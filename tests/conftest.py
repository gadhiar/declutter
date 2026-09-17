"""Shared test fixtures.

Tests invoke `python -m declutter` as a subprocess so that stdout/stderr
separation, exit codes and file-immutability can be verified the way a real
caller would see them, without importing declutter's own process state.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def run_declutter():
    def _run(args, cwd, env=None):
        full_env = dict(os.environ)
        full_env["PYTHONPATH"] = str(SRC)
        if env:
            full_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "declutter", *args],
            cwd=str(cwd),
            env=full_env,
            capture_output=True,
            text=True,
        )

    return _run


def _no_ambient_git_dir_env():
    """An environment with GIT_DIR/GIT_WORK_TREE stripped.

    The harness that runs this container sets both process-wide so that a
    bare `git` invocation targets the worktree's own repo. Any git command a
    test runs against a different, throwaway repo must not inherit that, or
    it ends up trying (and failing, read-only) to write into the harness's
    repo instead of the one under tmp_path.
    """
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway git repository in tmp_path, with a `main` branch and one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
            env=_no_ambient_git_dir_env(),
        )

    git("init", "-q")
    git("checkout", "-q", "-B", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (repo / "initial.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "initial.py")
    git("commit", "-q", "-m", "initial commit")

    return repo
