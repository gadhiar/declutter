"""Regression tests for two defects found at integration review.

Both were cases where the tool's answer depended on how it was asked rather
than on what was in the tree, which is the one thing a deterministic checker
must never do.
"""

from __future__ import annotations

import json
import subprocess

# Built with chr() rather than written literally: a literal arrow here would be
# a real critical finding in this repository's own `check --all` run, and a
# pragma is for false positives, not for slop we would rather not act on.
ARROW_LINE = "Input " + chr(0x2192) + " output\n"


def _git(repo, *args):
    import os

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


def test_excluded_dirs_are_skipped_by_git_modes_too(git_repo, run_declutter):
    """A tracked generated tree must be excluded whatever the selection flag.

    git's --exclude-standard only filters the untracked arm, so a build/ or
    node_modules/ that is actually committed reaches --staged and
    --changed-since unless the directory policy is applied to them as well.
    Before the fix, --all called this tree clean and --changed-since failed it.
    """
    for directory in ("build", "node_modules"):
        generated = git_repo / directory / "generated.md"
        generated.parent.mkdir(parents=True)
        generated.write_text(ARROW_LINE, encoding="utf-8")
        _git(git_repo, "add", "-f", f"{directory}/generated.md")
    _git(git_repo, "commit", "-q", "-m", "commit generated trees")

    # Staged but deliberately not committed. Without this the index would equal
    # HEAD by the time --staged runs, `git diff --cached` would return nothing,
    # and the --staged assertions below would hold with the bug fully present.
    staged_only = git_repo / "build" / "staged.md"
    staged_only.write_text(ARROW_LINE, encoding="utf-8")
    _git(git_repo, "add", "-f", "build/staged.md")
    assert "build/staged.md" in _git(
        git_repo, "diff", "--name-only", "--cached", "--diff-filter=ACMR"
    ).stdout

    all_run = run_declutter(["check", "--all"], cwd=git_repo)
    changed_run = run_declutter(["check", "--changed-since", "main~1"], cwd=git_repo)
    staged_run = run_declutter(["check", "--staged"], cwd=git_repo)

    assert all_run.returncode == 0, all_run.stdout
    assert changed_run.returncode == 0, changed_run.stdout
    assert staged_run.returncode == 0, staged_run.stdout
    for result in (all_run, changed_run, staged_run):
        assert "build/generated.md" not in result.stdout
        assert "build/staged.md" not in result.stdout
        assert "node_modules/generated.md" not in result.stdout


def test_non_excluded_change_is_still_reported(git_repo, run_declutter):
    """The exclusion must not be so broad that it hides a real finding."""
    (git_repo / "real.md").write_text(ARROW_LINE, encoding="utf-8")
    _git(git_repo, "add", "real.md")
    _git(git_repo, "commit", "-q", "-m", "add a file with a critical finding")

    result = run_declutter(["check", "--changed-since", "main~1"], cwd=git_repo)

    assert result.returncode == 1
    assert "real.md" in result.stdout


def test_critical_only_does_not_falsify_the_summary_counts(git_repo, run_declutter):
    """--critical-only narrows reporting, so it must not rewrite the counts.

    summary.counts_by_severity is what the reusable workflow uploads as the
    machine-readable report. If filtering zeroed the warning count, a consumer
    reading that JSON would conclude the tree had no warnings at all.
    """
    # Deliberately mixes severities: a critical finding as well as warnings, so
    # that the "findings are narrowed to criticals" assertion below is checked
    # against a non-empty list rather than passing vacuously over an empty one.
    (git_repo / "prose.md").write_text(
        "An amazing seamless result\n" + ARROW_LINE, encoding="utf-8"
    )

    plain = run_declutter(["check", "--all", "--output", "-"], cwd=git_repo)
    filtered = run_declutter(
        ["check", "--all", "--critical-only", "--output", "-"], cwd=git_repo
    )

    plain_report = json.loads(plain.stdout)
    filtered_report = json.loads(filtered.stdout)
    plain_counts = plain_report["summary"]["counts_by_severity"]

    assert plain_counts["warning"] > 0
    assert plain_counts["critical"] > 0
    assert filtered_report["summary"]["counts_by_severity"] == plain_counts

    # The findings list, unlike the counts, really is narrowed.
    assert all(f["severity"] == "critical" for f in filtered_report["findings"])
    assert len(filtered_report["findings"]) < len(plain_report["findings"])
