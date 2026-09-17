"""End-to-end line scoping: what a real git change makes declutter judge.

These tests exist because whole-file judgement blocked edits for content the
author never wrote. Each one plants a finding somewhere and asserts on
whether the author's change actually reached it.
"""

from __future__ import annotations

import json
import os
import subprocess

# Built with chr() rather than written literally, for the same reason as in
# tests/test_selection_consistency.py: a literal arrow here would be a real
# critical finding in this repository's own `check --all` run.
ARROW = chr(0x2192)
SLOP = "Input " + ARROW + " output"


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


def _write(path, lines):
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def _report(result):
    return json.loads(result.stdout)


def _paths(report):
    return {finding["path"] for finding in report["findings"]}


def _commit(repo, name, lines, message="plant"):
    _write(repo / name, lines)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


# --------------------------------------------------------------------------
# the core promise: only what the author touched
# --------------------------------------------------------------------------


def test_preexisting_critical_outside_the_change_is_not_reported(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])
    _write(git_repo / "doc.md", ["ONE", "two", SLOP, "four", "five"])

    result = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    report = _report(result)

    assert report["findings"] == []
    assert result.returncode == 0
    assert report["summary"]["scope"] == "changed-lines"
    # Detected and deliberately dropped, not invisible.
    assert report["summary"]["out_of_scope_findings"] >= 1
    assert report["summary"]["counts_by_severity"]["critical"] == 0


def test_the_same_critical_on_a_changed_line_is_reported(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", "three", "four", "five"])
    _write(git_repo / "doc.md", ["one", "two", SLOP, "four", "five"])

    result = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 1
    assert [(f["path"], f["line"]) for f in report["findings"]] == [("doc.md", 3)]
    assert report["summary"]["out_of_scope_findings"] == 0


def test_a_line_moved_without_being_edited_counts_as_touched(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])
    # Same bytes, new position: git records an addition at line 1 and a
    # deletion at line 3, so the author is authoring that line again there.
    _write(git_repo / "doc.md", [SLOP, "one", "two", "four", "five"])

    result = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 1
    assert [(f["path"], f["line"]) for f in report["findings"]] == [("doc.md", 1)]


def test_a_deleted_line_carrying_a_finding_is_not_reported(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", SLOP, "three", SLOP, "five"])
    # Delete the line 2 copy only. The line 4 copy survives, untouched, which
    # is what stops this test passing merely because the slop left the file.
    _write(git_repo / "doc.md", ["one", "three", SLOP, "five"])

    result = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 0
    assert report["findings"] == []
    # A pure deletion hunk selects no lines, so the file is never even read.
    assert report["summary"]["files_checked"] == 0


def test_a_pure_rename_reports_nothing_and_is_not_wholly_touched(git_repo, run_declutter):
    # Rename detection is switched off in this repository's config on purpose,
    # so that the test pins declutter's explicit --find-renames rather than
    # git's default. Without this line the test passes either way, because
    # diff.renames defaults to true, and it would not notice the flag being
    # dropped -- which is exactly what a mutation run found.
    _git(git_repo, "config", "diff.renames", "false")
    _commit(git_repo, "old.md", ["one", SLOP, "three"])
    _git(git_repo, "mv", "old.md", "new.md")

    result = run_declutter(["check", "--staged", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 0
    assert report["findings"] == []
    assert "new.md" not in _paths(report)
    # Wholly touched would have meant one checked file and one critical.
    assert report["summary"]["files_checked"] == 0
    assert report["summary"]["out_of_scope_findings"] == 0


# --------------------------------------------------------------------------
# the sweep path
# --------------------------------------------------------------------------


def test_whole_files_on_a_git_mode_reports_the_untouched_finding(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])
    _write(git_repo / "doc.md", ["ONE", "two", SLOP, "four", "five"])

    scoped = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    swept = run_declutter(
        ["check", "--changed-since", "HEAD", "--whole-files", "--output", "-"], git_repo
    )

    assert _report(scoped)["findings"] == []
    swept_report = _report(swept)
    assert swept.returncode == 1
    assert [(f["path"], f["line"]) for f in swept_report["findings"]] == [("doc.md", 3)]
    assert swept_report["summary"]["scope"] == "changed-files"
    assert swept_report["summary"]["out_of_scope_findings"] == 0


def test_whole_files_works_on_staged_too(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])
    _write(git_repo / "doc.md", ["ONE", "two", SLOP, "four", "five"])
    _git(git_repo, "add", "doc.md")

    result = run_declutter(["check", "--staged", "--whole-files", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 1
    assert [(f["path"], f["line"]) for f in report["findings"]] == [("doc.md", 3)]
    assert report["summary"]["scope"] == "changed-files"


def test_all_still_reports_everything_in_the_file(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])
    _write(git_repo / "doc.md", ["ONE", "two", SLOP, "four", "five"])

    result = run_declutter(["check", "--all", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 1
    assert ("doc.md", 3) in [(f["path"], f["line"]) for f in report["findings"]]
    assert report["summary"]["scope"] == "all"
    assert report["summary"]["out_of_scope_findings"] == 0


def test_files_mode_is_whole_file_and_scoped_as_changed_files(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])

    result = run_declutter(["check", "--files", "doc.md", "--output", "-"], git_repo)
    report = _report(result)

    assert result.returncode == 1
    assert report["summary"]["scope"] == "changed-files"


def test_whole_files_is_accepted_and_redundant_with_files_and_all(git_repo, run_declutter):
    """--whole-files cannot change a mode that was already whole-file.

    Accepting it silently is the chosen behaviour: a sweep script that passes
    the flag unconditionally should not have to special-case --all.
    """
    _commit(git_repo, "doc.md", ["one", "two", SLOP, "four", "five"])

    with_files = run_declutter(
        ["check", "--files", "doc.md", "--whole-files", "--output", "-"], git_repo
    )
    with_all = run_declutter(["check", "--all", "--whole-files", "--output", "-"], git_repo)

    assert _report(with_files)["summary"]["scope"] == "changed-files"
    assert _report(with_all)["summary"]["scope"] == "all"
    assert with_files.returncode == with_all.returncode == 1


# --------------------------------------------------------------------------
# --lines
# --------------------------------------------------------------------------


def test_lines_agrees_finding_for_finding_with_the_git_derived_run(git_repo, run_declutter):
    """The two scopes must be the same mechanism, not two approximations.

    The ranges below are the ones this change produces: editing line 2 gives
    `@@ -2 +2 @@`, and appending two lines gives `@@ -6,0 +7,2 @@`. They are
    written out rather than derived from the diff so that a regression in the
    hunk parser cannot make both sides wrong in the same way.
    """
    _commit(git_repo, "doc.md", ["one", "two", "three", "four", SLOP, "six"])
    _write(
        git_repo / "doc.md",
        ["one", SLOP, "three", "four", SLOP, "six", SLOP, "eight"],
    )

    from_git = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    from_lines = run_declutter(
        ["check", "--lines", "doc.md:2", "--lines", "doc.md:7-8", "--output", "-"],
        git_repo,
    )

    git_report = _report(from_git)
    lines_report = _report(from_lines)

    assert git_report["findings"] == lines_report["findings"]
    # Non-empty, and the line 5 copy is excluded by both.
    assert [f["line"] for f in git_report["findings"]] == [2, 7]
    assert git_report["summary"]["scope"] == lines_report["summary"]["scope"] == "changed-lines"
    assert git_report["summary"]["out_of_scope_findings"] == 1
    assert lines_report["summary"]["out_of_scope_findings"] == 1


def test_lines_accepts_a_single_line_and_unions_repeats(git_repo, run_declutter):
    _commit(git_repo, "doc.md", [SLOP, "two", SLOP, "four", SLOP])

    single = run_declutter(["check", "--lines", "doc.md:3", "--output", "-"], git_repo)
    unioned = run_declutter(
        ["check", "--lines", "doc.md:3", "--lines", "doc.md:5", "--output", "-"], git_repo
    )

    assert [f["line"] for f in _report(single)["findings"]] == [3]
    assert [f["line"] for f in _report(unioned)["findings"]] == [3, 5]


def test_lines_with_a_windows_style_absolute_path(tmp_path, run_declutter):
    """The last-colon split is what makes a drive-lettered path work.

    The path is built from tmp_path so the test runs on POSIX too; what is
    being exercised is that a colon inside the path does not steal the range.
    """
    doc = tmp_path / "doc.md"
    _write(doc, [SLOP, "two", SLOP])

    result = run_declutter(["check", "--lines", f"{doc}:3", "--output", "-"], tmp_path)
    report = _report(result)

    assert result.returncode == 1
    assert [f["line"] for f in report["findings"]] == [3]


def test_lines_with_a_literal_drive_letter_path_parses_before_it_is_opened(
    tmp_path, run_declutter
):
    """A `C:\\...` argument must fail on the missing file, not on parsing."""
    result = run_declutter(
        ["check", "--lines", r"C:\work\x.py:10-12", "--output", "-"], tmp_path
    )
    assert result.returncode == 2
    assert "no such file" in result.stderr
    assert r"C:\work\x.py" in result.stderr


LINES_USAGE_ERRORS = [
    "doc.md",
    "doc.md:abc",
    "doc.md:5-x",
    "doc.md:12-10",
    "doc.md:0-3",
]


def test_each_malformed_lines_argument_exits_two_with_a_message(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two"])
    for raw in LINES_USAGE_ERRORS:
        result = run_declutter(["check", "--lines", raw, "--output", "-"], git_repo)
        assert result.returncode == 2, raw
        assert result.stderr.strip() != "", raw
        assert result.stdout == "", raw


def test_lines_and_whole_files_contradict_each_other(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two"])
    result = run_declutter(
        ["check", "--lines", "doc.md:1", "--whole-files", "--output", "-"], git_repo
    )
    assert result.returncode == 2
    assert "--whole-files" in result.stderr


def test_lines_is_mutually_exclusive_with_the_other_selection_flags(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two"])
    result = run_declutter(["check", "--lines", "doc.md:1", "--all"], git_repo)
    assert result.returncode == 2


# --------------------------------------------------------------------------
# --all and git's exclusions
# --------------------------------------------------------------------------


def test_all_skips_a_nested_git_checkout(git_repo, run_declutter):
    """A nested checkout is what a worktree under .claude/worktrees looks like.

    An inventory run that walked into one would count the same repository's
    findings several times over, which is exactly what happened before --all
    started asking git what is in the tree.
    """
    nested = git_repo / "nested"
    nested.mkdir()
    _git(nested, "init", "-q")
    _write(nested / "slop.md", [SLOP])

    result = run_declutter(["check", "--all", "--output", "-"], git_repo)
    report = _report(result)

    assert not any(p.startswith("nested/") for p in _paths(report)), _paths(report)
    assert result.returncode == 0


def test_all_outside_a_repository_still_walks_the_tree(tmp_path, run_declutter):
    """The os.walk fallback: --all must keep working with no git at all."""
    _write(tmp_path / "doc.md", ["one", SLOP])

    result = run_declutter(["check", "--all", "--output", "-"], tmp_path)
    report = _report(result)

    assert result.returncode == 1
    assert _paths(report) == {"doc.md"}
    assert report["summary"]["scope"] == "all"


def test_all_respects_gitignore(git_repo, run_declutter):
    (git_repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    ignored = git_repo / "ignored"
    ignored.mkdir()
    _write(ignored / "slop.md", [SLOP])

    result = run_declutter(["check", "--all", "--output", "-"], git_repo)

    assert result.returncode == 0
    assert _paths(_report(result)) == set()


# --------------------------------------------------------------------------
# report shape
# --------------------------------------------------------------------------


def test_output_dash_is_pure_json_under_every_selection_mode(git_repo, run_declutter):
    _commit(git_repo, "doc.md", ["one", "two", SLOP])
    _write(git_repo / "doc.md", ["ONE", "two", SLOP])
    _git(git_repo, "add", "doc.md")

    invocations = [
        (["--files", "doc.md"], "changed-files"),
        (["--lines", "doc.md:1"], "changed-lines"),
        (["--staged"], "changed-lines"),
        (["--staged", "--whole-files"], "changed-files"),
        (["--changed-since", "HEAD"], "changed-lines"),
        (["--changed-since", "HEAD", "--whole-files"], "changed-files"),
        (["--all"], "all"),
    ]
    for flags, expected_scope in invocations:
        result = run_declutter(["check", *flags, "--output", "-"], git_repo)
        report = json.loads(result.stdout)  # raises if stdout is not pure JSON
        assert "declutter:" not in result.stdout, flags
        assert report["schema_version"] == 2, flags
        assert report["summary"]["scope"] == expected_scope, flags
        assert isinstance(report["summary"]["out_of_scope_findings"], int), flags


def test_counts_by_severity_counts_in_scope_findings_only(git_repo, run_declutter):
    """The soak compares these counts across repositories.

    A count that mixed scoped and unscoped findings would be worthless, so it
    is narrowed by scope -- and still taken before --critical-only filters.
    """
    _commit(git_repo, "doc.md", ["An amazing seamless result", "two", SLOP])
    # The edited line carries a warning of its own, so the counts below are
    # non-zero. With an all-zero count the --critical-only comparison would
    # hold whatever the code did, and would prove nothing.
    _write(git_repo / "doc.md", ["An amazing seamless result", "A fantastic two", SLOP])

    plain = run_declutter(["check", "--changed-since", "HEAD", "--output", "-"], git_repo)
    filtered = run_declutter(
        ["check", "--changed-since", "HEAD", "--critical-only", "--output", "-"], git_repo
    )

    plain_counts = _report(plain)["summary"]["counts_by_severity"]
    # In scope: the warning on the edited line, and nothing else. The critical
    # on line 3 and the warnings on line 1 are history, and are set aside.
    assert plain_counts == {"critical": 0, "warning": 1, "info": 0}
    assert _report(plain)["summary"]["out_of_scope_findings"] >= 2
    # Still taken before --critical-only narrows the report, so the warning
    # survives in the counts even though it is absent from the findings.
    assert _report(filtered)["summary"]["counts_by_severity"] == plain_counts
    assert _report(filtered)["findings"] == []
