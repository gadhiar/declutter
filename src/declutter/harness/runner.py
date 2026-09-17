"""Capture one tree's behaviour under a manifest, and compare two captures.

`capture` runs all three detectors -- CLI byte differential, interface
snapshot, mutation -- against one tree, and returns a plain,
JSON-serialisable artefact. `record` wraps `capture` with the manifest
itself for provenance and writes it out as canonical JSON. `compare` diffs
two captures and produces the report `verify` prints and writes.
"""

from __future__ import annotations

from pathlib import Path

from . import cli_diff, interface, mutation
from .canon import write_canonical_json
from .errors import HarnessError
from .manifest import Manifest, manifest_to_dict

SCHEMA_VERSION = 1


class TreeError(HarnessError):
    """The declared tree does not exist or is not a directory."""


def _require_tree(tree: Path) -> None:
    if not tree.is_dir():
        raise TreeError(f"no such directory: {tree}")


def capture(tree: Path, manifest: Manifest) -> dict:
    """Run every detector against `tree` and return the resulting artefact."""
    _require_tree(tree)
    cli_results = cli_diff.run_invocations(tree, manifest)
    interface_snapshot = interface.snapshot_modules(manifest.interface_modules, tree)
    mutation_results = mutation.run_mutation(tree, manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "cli": cli_results,
        "interface": interface_snapshot,
        "mutation": mutation_results,
    }


def record(tree: Path, manifest: Manifest, output_dir: Path) -> Path:
    """Capture `tree` and write it as a baseline artefact under `output_dir`.

    Returns the path written. The manifest itself is embedded in the
    artefact for provenance, so a later `verify` can be checked against it.
    """
    artefact = capture(tree, manifest)
    artefact["manifest"] = manifest_to_dict(manifest)
    baseline_path = output_dir / "baseline.json"
    write_canonical_json(baseline_path, artefact)
    return baseline_path


def compare(baseline_artefact: dict, candidate_artefact: dict, manifest: Manifest) -> dict:
    """Diff a loaded baseline artefact against a freshly captured candidate artefact."""
    cli_result_diff = cli_diff.diff_invocation_results(
        baseline_artefact["cli"], candidate_artefact["cli"]
    )
    interface_result_diff = interface.diff_interfaces(
        baseline_artefact["interface"], candidate_artefact["interface"]
    )
    mutation_result_diff = mutation.compare_kill_rates(
        baseline_artefact["mutation"]["by_qualified_name"],
        candidate_artefact["mutation"]["by_qualified_name"],
        manifest.mutation.kill_rate_tolerance,
    )

    reasons: list[str] = []
    if cli_diff.any_mismatch(cli_result_diff):
        reasons.append("cli byte differential mismatch on at least one invocation")
    if interface.any_rejection(interface_result_diff):
        reasons.append("public interface removal or change on at least one declared module")
    if mutation.any_regression(mutation_result_diff):
        reasons.append("mutation kill-rate regression on at least one qualified name common to both trees")

    verdict = "reject" if reasons else "accept"

    return {
        "schema_version": SCHEMA_VERSION,
        "policy": {"amendment_c": mutation.AMENDMENT_C_POLICY},
        "cli_diff": cli_result_diff,
        "interface_diff": interface_result_diff,
        "mutation_diff": mutation_result_diff,
        "verdict": verdict,
        "reasons": reasons,
    }
