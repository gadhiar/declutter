"""The shipped example manifest at tests/harness/fixtures is a working example:
record a baseline from the fixture project, then verify the same tree
against it, and expect an accept.
"""

from __future__ import annotations

import json
from pathlib import Path

from declutter.harness.manifest import parse_manifest
from declutter.harness.runner import capture, compare, record

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_shipped_example_manifest_is_well_formed_and_self_consistent(tmp_path) -> None:
    manifest_data = json.loads((FIXTURES / "example_manifest.json").read_text(encoding="utf-8"))
    manifest = parse_manifest(manifest_data)
    tree = FIXTURES / "example_project"

    baseline_dir = tmp_path / "baseline"
    record(tree, manifest, baseline_dir)
    baseline_artefact = json.loads((baseline_dir / "baseline.json").read_text(encoding="utf-8"))

    candidate_artefact = capture(tree, manifest)
    report = compare(baseline_artefact, candidate_artefact, manifest)

    assert report["verdict"] == "accept"
    assert report["reasons"] == []
