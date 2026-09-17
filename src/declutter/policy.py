"""Which files get checked, and what a finding's severity means for exit codes."""

from __future__ import annotations

import fnmatch
import os

# Extensions declutter checks, lower-case, without the leading dot.
CHECKED_EXTENSIONS: frozenset[str] = frozenset(
    {
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
)

# Directory names skipped outright while walking for --all.
DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
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
    }
)

# Directory name globs skipped while walking for --all (matched against the
# bare directory name, case-sensitive).
DEFAULT_EXCLUDED_DIR_GLOBS: frozenset[str] = frozenset({"*.egg-info"})


def is_checked_extension(path: str) -> bool:
    """True if `path`'s extension is one declutter checks (case-insensitive)."""
    _, ext = os.path.splitext(path)
    return ext.lstrip(".").lower() in CHECKED_EXTENSIONS


def is_excluded_dir(name: str) -> bool:
    """True if a directory named `name` should be pruned from an --all walk."""
    if name in DEFAULT_EXCLUDED_DIRS:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in DEFAULT_EXCLUDED_DIR_GLOBS)


def blocks(severity: str) -> bool:
    """True only for the severity level that makes `check` exit non-zero."""
    return severity == "critical"
