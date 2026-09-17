"""Shared fixtures for declutter.harness tests.

Every mutation/CLI/interface test builds its own small synthetic project
under `tmp_path` rather than touching this repository, so the harness's own
test suite stays fast and hermetic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

CORE_SOURCE = '''"""A tiny module with a handful of branches, for harness tests."""

from __future__ import annotations


def classify(n: int) -> str:
    if n > 0:
        return "positive"
    elif n < 0:
        return "negative"
    else:
        return "zero"


def is_even(n: int) -> bool:
    return n % 2 == 0
'''

MAIN_SOURCE = '''"""A minimal CLI: prints the classification of one integer argument."""

from __future__ import annotations

import sys

from .core import classify


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    n = int(args[0]) if args else 0
    print(classify(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

TEST_SOURCE = '''"""Stdlib unittest coverage for pkg.core."""

from __future__ import annotations

import unittest

from pkg.core import classify, is_even


class CoreTests(unittest.TestCase):
    def test_classify_positive(self) -> None:
        self.assertEqual(classify(5), "positive")

    def test_classify_negative(self) -> None:
        self.assertEqual(classify(-5), "negative")

    def test_classify_zero(self) -> None:
        self.assertEqual(classify(0), "zero")

    def test_is_even(self) -> None:
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(3))


if __name__ == "__main__":
    unittest.main()
'''


def write_project(
    root: Path,
    *,
    core_source: str = CORE_SOURCE,
    main_source: str = MAIN_SOURCE,
    test_source: str = TEST_SOURCE,
) -> Path:
    """Write a minimal `pkg` + `tests` project under `root`, return `root`."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(core_source, encoding="utf-8")
    (pkg / "__main__.py").write_text(main_source, encoding="utf-8")

    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_core.py").write_text(test_source, encoding="utf-8")
    return root


def build_manifest_dict(*, max_mutants: int = 30, kill_rate_tolerance: float = 0.0) -> dict:
    return {
        "schema_version": 1,
        "default_timeout": 30.0,
        "invocations": [
            {"id": "classify_positive", "argv": ["-m", "pkg", "5"], "expected_exit_code": 0},
            {"id": "classify_negative", "argv": ["-m", "pkg", "-3"], "expected_exit_code": 0},
            {"id": "classify_zero", "argv": ["-m", "pkg", "0"], "expected_exit_code": 0},
        ],
        "interface_modules": ["pkg/core.py"],
        "mutation": {
            "target_modules": ["pkg/core.py"],
            "test_command": {"argv": ["-m", "unittest", "discover", "-s", "tests", "-t", "."]},
            "max_mutants": max_mutants,
            "kill_rate_tolerance": kill_rate_tolerance,
        },
        "scrub_rules": [],
    }


@pytest.fixture
def run_harness():
    def _run(args, cwd=None, env=None):
        full_env = dict(os.environ)
        full_env["PYTHONPATH"] = str(SRC)
        if env:
            full_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "declutter.harness", *args],
            cwd=str(cwd) if cwd is not None else None,
            env=full_env,
            capture_output=True,
        )

    return _run
