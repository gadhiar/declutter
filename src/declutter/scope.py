"""Which lines of a selected file a run is allowed to judge.

Whole-file judgement makes the checker unusable at edit time and in CI on a
real repository: mist.ai carries 376 critical findings across 321 files, so
the first edit to any of them would be blocked for content the author never
wrote. Selection therefore carries a set of touched lines alongside each
path, and a finding that lands outside those lines is detected, counted as
out-of-scope, and dropped.

Everything in this module is pure. Hunk-header parsing takes diff *text*,
not a subprocess; `cli.py` owns the git calls and the wiring. That split is
what lets tests/test_scope.py run fast and git-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "ScopeError",
    "TouchedLines",
    "normalise_ranges",
    "parse_diff_touched_lines",
    "parse_lines_argument",
]


class ScopeError(ValueError):
    """A malformed --lines argument. cli.py turns this into exit code 2."""


# --------------------------------------------------------------------------
# range sets
# --------------------------------------------------------------------------


def normalise_ranges(ranges: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Sort, merge and return closed 1-based (start, end) ranges.

    Adjacent ranges are merged as well as overlapping ones: (1, 3) and (4, 5)
    become (1, 5). A reader only ever asks "is line N touched", so keeping
    them apart would carry no information and would make equality between two
    equivalent range sets depend on how they happened to be built.
    """
    ordered = sorted((int(start), int(end)) for start, end in ranges if end >= start)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1] + 1:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


@dataclass(frozen=True)
class TouchedLines:
    """The lines of one file a run may judge.

    Either a whole-file sentinel -- used for `--all`, `--files`, untracked
    files (every line in them is new) and `--whole-files` -- or an explicit
    set of merged, closed, 1-based ranges.
    """

    ranges: tuple[tuple[int, int], ...] = ()
    whole_file: bool = False

    @classmethod
    def whole(cls) -> "TouchedLines":
        return cls(ranges=(), whole_file=True)

    @classmethod
    def of(cls, ranges: Iterable[tuple[int, int]]) -> "TouchedLines":
        return cls(ranges=normalise_ranges(ranges), whole_file=False)

    def contains(self, lineno: int) -> bool:
        if self.whole_file:
            return True
        return any(start <= lineno <= end for start, end in self.ranges)

    def is_empty(self) -> bool:
        """True when this selects nothing at all.

        A file can reach selection with no touched lines -- a pure deletion
        hunk (`+l,0`) is the common case -- and the caller may then skip
        reading it entirely.
        """
        return not self.whole_file and not self.ranges

    def union(self, other: "TouchedLines") -> "TouchedLines":
        if self.whole_file or other.whole_file:
            return TouchedLines.whole()
        return TouchedLines.of(self.ranges + other.ranges)


def merge_touched(
    target: dict[str, TouchedLines], path: str, touched: TouchedLines
) -> None:
    """Union `touched` into `target[path]`, creating the entry if absent."""
    existing = target.get(path)
    target[path] = touched if existing is None else existing.union(touched)


# --------------------------------------------------------------------------
# unified diff parsing
# --------------------------------------------------------------------------

# Only the "+l,s" side matters: we judge the file as it exists on disk now, so
# the pre-image line numbers are meaningless to us.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_PLUS_FILE_RE = re.compile(r"^\+\+\+ (.*)$")


def parse_diff_touched_lines(diff_text: str) -> dict[str, TouchedLines]:
    """Map post-image path -> touched lines, from `git diff --unified=0` text.

    Call sites must pass `--unified=0 --find-renames` explicitly, never
    leaving rename detection to the user's git config. Three consequences
    fall out of reading only the post-image side, and all three are wanted:

    * `s == 0` is a pure deletion, so the hunk contributes no touched lines
      and a finding that lived on a deleted line is not reported.
    * a pure rename produces no hunks at all, so a renamed-but-unedited file
      is not treated as wholly touched.
    * a line moved without being edited reappears as an added line at its new
      position, so it counts as touched -- moving slop is authoring it again
      at that position, and the checker should say so.
    """
    touched: dict[str, TouchedLines] = {}
    current: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            match = _PLUS_FILE_RE.match(line)
            # "+++ /dev/null" is a deletion: the post-image does not exist, so
            # there is nothing on disk for us to judge.
            current = _strip_diff_prefix(match.group(1)) if match else None
            if current is not None:
                touched.setdefault(current, TouchedLines.of(()))
            continue
        if line.startswith("@@") and current is not None:
            match = _HUNK_RE.match(line)
            if match is None:
                continue
            start = int(match.group(1))
            # An omitted length means exactly one line, per the unified format.
            length = 1 if match.group(2) is None else int(match.group(2))
            if length == 0:
                continue
            merge_touched(touched, current, TouchedLines.of([(start, start + length - 1)]))

    return touched


def _strip_diff_prefix(raw: str) -> str | None:
    """Turn a `+++` header's operand into a repository-relative path."""
    path = raw.split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        # git quotes paths containing unusual bytes with C-style escapes.
        path = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
    if path.startswith("b/"):
        path = path[2:]
    return path


# --------------------------------------------------------------------------
# --lines arguments
# --------------------------------------------------------------------------


def parse_lines_argument(raw: str) -> tuple[str, tuple[int, int]]:
    """Parse one `--lines PATH:START-END` (or `PATH:N`) value.

    The split is on the *last* colon so that a Windows absolute path such as
    `C:\\work\\x.py:10-12` parses: the drive-letter colon is part of the path,
    and only the trailing one separates the range.

    Ranges are 1-based and inclusive. Anything malformed raises rather than
    quietly selecting nothing -- a silent empty selection would make the
    checker report a clean tree for a typo.
    """
    path, sep, spec = raw.rpartition(":")
    if not sep or not path:
        raise ScopeError(
            f"--lines needs PATH:START-END or PATH:N, got {raw!r}"
        )

    spec = spec.strip()
    if "-" in spec:
        start_text, _, end_text = spec.partition("-")
    else:
        start_text, end_text = spec, spec

    try:
        start = int(start_text)
        end = int(end_text)
    except ValueError:
        raise ScopeError(
            f"--lines range must be numeric (START-END or N), got {spec!r} in {raw!r}"
        ) from None

    if start < 1:
        raise ScopeError(f"--lines start must be 1 or greater, got {start} in {raw!r}")
    if end < start:
        raise ScopeError(
            f"--lines end must not be before start, got {start}-{end} in {raw!r}"
        )

    return path, (start, end)


def parse_lines_arguments(raw_values: Sequence[str]) -> dict[str, TouchedLines]:
    """Parse and union every `--lines` value, keyed by the path as written."""
    selected: dict[str, TouchedLines] = {}
    for raw in raw_values:
        path, span = parse_lines_argument(raw)
        merge_touched(selected, path, TouchedLines.of([span]))
    return selected
