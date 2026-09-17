"""The declutter.harness command line interface.

`python -m declutter.harness record --tree TREE --manifest MANIFEST --output DIR`
captures a baseline from `TREE` under the rules in `MANIFEST` and writes it
as canonical JSON to `DIR/baseline.json`.

`python -m declutter.harness verify --tree TREE --manifest MANIFEST --baseline BASELINE [--output FILE]`
captures `TREE` the same way, compares it against the recorded baseline
(a `record` output directory, or a `baseline.json` file directly), and
reports the result.

Every progress and diagnostic message goes to stderr. Stdout carries the
human-readable summary by default; `--output -` writes pure JSON to stdout
instead, and any other `--output FILE` additionally writes the JSON report
to `FILE` while still printing the human summary to stdout.

Exit codes: 0 accept, 1 reject (a byte differential mismatch, an interface
removal or change, or a kill-rate regression on a name common to both
trees), 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .canon import canonical_bytes
from .errors import HarnessError
from .manifest import Manifest, parse_manifest
from .runner import capture, compare, record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="declutter.harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser(
        "record",
        help="Record a baseline from a tree plus a manifest into an output directory.",
    )
    record_parser.add_argument("--tree", required=True, metavar="PATH", help="The tree to capture.")
    record_parser.add_argument("--manifest", required=True, metavar="PATH", help="The manifest JSON file.")
    record_parser.add_argument("--output", required=True, metavar="DIR", help="Output directory for baseline.json.")
    record_parser.set_defaults(func=_cmd_record)

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a candidate tree against a recorded baseline, emitting a comparison report.",
    )
    verify_parser.add_argument("--tree", required=True, metavar="PATH", help="The candidate tree.")
    verify_parser.add_argument("--manifest", required=True, metavar="PATH", help="The manifest JSON file.")
    verify_parser.add_argument(
        "--baseline",
        required=True,
        metavar="PATH",
        help="A record output directory, or a baseline.json file directly.",
    )
    verify_parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write the JSON report to FILE. Use '-' to write JSON to stdout instead of the human summary.",
    )
    verify_parser.set_defaults(func=_cmd_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return 0 if code == 0 else 2

    try:
        return args.func(args)
    except HarnessError as exc:
        print(f"declutter.harness: {exc}", file=sys.stderr)
        return 2


def _load_manifest(path_str: str) -> Manifest:
    path = Path(path_str)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"could not read manifest {path_str}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"manifest {path_str} is not valid JSON: {exc}") from exc
    return parse_manifest(data)


def _cmd_record(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    tree = Path(args.tree)
    output_dir = Path(args.output)
    print(f"declutter.harness: capturing baseline from {args.tree}", file=sys.stderr)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = record(tree, manifest, output_dir)
    print(
        f"declutter.harness: recorded {len(manifest.invocations)} invocation(s), "
        f"{len(manifest.interface_modules)} interface module(s), "
        f"{len(manifest.mutation.target_modules)} mutation target(s)",
        file=sys.stdout,
    )
    print(f"declutter.harness: baseline written to {baseline_path}", file=sys.stderr)
    return 0


def _load_baseline_artefact(baseline_str: str) -> dict:
    path = Path(baseline_str)
    if path.is_dir():
        path = path / "baseline.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"could not read baseline {baseline_str}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"baseline {baseline_str} is not valid JSON: {exc}") from exc


def _cmd_verify(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    tree = Path(args.tree)
    baseline_artefact = _load_baseline_artefact(args.baseline)

    print(f"declutter.harness: capturing candidate from {args.tree}", file=sys.stderr)
    candidate_artefact = capture(tree, manifest)

    report = compare(baseline_artefact, candidate_artefact, manifest)

    should_print_human = args.output != "-"
    if should_print_human:
        _print_human_report(report)
    if args.output is not None:
        _write_json(report, args.output)

    return 0 if report["verdict"] == "accept" else 1


def _print_human_report(report: dict) -> None:
    cli_mismatches = sum(1 for e in report["cli_diff"].values() if not e["match"])
    print(
        f"declutter.harness: cli: {len(report['cli_diff'])} invocation(s) checked, "
        f"{cli_mismatches} mismatch(es)"
    )

    removed_modules = sum(1 for e in report["interface_diff"].values() if e["status"] == "removed_module")
    changed_members = sum(len(e["changed"]) for e in report["interface_diff"].values())
    removed_members = sum(len(e["removed"]) for e in report["interface_diff"].values())
    added_members = sum(len(e["added"]) for e in report["interface_diff"].values())
    print(
        f"declutter.harness: interface: {removed_modules} module(s) removed, "
        f"{removed_members} member(s) removed, {changed_members} member(s) changed, "
        f"{added_members} member(s) added"
    )

    mdiff = report["mutation_diff"]
    print(
        f"declutter.harness: mutation: {len(mdiff['regressions'])} regression(s) on "
        f"{len(mdiff['common'])} common qualified name(s); "
        f"{len(mdiff['removed_or_merged'])} removed_or_merged (informational); "
        f"{len(mdiff['added'])} added (informational)"
    )

    print(f"declutter.harness: verdict={report['verdict']}")
    for reason in report["reasons"]:
        print(f"declutter.harness: reason: {reason}")


def _write_json(report: dict, output: str) -> None:
    payload = canonical_bytes(report)
    if output == "-":
        sys.stdout.buffer.write(payload)
        return
    try:
        with open(output, "wb") as fh:
            fh.write(payload)
    except OSError as exc:
        raise HarnessError(f"could not write {output}: {exc}") from exc


if __name__ == "__main__":
    sys.exit(main())
