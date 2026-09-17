"""Parity between declutter.patterns and the pinned mist.ai fixture.

See tests/fixtures/mist_ai_6ca9f74_patterns.py for the fixture and its
provenance note.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from declutter import patterns as dp

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mist_ai_6ca9f74_patterns.py"


def _load_fixture():
    spec = importlib.util.spec_from_file_location(
        "mist_ai_6ca9f74_patterns", FIXTURE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses resolves string annotations via sys.modules[cls.__module__],
    # so the module must be registered there before its class bodies execute.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def test_fixture_imports_standalone():
    module = _load_fixture()
    assert module.PATTERNS


def test_same_names_in_same_order():
    fixture = _load_fixture()
    ours = [p.name for p in dp.PATTERNS]
    theirs = [p.name for p in fixture.PATTERNS]
    assert ours == theirs


def test_each_pattern_matches_fixture():
    fixture = _load_fixture()
    for ours, theirs in zip(dp.PATTERNS, fixture.PATTERNS):
        assert ours.name == theirs.name
        assert ours.pattern.pattern == theirs.pattern.pattern, ours.name
        assert ours.pattern.flags == theirs.pattern.flags, ours.name
        assert ours.severity == theirs.severity, ours.name
        assert ours.fixable == theirs.fixable, ours.name
        assert ours.replacement == theirs.replacement, ours.name
