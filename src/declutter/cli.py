"""The declutter command line interface.

`python -m declutter check` selects a set of (file, touched-lines) pairs (by
name, by git staging area, by what changed since a ref, by explicit line
ranges, or everything under the extension policy), scans each file against
the pattern catalogue, applies any `declutter: allow=...` pragmas, drops
whatever lands outside the touched lines, and reports what is left.

Judgement is line-scoped by default, because whole-file judgement is
unusable at edit time: a repository with pre-existing findings would block
the first edit to any of those files for content the author never wrote.
`--whole-files` and `--all` opt back into whole-file judgement for a
retroactive sweep.

Only critical findings make the process exit non-zero. Warning and info
findings are always reported, never blocking, and `--critical-only` only
changes what is *reported* -- it does not change what blocks.

Every progress, status and diagnostic message goes to stderr. Stdout carries
only the human-readable report, or -- when `--output -` is given -- pure
JSON and nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

from . import policy, pragma, scope
from .patterns import PATTERNS
from .scope import TouchedLines

# 2 added summary.scope and summary.out_of_scope_findings, and narrowed
# counts_by_severity to in-scope findings only.
SCHEMA_VERSION = 2

SCOPE_CHANGED_LINES = "changed-lines"
SCOPE_CHANGED_FILES = "changed-files"
SCOPE_ALL = "all"

# A (path, touched-lines) pair is what every selection mode produces.
Selection = list[tuple[Path, TouchedLines]]


class UsageError(Exception):
    """A usage or I/O error: main() turns this into exit code 2."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="declutter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="Check a set of files against the pattern catalogue.",
        description=(
            "Check a set of files against the pattern catalogue. Exactly "
            "one selection flag is required."
        ),
    )
    selection = check.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--files",
        nargs="+",
        metavar="PATH",
        help="Check exactly these files (accepts one or more paths).",
    )
    selection.add_argument(
        "--staged",
        action="store_true",
        help=(
            "Check the lines staged in git, from "
            "'git diff --unified=0 --find-renames --cached'."
        ),
    )
    selection.add_argument(
        "--changed-since",
        metavar="REF",
        help=(
            "Check the lines changed since REF, from "
            "'git diff --unified=0 --find-renames REF', unioned with every "
            "untracked file from 'git ls-files --others --exclude-standard' "
            "(wholly touched, since every line in them is new)."
        ),
    )
    selection.add_argument(
        "--lines",
        action="append",
        metavar="PATH:START-END",
        help=(
            "Check only these lines of these files. Repeatable; ranges are "
            "1-based and inclusive, 'PATH:N' selects a single line, and "
            "repeating a path unions its ranges."
        ),
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Check every file under the extension and directory exclusion policy.",
    )
    check.add_argument(
        "--whole-files",
        action="store_true",
        help=(
            "Judge whole files rather than only the changed lines. Intended "
            "for a retroactive sweep. Contradicts --lines."
        ),
    )
    check.add_argument(
        "--critical-only",
        action="store_true",
        help=(
            "Report only critical findings. This filters what is reported, "
            "not what blocks: only critical findings ever make the exit "
            "code non-zero, with or without this flag."
        ),
    )
    check.add_argument(
        "--output",
        metavar="FILE",
        help=(
            "Write the JSON report to FILE. Use '-' to write JSON to "
            "stdout instead of the human-readable report, so stdout is "
            "pure JSON."
        ),
    )
    check.set_defaults(func=_cmd_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed its message (usage errors to stderr,
        # --help to stdout) and calls sys.exit with the code below.
        code = exc.code if isinstance(exc.code, int) else 2
        return 0 if code == 0 else 2

    try:
        return args.func(args)
    except UsageError as exc:
        print(f"declutter: {exc}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def _cmd_check(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    root = _git_toplevel(cwd) or cwd

    if args.lines is not None and args.whole_files:
        # Naming ranges and then asking for the whole file cannot both be
        # meant, and guessing which one the caller wanted would silently
        # change what blocks their commit.
        raise UsageError("--whole-files contradicts --lines")

    if args.files is not None:
        selection = _select_explicit_files(args.files, cwd)
        scope_name = SCOPE_CHANGED_FILES
    elif args.lines is not None:
        selection = _select_explicit_lines(args.lines, cwd)
        scope_name = SCOPE_CHANGED_LINES
    elif args.staged:
        # Deliberate: the file read below is the one on disk, not the staged
        # blob, because the checker and the edit hook both judge the working
        # tree. The cost is that unstaged edits layered on top of staged ones
        # shift line numbers relative to this HEAD-to-index diff. That is not
        # fixed here on purpose; the README explains it.
        selection = _select_from_touched(_git_staged_touched(cwd), root)
        scope_name = SCOPE_CHANGED_LINES
    elif args.changed_since is not None:
        selection = _select_from_touched(
            _git_changed_since_touched(cwd, args.changed_since), root
        )
        scope_name = SCOPE_CHANGED_LINES
    else:
        assert args.all
        selection = _select_all(root, cwd)
        scope_name = SCOPE_ALL

    if args.whole_files and scope_name == SCOPE_CHANGED_LINES:
        selection = [(path, TouchedLines.whole()) for path, _ in selection]
        scope_name = SCOPE_CHANGED_FILES

    print(f"declutter: {len(selection)} file(s) selected", file=sys.stderr)

    report = _build_report(
        selection, root, critical_only=args.critical_only, scope_name=scope_name
    )

    should_print_human = args.output != "-"
    if should_print_human:
        _print_human_report(report)

    if args.output is not None:
        _write_json(report, args.output)

    return report["exit_code"]


# --------------------------------------------------------------------------
# file selection
# --------------------------------------------------------------------------


def _resolve_explicit_files(raw_paths: Iterable[str], cwd: Path) -> list[Path]:
    resolved: list[Path] = []
    for raw in raw_paths:
        p = Path(raw)
        abs_p = p if p.is_absolute() else cwd / p
        if not abs_p.is_file():
            raise UsageError(f"no such file: {raw}")
        if policy.is_checked_extension(abs_p.name):
            resolved.append(abs_p.resolve())
    return _dedupe_sorted(resolved)


def _select_explicit_files(raw_paths: Iterable[str], cwd: Path) -> Selection:
    return [(path, TouchedLines.whole()) for path in _resolve_explicit_files(raw_paths, cwd)]


def _select_explicit_lines(raw_values: Sequence[str], cwd: Path) -> Selection:
    """--lines names files and their ranges at once, so it is its own mode."""
    try:
        by_path = scope.parse_lines_arguments(raw_values)
    except scope.ScopeError as exc:
        raise UsageError(str(exc)) from exc

    selection: Selection = []
    for raw, touched in by_path.items():
        p = Path(raw)
        abs_p = p if p.is_absolute() else cwd / p
        if not abs_p.is_file():
            raise UsageError(f"no such file: {raw}")
        if policy.is_checked_extension(abs_p.name):
            selection.append((abs_p.resolve(), touched))
    return _sorted_selection(selection)


def _select_from_touched(touched: dict[str, TouchedLines], root: Path) -> Selection:
    # The directory exclusion policy applies here as well as in --all. Without
    # it the same tree gets opposite verdicts depending on the selection flag:
    # a tracked build/ or a vendored node_modules/ is skipped by --all but
    # reported by --staged and --changed-since, because git only filters the
    # untracked arm (via --exclude-standard) and never the tracked one.
    selection: Selection = []
    for name, lines in touched.items():
        # A file whose only hunks were pure deletions has nothing on disk left
        # to judge, so it never reaches the scanner at all.
        if lines.is_empty():
            continue
        parts = Path(name).parts
        if any(policy.is_excluded_dir(part) for part in parts[:-1]):
            continue
        p = (root / name).resolve()
        if p.is_file() and policy.is_checked_extension(p.name):
            selection.append((p, lines))
    return _sorted_selection(selection)


def _select_all(root: Path, cwd: Path) -> Selection:
    return [(path, TouchedLines.whole()) for path in _all_paths(root, cwd)]


def _all_paths(root: Path, cwd: Path) -> list[Path]:
    """Every checkable file in the tree.

    Inside a repository this asks git, so that --all inherits .gitignore and
    every other exclusion the author already wrote down -- without it, an
    inventory run is polluted by ignored trees such as nested checkouts under
    .claude/worktrees. Outside a repository there is nobody to ask, so the
    os.walk of the original implementation stands.

    The DEFAULT_EXCLUDED_DIRS policy is layered on top either way: a tree
    committed with `git add -f` is listed by git but is still generated, and
    the two selection paths must agree about it.
    """
    listed = _git_all_names(root)
    if listed is None:
        return _walk_all(root)

    resolved: list[Path] = []
    for name in listed:
        parts = Path(name).parts
        if any(policy.is_excluded_dir(part) for part in parts[:-1]):
            continue
        if not policy.is_checked_extension(Path(name).name):
            continue
        p = (root / name).resolve()
        # --cached lists tracked-but-deleted paths, and --others lists a
        # nested checkout as a bare directory entry; neither is a file here.
        if p.is_file():
            resolved.append(p)
    return _dedupe_sorted(resolved)


def _walk_all(root: Path) -> list[Path]:
    resolved: list[Path] = []
    for dirpath, dirnames, filenames in _walk(root):
        dirnames[:] = [d for d in dirnames if not policy.is_excluded_dir(d)]
        for filename in filenames:
            if policy.is_checked_extension(filename):
                resolved.append(Path(dirpath) / filename)
    return _dedupe_sorted(resolved)


def _walk(root: Path):
    yield from os.walk(root)


def _dedupe_sorted(paths: Iterable[Path]) -> list[Path]:
    return sorted(set(paths), key=lambda p: p.as_posix())


def _sorted_selection(selection: Selection) -> Selection:
    merged: dict[Path, TouchedLines] = {}
    for path, lines in selection:
        existing = merged.get(path)
        merged[path] = lines if existing is None else existing.union(lines)
    return sorted(merged.items(), key=lambda item: item[0].as_posix())


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _run_git(cwd: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise UsageError("git is required for this selection mode, and was not found") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or f"git {' '.join(args)} failed"
        raise UsageError(message)
    return result.stdout


# --find-renames is passed explicitly rather than left to the user's git
# config, so two people running declutter on the same change get the same
# answer. --unified=0 is what makes a hunk header name exactly the changed
# lines and nothing around them.
_DIFF_BASE = ["diff", "--unified=0", "--find-renames"]


def _git_staged_touched(cwd: Path) -> dict[str, TouchedLines]:
    if _git_toplevel(cwd) is None:
        raise UsageError("--staged requires a git repository")
    return scope.parse_diff_touched_lines(_run_git(cwd, [*_DIFF_BASE, "--cached"]))


def _git_changed_since_touched(cwd: Path, ref: str) -> dict[str, TouchedLines]:
    if _git_toplevel(cwd) is None:
        raise UsageError("--changed-since requires a git repository")
    touched = scope.parse_diff_touched_lines(_run_git(cwd, [*_DIFF_BASE, ref]))
    untracked = _run_git(cwd, ["ls-files", "--others", "--exclude-standard"])
    for name in untracked.splitlines():
        if name:
            # Every line in an untracked file is new, so it is wholly touched.
            scope.merge_touched(touched, name, TouchedLines.whole())
    return touched


def _git_all_names(root: Path) -> list[str] | None:
    """Every path git knows about at `root`, or None when there is no repo."""
    if _git_toplevel(root) is None:
        return None
    out = _run_git(root, ["ls-files", "--cached", "--others", "--exclude-standard"])
    return [line for line in out.splitlines() if line]


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------


def _build_report(
    selection: Selection | Iterable[Path],
    root: Path,
    *,
    critical_only: bool,
    scope_name: str = SCOPE_ALL,
) -> dict:
    findings: list[dict] = []
    files_checked = 0
    files_skipped = 0
    out_of_scope = 0

    # A bare Path means whole-file judgement: that is what a caller who never
    # named any lines is asking for, and it keeps in-process callers (the
    # prompt dogfooding test, for one) from having to build a Selection.
    for path, touched in (
        item if isinstance(item, tuple) else (item, TouchedLines.whole())
        for item in selection
    ):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise UsageError(f"could not read {path}: {exc}") from exc

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            files_skipped += 1
            continue

        files_checked += 1
        rel = _repo_relative(path, root)
        for finding in _scan_text(text, rel):
            # Detected either way, but only judged when the author touched the
            # line. Dropping it silently would hide how much the scope cost, so
            # the count is reported.
            if touched.contains(finding["line"]):
                findings.append(finding)
            else:
                out_of_scope += 1

    # Count before filtering. --critical-only narrows what is *reported*, not
    # what was found, and summary.counts_by_severity is the machine-readable
    # record of the scan: a consumer reading warning=0 out of the uploaded JSON
    # must not conclude the tree is clean of warnings merely because the run
    # was asked to print criticals only.
    counts_by_severity = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        counts_by_severity[finding["severity"]] += 1

    if critical_only:
        findings = [f for f in findings if f["severity"] == "critical"]

    findings.sort(key=lambda f: (f["path"], f["line"], f["column"], f["pattern"]))

    exit_code = 1 if counts_by_severity["critical"] > 0 else 0

    return {
        "schema_version": SCHEMA_VERSION,
        "findings": findings,
        "summary": {
            "files_checked": files_checked,
            "files_skipped": files_skipped,
            "counts_by_severity": counts_by_severity,
            "scope": scope_name,
            "out_of_scope_findings": out_of_scope,
        },
        "exit_code": exit_code,
    }


def _scan_text(text: str, rel_path: str) -> list[dict]:
    findings: list[dict] = []
    # Split on bare "\n" only: this preserves a trailing "\r" as part of the
    # line's text (rather than stripping it), so a CRLF file and its LF twin
    # produce identical line numbers and identical match positions.
    lines = text.split("\n")
    for lineno, line in enumerate(lines, start=1):
        exempt = pragma.allowed_names(line)
        for pat in PATTERNS:
            if pat.name in exempt:
                continue
            for match in pat.pattern.finditer(line):
                findings.append(
                    {
                        "path": rel_path,
                        "line": lineno,
                        "column": match.start() + 1,
                        "pattern": pat.name,
                        "severity": pat.severity,
                        "match": match.group(0),
                    }
                )
    return findings


def _repo_relative(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = path.resolve()
    return rel.as_posix()


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def _print_human_report(report: dict) -> None:
    for finding in report["findings"]:
        print(
            f'{finding["path"]}:{finding["line"]}:{finding["column"]}: '
            f'{finding["severity"]} {finding["pattern"]}: {finding["match"]}'
        )
    summary = report["summary"]
    counts = summary["counts_by_severity"]
    print(
        "declutter: {checked} file(s) checked, {skipped} skipped -- "
        "critical={critical} warning={warning} info={info}".format(
            checked=summary["files_checked"],
            skipped=summary["files_skipped"],
            critical=counts["critical"],
            warning=counts["warning"],
            info=counts["info"],
        )
    )


def _write_json(report: dict, output: str) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output == "-":
        sys.stdout.write(payload)
        return
    try:
        with open(output, "wb") as fh:
            fh.write(payload.encode("utf-8"))
    except OSError as exc:
        raise UsageError(f"could not write {output}: {exc}") from exc


if __name__ == "__main__":
    sys.exit(main())
