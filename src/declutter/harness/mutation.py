"""Deterministic mutation testing over declared target modules.

Fixed operator set (this is the complete list; it is not configurable,
because a configurable operator set is a set that drifts):

- `cmp_swap` -- swap a single comparison operator for its complement:
  `==`/`!=`, `<`/`>=`, `<=`/`>`, `is`/`is not`, `in`/`not in`. Only applies
  to a `Compare` node with exactly one operator; a chained comparison
  (`a < b < c`) is not a mutation site, to keep site identification
  unambiguous.
- `bool_op_swap` -- swap `and`/`or` on a `BoolOp` node.
- `arith_op_swap` -- swap `+`/`-` and `*`/`//` on a `BinOp` node.
- `bool_const_invert` -- invert a literal `True`/`False` constant.
- `num_const_perturb` -- add 1 to a literal int or float constant (not a
  bool, which is `int`'s subclass but is handled by `bool_const_invert`
  instead).

Mutation sites are enumerated by a deterministic AST walk: `ast.parse` is a
pure function of source text, and child traversal order follows the fixed
field order of each node type, so the same source always yields the same
walk. Sites are then sorted by the total key `(path, lineno, col_offset,
node_class, operator_id)`, and each mutant's id is derived from that same
key -- never from a counter or an index into the sorted list -- so ids do
not depend on traversal accidents.

If the manifest caps the mutant count with `max_mutants`, the first N sites
in that deterministic order are run. There is no random sampling: the
manifest schema has no seed field for it, and none is implemented here,
per the project's preference for no sampling over a sampling scheme that
would need one more piece of determinism to get right.

Every mutation site is attributed to its enclosing qualified function name
(`path::Class.method` or `path::function`, dotted for nested functions). A
site not inside any function -- module scope, or directly in a class body
outside any method -- is attributed to a module-level bucket
(`path::<module>`) and excluded from the per-qualified-name kill-rate
comparison that gates acceptance (Amendment C).

A mutant is killed if the declared test command exits non-zero, or times
out; it survives if the test command exits zero. The tree under test is
never mutated in place: one scratch copy is made per run, and each mutant
overwrites and then restores the one target file it touches before the
next mutant runs, so mutants never observe each other.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import HarnessError
from .manifest import Manifest, MutationConfig, ScrubRule
from .procrun import run

# Directory names never copied into the mutation scratch tree.
_SCRATCH_IGNORE = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".venv",
    "venv",
    "build",
    "dist",
    ".tox",
}


class MutationError(HarnessError):
    """A target module could not be parsed, or the scratch copy failed."""


_CMP_SWAP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}

_BOOL_SWAP: dict[type, type] = {ast.And: ast.Or, ast.Or: ast.And}

_ARITH_SWAP: dict[type, type] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.FloorDiv,
    ast.FloorDiv: ast.Mult,
}


def _cmp_applies(node: ast.AST) -> bool:
    return isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP_SWAP


def _cmp_mutate(node: ast.AST) -> None:
    assert isinstance(node, ast.Compare)
    node.ops[0] = _CMP_SWAP[type(node.ops[0])]()


def _bool_op_applies(node: ast.AST) -> bool:
    return isinstance(node, ast.BoolOp) and type(node.op) in _BOOL_SWAP


def _bool_op_mutate(node: ast.AST) -> None:
    assert isinstance(node, ast.BoolOp)
    node.op = _BOOL_SWAP[type(node.op)]()


def _arith_applies(node: ast.AST) -> bool:
    return isinstance(node, ast.BinOp) and type(node.op) in _ARITH_SWAP


def _arith_mutate(node: ast.AST) -> None:
    assert isinstance(node, ast.BinOp)
    node.op = _ARITH_SWAP[type(node.op)]()


def _bool_const_applies(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _bool_const_mutate(node: ast.AST) -> None:
    assert isinstance(node, ast.Constant)
    node.value = not node.value


def _num_const_applies(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def _num_const_mutate(node: ast.AST) -> None:
    assert isinstance(node, ast.Constant)
    node.value = node.value + 1


@dataclass(frozen=True)
class _Operator:
    id: str
    node_types: tuple
    applies: object  # Callable[[ast.AST], bool]
    mutate: object  # Callable[[ast.AST], None]


OPERATORS: tuple[_Operator, ...] = (
    _Operator("arith_op_swap", (ast.BinOp,), _arith_applies, _arith_mutate),
    _Operator("bool_const_invert", (ast.Constant,), _bool_const_applies, _bool_const_mutate),
    _Operator("bool_op_swap", (ast.BoolOp,), _bool_op_applies, _bool_op_mutate),
    _Operator("cmp_swap", (ast.Compare,), _cmp_applies, _cmp_mutate),
    _Operator("num_const_perturb", (ast.Constant,), _num_const_applies, _num_const_mutate),
)

_OPERATORS_BY_ID = {op.id: op for op in OPERATORS}


@dataclass(frozen=True)
class MutationSite:
    path: str
    lineno: int
    col_offset: int
    node_class: str
    operator_id: str
    qualified_name: str  # e.g. "pkg/core.py::Class.method" or "pkg/core.py::<module>"

    @property
    def mutant_id(self) -> str:
        return f"{self.path}:{self.lineno}:{self.col_offset}:{self.node_class}:{self.operator_id}"

    @property
    def sort_key(self):
        return (self.path, self.lineno, self.col_offset, self.node_class, self.operator_id)


def _enclosing_scope_stack(tree: ast.Module):
    """Yield (node, scope_stack) for every node, tracking (kind, name) frames."""

    def walk(node: ast.AST, stack: tuple[tuple[str, str], ...]):
        yield node, stack
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_stack = stack + (("function", node.name),)
        elif isinstance(node, ast.ClassDef):
            next_stack = stack + (("class", node.name),)
        else:
            next_stack = stack
        for child in ast.iter_child_nodes(node):
            yield from walk(child, next_stack)

    yield from walk(tree, ())


def _qualified_name(rel_path: str, scope_stack: tuple[tuple[str, str], ...]) -> str:
    if scope_stack and scope_stack[-1][0] == "function":
        dotted = ".".join(name for _, name in scope_stack)
        return f"{rel_path}::{dotted}"
    return f"{rel_path}::<module>"


def enumerate_sites(source: str, rel_path: str) -> list[MutationSite]:
    """Enumerate every mutation site in `source`, sorted by the total key."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise MutationError(f"could not parse {rel_path}: {exc}") from exc

    sites: list[MutationSite] = []
    for node, scope_stack in _enclosing_scope_stack(tree):
        qualified_name = _qualified_name(rel_path, scope_stack)
        for op in OPERATORS:
            if isinstance(node, op.node_types) and op.applies(node):
                sites.append(
                    MutationSite(
                        path=rel_path,
                        lineno=node.lineno,
                        col_offset=node.col_offset,
                        node_class=type(node).__name__,
                        operator_id=op.id,
                        qualified_name=qualified_name,
                    )
                )
    sites.sort(key=lambda s: s.sort_key)
    return sites


def _apply_mutation(source: str, site: MutationSite) -> str:
    tree = ast.parse(source)
    op = _OPERATORS_BY_ID[site.operator_id]
    target = None
    for node in ast.walk(tree):
        if (
            type(node).__name__ == site.node_class
            and getattr(node, "lineno", None) == site.lineno
            and getattr(node, "col_offset", None) == site.col_offset
        ):
            target = node
            break
    if target is None:
        raise MutationError(f"could not relocate mutation site {site.mutant_id}")
    op.mutate(target)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _copy_tree(tree_root: Path, scratch_root: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _SCRATCH_IGNORE or n.endswith(".egg-info")}

    shutil.copytree(tree_root, scratch_root, ignore=ignore, dirs_exist_ok=True)


def run_mutation(tree_root: Path, manifest: Manifest) -> dict:
    """Enumerate and run every mutation site declared by the manifest's mutation config.

    Returns a plain dict artefact: `mutants` (mutant id -> outcome detail),
    `by_qualified_name` (kill/total counts, excluding the module-level
    bucket), `module_level` (kill/total counts for sites not inside any
    function), and `config` (the effective mutation configuration, for
    provenance).
    """
    config: MutationConfig = manifest.mutation

    if not config.target_modules:
        return {
            "mutants": {},
            "by_qualified_name": {},
            "module_level": {"killed": 0, "total": 0},
            "config": {
                "target_modules": [],
                "max_mutants": config.max_mutants,
                "kill_rate_tolerance": config.kill_rate_tolerance,
                "total_sites": 0,
                "mutants_run": 0,
            },
        }

    assert config.test_command is not None

    sources: dict[str, str] = {}
    all_sites: list[MutationSite] = []
    for rel_path in config.target_modules:
        path = tree_root / rel_path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MutationError(f"could not read target module {rel_path}: {exc}") from exc
        sources[rel_path] = source
        all_sites.extend(enumerate_sites(source, rel_path))

    all_sites.sort(key=lambda s: s.sort_key)
    total_sites = len(all_sites)
    sites = all_sites if config.max_mutants is None else all_sites[: config.max_mutants]

    scratch_root = Path(tempfile.mkdtemp(prefix="declutter-harness-mutation-"))
    try:
        _copy_tree(tree_root, scratch_root)
        mutants: dict[str, dict] = {}
        for site in sites:
            mutated_source = _apply_mutation(sources[site.path], site)
            scratch_file = scratch_root / site.path
            original_bytes = scratch_file.read_bytes()
            scratch_file.write_text(mutated_source, encoding="utf-8")
            try:
                result = _run_test_command(scratch_root, config, manifest.default_timeout, manifest.scrub_rules)
            finally:
                scratch_file.write_bytes(original_bytes)

            killed = result.timed_out or (result.exit_code is not None and result.exit_code != 0)
            mutants[site.mutant_id] = {
                "path": site.path,
                "lineno": site.lineno,
                "col_offset": site.col_offset,
                "node_class": site.node_class,
                "operator_id": site.operator_id,
                "qualified_name": site.qualified_name,
                "outcome": "killed" if killed else "survived",
                "timed_out": result.timed_out,
            }
    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)

    by_qualified_name: dict[str, dict] = {}
    module_level = {"killed": 0, "total": 0}
    for detail in mutants.values():
        qname = detail["qualified_name"]
        killed = detail["outcome"] == "killed"
        if qname.endswith("::<module>"):
            module_level["total"] += 1
            if killed:
                module_level["killed"] += 1
            continue
        bucket = by_qualified_name.setdefault(qname, {"killed": 0, "total": 0})
        bucket["total"] += 1
        if killed:
            bucket["killed"] += 1

    return {
        "mutants": mutants,
        "by_qualified_name": by_qualified_name,
        "module_level": module_level,
        "config": {
            "target_modules": list(config.target_modules),
            "max_mutants": config.max_mutants,
            "kill_rate_tolerance": config.kill_rate_tolerance,
            "total_sites": total_sites,
            "mutants_run": len(sites),
        },
    }


def _run_test_command(scratch_root: Path, config: MutationConfig, default_timeout: float, scrub_rules: tuple[ScrubRule, ...]):
    assert config.test_command is not None
    cwd = (scratch_root / config.test_command.cwd).resolve()
    timeout = config.test_command.timeout if config.test_command.timeout is not None else default_timeout
    return run(
        config.test_command.argv,
        cwd=cwd,
        env_overlay=config.test_command.env_dict(),
        timeout=timeout,
        scrub_rules=(),
    )


AMENDMENT_C_POLICY = (
    "Kill rate is gated only on qualified function names present in both "
    "baseline and candidate under the same name; a name removed, renamed "
    "or merged is reported in removed_or_merged and never affects the "
    "exit code, and a name new in the candidate is reported in added and "
    "is likewise informational only."
)


def compare_kill_rates(
    baseline_by_qualified_name: dict[str, dict],
    candidate_by_qualified_name: dict[str, dict],
    tolerance: float,
) -> dict:
    """Amendment C: gate only on qualified names present in both baseline and candidate."""
    common = sorted(set(baseline_by_qualified_name) & set(candidate_by_qualified_name))
    removed_or_merged = sorted(set(baseline_by_qualified_name) - set(candidate_by_qualified_name))
    added = sorted(set(candidate_by_qualified_name) - set(baseline_by_qualified_name))

    gated: dict[str, dict] = {}
    regressions: list[str] = []
    for name in common:
        b = baseline_by_qualified_name[name]
        c = candidate_by_qualified_name[name]
        b_rate = b["killed"] / b["total"] if b["total"] else None
        c_rate = c["killed"] / c["total"] if c["total"] else None
        gated[name] = {
            "baseline": b,
            "candidate": c,
            "baseline_rate": b_rate,
            "candidate_rate": c_rate,
        }
        if b_rate is not None and c_rate is not None and c_rate < b_rate - tolerance:
            regressions.append(name)

    return {
        "policy": AMENDMENT_C_POLICY,
        "tolerance": tolerance,
        "common": gated,
        "removed_or_merged": removed_or_merged,
        "added": added,
        "regressions": regressions,
    }


def any_regression(kill_rate_comparison: dict) -> bool:
    return len(kill_rate_comparison["regressions"]) > 0
