"""Acceptance test 3: a planted change is detected by each of the three detectors,
covered as three separate tests. Each test isolates its detector by leaving
the manifest sections for the other two detectors empty, so a failure
points at exactly one piece of machinery.
"""

from __future__ import annotations

from declutter.harness.manifest import parse_manifest
from declutter.harness.runner import capture, compare

from .conftest import write_project

EMPTY_MUTATION = {"target_modules": []}


def test_cli_output_text_change_is_caught_by_byte_differential(tmp_path) -> None:
    baseline_main = '''
import sys
from .core import classify

def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    print(classify(int(args[0])))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    candidate_main = baseline_main.replace(
        "print(classify(int(args[0])))", 'print("result: " + classify(int(args[0])))'
    )
    core = "def classify(n):\n    return 'positive' if n > 0 else 'other'\n"

    baseline_tree = write_project(tmp_path / "baseline", core_source=core, main_source=baseline_main)
    candidate_tree = write_project(tmp_path / "candidate", core_source=core, main_source=candidate_main)

    manifest = parse_manifest(
        {
            "schema_version": 1,
            "invocations": [{"id": "run", "argv": ["-m", "pkg", "5"]}],
            "interface_modules": [],
            "mutation": EMPTY_MUTATION,
            "scrub_rules": [],
        }
    )

    baseline_artefact = capture(baseline_tree, manifest)
    candidate_artefact = capture(candidate_tree, manifest)
    report = compare(baseline_artefact, candidate_artefact, manifest)

    assert report["cli_diff"]["run"]["match"] is False
    assert report["verdict"] == "reject"
    assert any("cli byte differential" in r for r in report["reasons"])


def test_removed_public_function_signature_is_caught_by_interface_snapshot(tmp_path) -> None:
    baseline_core = "def classify(n: int) -> str:\n    return 'x'\n"
    candidate_core = "def classify(n: int, loud: bool = False) -> str:\n    return 'x'\n"

    baseline_tree = write_project(tmp_path / "baseline", core_source=baseline_core)
    candidate_tree = write_project(tmp_path / "candidate", core_source=candidate_core)

    manifest = parse_manifest(
        {
            "schema_version": 1,
            "invocations": [],
            "interface_modules": ["pkg/core.py"],
            "mutation": EMPTY_MUTATION,
            "scrub_rules": [],
        }
    )

    baseline_artefact = capture(baseline_tree, manifest)
    candidate_artefact = capture(candidate_tree, manifest)
    report = compare(baseline_artefact, candidate_artefact, manifest)

    assert "function:classify" in report["interface_diff"]["pkg/core.py"]["changed"]
    assert report["verdict"] == "reject"
    assert any("interface" in r for r in report["reasons"])


def test_mutant_that_survives_only_in_candidate_is_caught_by_kill_rate_comparison(tmp_path) -> None:
    core = "def is_even(n: int) -> bool:\n    return n % 2 == 0\n"
    strong_test = '''
import unittest
from pkg.core import is_even

class T(unittest.TestCase):
    def test_true(self):
        self.assertTrue(is_even(4))

    def test_false(self):
        self.assertFalse(is_even(3))
'''
    weak_test = '''
import unittest
from pkg.core import is_even

class T(unittest.TestCase):
    def test_smoke(self):
        is_even(4)
'''

    baseline_tree = write_project(tmp_path / "baseline", core_source=core, test_source=strong_test)
    candidate_tree = write_project(tmp_path / "candidate", core_source=core, test_source=weak_test)

    manifest = parse_manifest(
        {
            "schema_version": 1,
            "invocations": [],
            "interface_modules": [],
            "mutation": {
                "target_modules": ["pkg/core.py"],
                "test_command": {"argv": ["-m", "unittest", "discover", "-s", "tests", "-t", "."]},
                "max_mutants": 20,
                "kill_rate_tolerance": 0.0,
            },
            "scrub_rules": [],
        }
    )

    baseline_artefact = capture(baseline_tree, manifest)
    candidate_artefact = capture(candidate_tree, manifest)
    report = compare(baseline_artefact, candidate_artefact, manifest)

    mdiff = report["mutation_diff"]
    assert "pkg/core.py::is_even" in mdiff["regressions"]
    entry = mdiff["common"]["pkg/core.py::is_even"]
    assert entry["candidate_rate"] < entry["baseline_rate"]
    assert report["verdict"] == "reject"
    assert any("kill-rate regression" in r for r in report["reasons"])
