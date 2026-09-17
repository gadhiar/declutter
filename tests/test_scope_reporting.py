"""The human-readable report must say which scope produced its counts.

A count without its scope is a claim a reader will misread: "critical=0"
under changed-lines means this change is clean, not that the file is. These
tests pin both halves of that -- the scope on the summary line, and the
count of findings the scope set aside.
"""

from __future__ import annotations

import json
import os
import subprocess

# Built with chr() rather than written literally, matching the convention in
# tests/test_selection_consistency.py: a literal arrow here would be a real
# critical finding in this repository's own check --all run.
ARROW = chr(0x2192)


def _git(repo, *args):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


def _plant_history_then_edit(repo):
    """A file whose slop predates the change, edited on a later line.

    Returns the 1-based line number that the edit touches.
    """
    target = repo / "history.py"
    target.write_text(
        f'BANNER = "in {ARROW} out"\nsecond = 2\nthird = 3\n', encoding="utf-8"
    )
    _git(repo, "add", "history.py")
    _git(repo, "commit", "-q", "-m", "add a file carrying a pre-existing critical")

    target.write_text(
        f'BANNER = "in {ARROW} out"\nsecond = 2\nthird = 33\n', encoding="utf-8"
    )
    _git(repo, "add", "history.py")
    _git(repo, "commit", "-q", "-m", "edit the third line only")
    return 3


def test_summary_names_the_scope_and_the_findings_it_set_aside(git_repo, run_declutter):
    _plant_history_then_edit(git_repo)

    result = run_declutter(["check", "--changed-since", "HEAD~1"], cwd=git_repo)

    assert result.returncode == 0, result.stdout
    assert "scope=changed-lines" in result.stdout
    assert "finding(s) outside the checked lines were not reported" in result.stdout
    # The pre-existing arrow is on line 1, which this change never touched.
    assert "history.py:1:" not in result.stdout


def test_sweep_over_the_same_change_reports_the_history(git_repo, run_declutter):
    """--whole-files is the sweep path: same files, every finding in them."""
    _plant_history_then_edit(git_repo)

    result = run_declutter(
        ["check", "--changed-since", "HEAD~1", "--whole-files"], cwd=git_repo
    )

    assert result.returncode == 1
    assert "scope=changed-files" in result.stdout
    assert "history.py:1:" in result.stdout
    # Nothing was set aside, so the caveat line must not appear and mislead.
    assert "were not reported" not in result.stdout


def test_out_of_scope_count_is_zero_when_nothing_was_set_aside(git_repo, run_declutter):
    (git_repo / "fresh.py").write_text(f'X = "a {ARROW} b"\n', encoding="utf-8")

    result = run_declutter(
        ["check", "--changed-since", "HEAD", "--output", "-"], cwd=git_repo
    )

    report = json.loads(result.stdout)
    assert report["schema_version"] == 2
    assert report["summary"]["scope"] == "changed-lines"
    assert report["summary"]["out_of_scope_findings"] == 0
    assert report["summary"]["counts_by_severity"]["critical"] == 1


def test_all_reports_scope_all(git_repo, run_declutter):
    _plant_history_then_edit(git_repo)

    result = run_declutter(["check", "--all"], cwd=git_repo)

    assert "scope=all" in result.stdout
