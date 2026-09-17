from __future__ import annotations

from declutter import policy


def test_all_thirteen_extensions_checked():
    assert policy.CHECKED_EXTENSIONS == {
        "py",
        "md",
        "txt",
        "yaml",
        "yml",
        "json",
        "ts",
        "tsx",
        "js",
        "rs",
        "ps1",
        "sh",
        "dart",
    }


def test_is_checked_extension_case_insensitive():
    assert policy.is_checked_extension("foo.py")
    assert policy.is_checked_extension("foo.PY")
    assert policy.is_checked_extension("foo.Py")
    assert policy.is_checked_extension("foo.dart")


def test_is_checked_extension_rejects_others():
    assert not policy.is_checked_extension("foo.png")
    assert not policy.is_checked_extension("foo.lock")
    assert not policy.is_checked_extension("foo")


def test_default_excluded_dirs():
    for name in (
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "build",
        "dist",
    ):
        assert policy.is_excluded_dir(name), name


def test_egg_info_glob_excluded():
    assert policy.is_excluded_dir("declutter.egg-info")
    assert not policy.is_excluded_dir("src")


def test_blocks_only_critical():
    assert policy.blocks("critical") is True
    assert policy.blocks("warning") is False
    assert policy.blocks("info") is False
