"""The pure half of line scoping: hunk headers, --lines arguments, range sets.

Every test here takes diff *text* rather than shelling out to git, which is
the point of keeping this logic in scope.py: the semantics that matter (a
zero-length post-image hunk is a pure deletion, a rename with no hunks is not
wholly touched) are checked in milliseconds and without a repository.
"""

from __future__ import annotations

import pytest

from declutter import scope
from declutter.scope import ScopeError, TouchedLines


# --------------------------------------------------------------------------
# range sets
# --------------------------------------------------------------------------


def test_normalise_ranges_sorts_merges_and_joins_adjacent():
    assert scope.normalise_ranges([(5, 6), (1, 2), (3, 4)]) == ((1, 6),)
    assert scope.normalise_ranges([(1, 4), (2, 3)]) == ((1, 4),)
    assert scope.normalise_ranges([(1, 2), (10, 11)]) == ((1, 2), (10, 11))


def test_touched_lines_contains_is_inclusive_at_both_ends():
    touched = TouchedLines.of([(10, 12)])
    assert not touched.contains(9)
    assert touched.contains(10)
    assert touched.contains(12)
    assert not touched.contains(13)


def test_whole_file_contains_everything_and_is_not_empty():
    whole = TouchedLines.whole()
    assert whole.contains(1)
    assert whole.contains(10_000)
    assert not whole.is_empty()


def test_empty_range_set_contains_nothing():
    empty = TouchedLines.of([])
    assert empty.is_empty()
    assert not empty.contains(1)


def test_union_with_whole_file_is_whole_file():
    assert TouchedLines.of([(1, 2)]).union(TouchedLines.whole()).whole_file
    assert TouchedLines.whole().union(TouchedLines.of([(1, 2)])).whole_file


# --------------------------------------------------------------------------
# hunk headers
# --------------------------------------------------------------------------


ADDED_DIFF = """diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -3,0 +4,2 @@ def f():
+    added one
+    added two
"""


def test_only_the_post_image_side_of_a_hunk_header_is_read():
    touched = scope.parse_diff_touched_lines(ADDED_DIFF)
    assert touched["a.py"].ranges == ((4, 5),)


def test_omitted_length_means_exactly_one_line():
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -7 +7 @@\n-old\n+new\n"
    )
    touched = scope.parse_diff_touched_lines(diff)
    assert touched["a.py"].ranges == ((7, 7),)


def test_zero_length_post_image_is_a_pure_deletion_and_touches_nothing():
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -4,2 +3,0 @@\n-gone\n-gone\n"
    )
    touched = scope.parse_diff_touched_lines(diff)
    assert touched["a.py"].is_empty()


def test_a_rename_with_no_hunks_is_not_wholly_touched():
    diff = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )
    touched = scope.parse_diff_touched_lines(diff)
    # No +++ header at all for a pure rename, so nothing is selected -- and
    # crucially the file is not recorded as whole-file touched.
    assert touched == {}


def test_a_deleted_file_is_not_selected():
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-one\n"
        "-two\n"
    )
    assert scope.parse_diff_touched_lines(diff) == {}


def test_several_hunks_in_one_file_are_unioned():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,0 +2,1 @@\n"
        "+x\n"
        "@@ -20,0 +22,3 @@\n"
        "+y\n+y\n+y\n"
    )
    touched = scope.parse_diff_touched_lines(diff)
    assert touched["a.py"].ranges == ((2, 2), (22, 24))


def test_several_files_are_kept_apart():
    diff = ADDED_DIFF + (
        "diff --git a/b.md b/b.md\n--- a/b.md\n+++ b/b.md\n@@ -0,0 +1,1 @@\n+hello\n"
    )
    touched = scope.parse_diff_touched_lines(diff)
    assert set(touched) == {"a.py", "b.md"}
    assert touched["b.md"].ranges == ((1, 1),)


def test_a_hunk_section_heading_containing_at_signs_does_not_confuse_the_parser():
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,0 +2,1 @@ def f():  # @@ not a header\n+x\n"
    )
    assert scope.parse_diff_touched_lines(diff)["a.py"].ranges == ((2, 2),)


# --------------------------------------------------------------------------
# --lines arguments
# --------------------------------------------------------------------------


def test_lines_argument_splits_on_the_last_colon_for_windows_paths():
    path, span = scope.parse_lines_argument(r"C:\work\x.py:10-12")
    assert path == r"C:\work\x.py"
    assert span == (10, 12)


def test_lines_argument_accepts_a_single_line():
    assert scope.parse_lines_argument("src/a.py:7") == ("src/a.py", (7, 7))


def test_repeated_lines_flags_for_one_path_are_unioned():
    selected = scope.parse_lines_arguments(["a.py:1-3", "a.py:10-11", "b.py:5"])
    assert selected["a.py"].ranges == ((1, 3), (10, 11))
    assert selected["b.py"].ranges == ((5, 5),)


@pytest.mark.parametrize(
    "raw",
    [
        "a.py",  # no colon at all
        "a.py:abc",  # non-numeric
        "a.py:5-x",  # non-numeric end
        "a.py:12-10",  # end before start
        "a.py:0-3",  # start below 1
        ":1-2",  # empty path
    ],
)
def test_malformed_lines_arguments_raise_rather_than_selecting_nothing(raw):
    with pytest.raises(ScopeError):
        scope.parse_lines_argument(raw)
