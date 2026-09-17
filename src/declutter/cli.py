"""The declutter command line interface.

`python -m declutter check` selects a set of files (by name, by git staging
area, by what changed since a ref, or everything under the extension
policy), scans each one against the pattern catalogue, applies any
`declutter: allow=...` pragmas, and reports what is left.

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

from . import policy, pragma
from .patterns import PATTERNS

SCHEMA_VERSION = 1


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
        help="Check files staged in git (git diff --name-only --cached --diff-filter=ACMR).",
    )
    selection.add_argument(
        "--changed-since",
        metavar="REF",
        help=(
            "Check files changed since REF: the union of "
            "'git diff --name-only --diff-filter=ACMR REF' and "
            "'git ls-files --others --exclude-standard', so an uncommitted "
            "planted file is found whether or not it is committed."
        ),
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Check every file under the extension and directory exclusion policy.",
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

    if args.files is not None:
        paths = _resolve_explicit_files(args.files, cwd)
    elif args.staged:
        paths = _selected_from_git_names(_git_staged_names(cwd), root)
    elif args.changed_since is not None:
        paths = _selected_from_git_names(
            _git_changed_since_names(cwd, args.changed_since), root
        )
    else:
        assert args.all
        paths = _walk_all(root)

    print(f"declutter: {len(paths)} file(s) selected", file=sys.stderr)

    report = _build_report(paths, root, critical_only=args.critical_only)

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


def _selected_from_git_names(names: Iterable[str], root: Path) -> list[Path]:
    # The directory exclusion policy applies here as well as in --all. Without
    # it the same tree gets opposite verdicts depending on the selection flag:
    # a tracked build/ or a vendored node_modules/ is skipped by --all but
    # reported by --staged and --changed-since, because git only filters the
    # untracked arm (via --exclude-standard) and never the tracked one.
    resolved: list[Path] = []
    for name in names:
        parts = Path(name).parts
        if any(policy.is_excluded_dir(part) for part in parts[:-1]):
            continue
        p = (root / name).resolve()
        if p.is_file() and policy.is_checked_extension(p.name):
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


def _git_staged_names(cwd: Path) -> list[str]:
    if _git_toplevel(cwd) is None:
        raise UsageError("--staged requires a git repository")
    out = _run_git(cwd, ["diff", "--name-only", "--cached", "--diff-filter=ACMR"])
    return [line for line in out.splitlines() if line]


def _git_changed_since_names(cwd: Path, ref: str) -> list[str]:
    if _git_toplevel(cwd) is None:
        raise UsageError("--changed-since requires a git repository")
    diffed = _run_git(cwd, ["diff", "--name-only", "--diff-filter=ACMR", ref])
    untracked = _run_git(cwd, ["ls-files", "--others", "--exclude-standard"])
    names = {line for line in diffed.splitlines() if line}
    names.update(line for line in untracked.splitlines() if line)
    return sorted(names)


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------


def _build_report(paths: list[Path], root: Path, *, critical_only: bool) -> dict:
    findings: list[dict] = []
    files_checked = 0
    files_skipped = 0

    for path in paths:
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
        findings.extend(_scan_text(text, rel))

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
