"""--staged and --changed-since, exercised against a throwaway git repo.

The repo lives entirely in tmp_path (via the git_repo fixture in
conftest.py) so these tests do not depend on this branch's own history.
"""

from __future__ import annotations

import json
import os
import subprocess


def _git(repo, *args):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True, env=env
    )


def test_staged_finds_a_staged_file(git_repo, run_declutter):
    planted = git_repo / "planted.py"
    planted.write_text("This is amazing.\n", encoding="utf-8")
    _git(git_repo, "add", "planted.py")

    result = run_declutter(["check", "--staged", "--output", "-"], git_repo)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert "planted.py" in paths


def test_staged_ignores_unstaged_file(git_repo, run_declutter):
    unstaged = git_repo / "unstaged.py"
    unstaged.write_text("This is amazing.\n", encoding="utf-8")

    result = run_declutter(["check", "--staged", "--output", "-"], git_repo)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert "unstaged.py" not in paths


def test_changed_since_finds_staged_addition(git_repo, run_declutter):
    planted = git_repo / "staged_planted.py"
    planted.write_text("This is amazing.\n", encoding="utf-8")
    _git(git_repo, "add", "staged_planted.py")

    result = run_declutter(["check", "--changed-since", "main", "--output", "-"], git_repo)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert "staged_planted.py" in paths


def test_changed_since_finds_untracked_addition(git_repo, run_declutter):
    # Committed on a side branch, then main stays put: from main's
    # perspective "main" itself has no diff, so this exercises the
    # ls-files --others half of the union instead by leaving the file
    # completely untracked.
    planted = git_repo / "untracked_planted.py"
    planted.write_text("This is amazing.\n", encoding="utf-8")

    result = run_declutter(["check", "--changed-since", "main", "--output", "-"], git_repo)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert "untracked_planted.py" in paths


def test_staged_without_git_is_usage_error(tmp_path, run_declutter):
    result = run_declutter(["check", "--staged", "--output", "-"], tmp_path)
    assert result.returncode == 2
    assert result.stderr.strip() != ""


def test_changed_since_without_git_is_usage_error(tmp_path, run_declutter):
    result = run_declutter(
        ["check", "--changed-since", "main", "--output", "-"], tmp_path
    )
    assert result.returncode == 2
    assert result.stderr.strip() != ""
