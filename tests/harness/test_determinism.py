"""Acceptance criterion 6 / acceptance test 2: two baseline runs over the same
unchanged tree must produce byte-identical artefacts.

Built on a small synthetic project under `tmp_path`, not on this repository,
so the check stays fast and hermetic. Assertion is on the raw artefact
bytes, not on a parsed structure.
"""

from __future__ import annotations

from declutter.harness.manifest import parse_manifest
from declutter.harness.runner import record

from .conftest import build_manifest_dict, write_project


def test_two_baseline_runs_are_byte_identical(tmp_path) -> None:
    tree = write_project(tmp_path / "tree")
    manifest = parse_manifest(build_manifest_dict())

    out1 = tmp_path / "baseline1"
    out2 = tmp_path / "baseline2"
    path1 = record(tree, manifest, out1)
    path2 = record(tree, manifest, out2)

    bytes1 = path1.read_bytes()
    bytes2 = path2.read_bytes()
    assert bytes1 == bytes2
    # Sanity: the artefact is not empty and is valid canonical JSON text.
    assert bytes1.endswith(b"\n")
    assert b'"schema_version": 1' in bytes1
