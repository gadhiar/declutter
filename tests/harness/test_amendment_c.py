"""Acceptance test 4 (Amendment C): a candidate that deletes a whole function
is reported under `removed_or_merged` and exits 0 on that account.

This isolates the mutation detector: the manifest declares no interface
modules and no CLI invocations, so the only thing that could reject here is
a kill-rate regression, and there is none -- the function is simply gone,
which is informational only. The exit code is asserted directly, not just
the report text, per the acceptance criterion.
"""

from __future__ import annotations

import json

from declutter.harness.cli import main
from declutter.harness.manifest import parse_manifest
from declutter.harness.runner import record

from .conftest import write_project

BASELINE_CORE = '''
def foo(n: int) -> bool:
    return n > 0


def bar(n: int) -> bool:
    return n < 0
'''

BASELINE_TEST = '''
import unittest
from pkg.core import foo, bar

class T(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(foo(1))
        self.assertFalse(foo(-1))

    def test_bar(self):
        self.assertTrue(bar(-1))
        self.assertFalse(bar(1))
'''

CANDIDATE_CORE = '''
def foo(n: int) -> bool:
    return n > 0
'''

CANDIDATE_TEST = '''
import unittest
from pkg.core import foo

class T(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(foo(1))
        self.assertFalse(foo(-1))
'''

MANIFEST_DICT = {
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


def test_deleted_function_is_informational_and_exits_zero(tmp_path, capsys) -> None:
    baseline_tree = write_project(tmp_path / "baseline", core_source=BASELINE_CORE, test_source=BASELINE_TEST)
    candidate_tree = write_project(tmp_path / "candidate", core_source=CANDIDATE_CORE, test_source=CANDIDATE_TEST)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST_DICT), encoding="utf-8")

    manifest = parse_manifest(MANIFEST_DICT)
    baseline_dir = tmp_path / "baseline_out"
    record(baseline_tree, manifest, baseline_dir)

    exit_code = main(
        [
            "verify",
            "--tree",
            str(candidate_tree),
            "--manifest",
            str(manifest_path),
            "--baseline",
            str(baseline_dir),
            "--output",
            "-",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert "pkg/core.py::bar" in report["mutation_diff"]["removed_or_merged"]
    assert report["mutation_diff"]["regressions"] == []
    assert report["verdict"] == "accept"
    assert exit_code == 0
