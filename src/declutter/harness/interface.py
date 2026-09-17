"""Public-interface snapshot, by AST -- never by import.

Importing a module under test would run arbitrary code from the tree and
make the snapshot depend on the tree being importable, which a mid-cleanup
tree may not be. Instead every module is parsed with `ast.parse` on its
source text, and its public interface is read off the syntax tree.

"Public" means not leading-underscore. Dunder names (`__all__` aside) are
treated as private and excluded; this package keeps no dunder exception, so
every leading-underscore name -- single or double -- is dropped. `__all__`
itself is captured separately, when it is a literal list or tuple of string
constants (a computed `__all__` is recorded as absent rather than guessed
at).

Captured per module:

- `__all__`, as a sorted list of names, if present as a literal list/tuple
  of string constants; `None` otherwise.
- Public module-level functions, keyed by name, each with its full
  signature: parameter names in order, parameter kind (positional-only,
  positional-or-keyword, var-positional, keyword-only, var-keyword),
  whether each parameter has a default and the default's source text, each
  parameter's annotation source text, and the return annotation's source
  text. Annotation and default text is rendered with `ast.unparse`, so it
  is canonical rather than a raw slice of the source.
- Public classes, keyed by name, with their base class expressions (source
  text) and their public methods defined directly in the class body, using
  the same signature detail as functions.
- Public module-level assigned names (`x = ...` or `x: T = ...` at module
  scope), keyed by name, with the annotation source text if any.

The snapshot is emitted as a plain, JSON-serialisable structure; canonical
formatting (sorted keys) happens at serialisation time in
`declutter.harness.canon`, not here.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .errors import HarnessError


class InterfaceParseError(HarnessError):
    """A declared interface module's source could not be parsed."""


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _annotation_text(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    return ast.unparse(node)


def _params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
    args = node.args
    all_positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    n_no_default = len(all_positional) - len(defaults)

    params: list[dict] = []
    for i, arg in enumerate(args.posonlyargs):
        has_default = i >= n_no_default
        default = _annotation_text(defaults[i - n_no_default]) if has_default else None
        params.append(
            {
                "name": arg.arg,
                "kind": "POSITIONAL_ONLY",
                "annotation": _annotation_text(arg.annotation),
                "has_default": has_default,
                "default": default,
            }
        )
    offset = len(args.posonlyargs)
    for j, arg in enumerate(args.args):
        idx = offset + j
        has_default = idx >= n_no_default
        default = _annotation_text(defaults[idx - n_no_default]) if has_default else None
        params.append(
            {
                "name": arg.arg,
                "kind": "POSITIONAL_OR_KEYWORD",
                "annotation": _annotation_text(arg.annotation),
                "has_default": has_default,
                "default": default,
            }
        )
    if args.vararg is not None:
        params.append(
            {
                "name": args.vararg.arg,
                "kind": "VAR_POSITIONAL",
                "annotation": _annotation_text(args.vararg.annotation),
                "has_default": False,
                "default": None,
            }
        )
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
        has_default = kw_default is not None
        params.append(
            {
                "name": arg.arg,
                "kind": "KEYWORD_ONLY",
                "annotation": _annotation_text(arg.annotation),
                "has_default": has_default,
                "default": _annotation_text(kw_default) if has_default else None,
            }
        )
    if args.kwarg is not None:
        params.append(
            {
                "name": args.kwarg.arg,
                "kind": "VAR_KEYWORD",
                "annotation": _annotation_text(args.kwarg.annotation),
                "has_default": False,
                "default": None,
            }
        )
    return params


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "params": _params(node),
        "returns": _annotation_text(node.returns),
    }


def _module_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if node.targets[0].id != "__all__":
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return None
        names = []
        for elt in node.value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                return None
            names.append(elt.value)
        return sorted(names)
    return None


def snapshot_source(source: str) -> dict:
    """Parse `source` and return its public-interface snapshot as a plain dict."""
    tree = ast.parse(source)

    functions: dict[str, dict] = {}
    classes: dict[str, dict] = {}
    assigned: dict[str, dict] = {}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
            functions[node.name] = _signature(node)
        elif isinstance(node, ast.ClassDef) and _is_public(node.name):
            methods: dict[str, dict] = {}
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(member.name):
                    methods[member.name] = _signature(member)
            classes[node.name] = {
                "bases": [ast.unparse(base) for base in node.bases],
                "methods": methods,
            }
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_public(target.id) and target.id != "__all__":
                    assigned[target.id] = {"annotation": None}
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and _is_public(node.target.id):
                assigned[node.target.id] = {"annotation": _annotation_text(node.annotation)}

    return {
        "all": _module_all(tree),
        "functions": functions,
        "classes": classes,
        "assigned": assigned,
    }


def snapshot_modules(module_paths: tuple[str, ...], tree_root: Path) -> dict[str, dict | None]:
    """Snapshot every declared module, keyed by its declared relative path.

    A module whose file does not exist under `tree_root` is recorded as
    `None` -- this is not an error; a cleanup that deletes the whole file
    is exactly the kind of change the interface diff must be able to see
    as a removal, without the harness crashing on it.
    """
    result: dict[str, dict | None] = {}
    for rel_path in module_paths:
        path = tree_root / rel_path
        if not path.is_file():
            result[rel_path] = None
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise InterfaceParseError(f"could not read {rel_path}: {exc}") from exc
        try:
            result[rel_path] = snapshot_source(source)
        except SyntaxError as exc:
            raise InterfaceParseError(f"could not parse {rel_path}: {exc}") from exc
    return result


def _flatten(snapshot: dict) -> dict[str, object]:
    flat: dict[str, object] = {}
    if snapshot["all"] is not None:
        flat["__all__"] = snapshot["all"]
    for name, sig in snapshot["functions"].items():
        flat[f"function:{name}"] = sig
    for name, cls in snapshot["classes"].items():
        flat[f"class:{name}"] = {"bases": cls["bases"]}
        for method_name, sig in cls["methods"].items():
            flat[f"class:{name}.method:{method_name}"] = sig
    for name, info in snapshot["assigned"].items():
        flat[f"assigned:{name}"] = info
    return flat


def diff_module(baseline: dict | None, candidate: dict | None) -> dict:
    """Diff one module's snapshot. `status` is one of ok/added_module/removed_module."""
    if baseline is None and candidate is None:
        return {"status": "ok", "added": [], "removed": [], "changed": []}
    if baseline is None:
        return {"status": "added_module", "added": [], "removed": [], "changed": []}
    if candidate is None:
        return {"status": "removed_module", "added": [], "removed": [], "changed": []}

    b_flat = _flatten(baseline)
    c_flat = _flatten(candidate)
    added = sorted(set(c_flat) - set(b_flat))
    removed = sorted(set(b_flat) - set(c_flat))
    changed = sorted(k for k in (set(b_flat) & set(c_flat)) if b_flat[k] != c_flat[k])
    return {"status": "ok", "added": added, "removed": removed, "changed": changed}


def diff_interfaces(
    baseline: dict[str, dict | None], candidate: dict[str, dict | None]
) -> dict[str, dict]:
    """Diff every declared module's snapshot between baseline and candidate."""
    modules = sorted(set(baseline) | set(candidate))
    return {mod: diff_module(baseline.get(mod), candidate.get(mod)) for mod in modules}


def any_rejection(diff: dict[str, dict]) -> bool:
    """True if any module was removed or had a removed/changed member.

    An added module, or an added member, is informational only.
    """
    for entry in diff.values():
        if entry["status"] == "removed_module":
            return True
        if entry["removed"] or entry["changed"]:
            return True
    return False
