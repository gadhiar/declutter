"""Acceptance test 5: `python -m declutter.harness --help` works under
PYTHONPATH=src with no installed package, plus a minimal subprocess-level
record/verify round trip.
"""

from __future__ import annotations

import json

from .conftest import build_manifest_dict, write_project


def test_help_works_with_pythonpath_and_no_installed_package(run_harness, tmp_path) -> None:
    result = run_harness(["--help"], cwd=tmp_path)
    assert result.returncode == 0
    assert b"record" in result.stdout
    assert b"verify" in result.stdout


def test_record_then_verify_round_trip_via_subprocess(run_harness, tmp_path) -> None:
    tree = write_project(tmp_path / "tree")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(build_manifest_dict(max_mutants=5)), encoding="utf-8")

    baseline_dir = tmp_path / "baseline"
    record_result = run_harness(
        ["record", "--tree", str(tree), "--manifest", str(manifest_path), "--output", str(baseline_dir)],
        cwd=tmp_path,
    )
    assert record_result.returncode == 0, record_result.stderr
    assert (baseline_dir / "baseline.json").is_file()

    verify_result = run_harness(
        [
            "verify",
            "--tree",
            str(tree),
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_dir),
            "--output",
            "-",
        ],
        cwd=tmp_path,
    )
    assert verify_result.returncode == 0, verify_result.stderr
    report = json.loads(verify_result.stdout)
    assert report["verdict"] == "accept"
