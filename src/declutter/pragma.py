"""Inline exemptions: `declutter: allow=<names>`.

The pragma is matched as bare text, not as a comment in any particular
syntax, so it works inside `#`, `//`, `<!-- -->`, or any other comment
marker a checked file happens to use. A line may carry more than one
pragma, and each pragma may list more than one pattern name, comma
separated. There is no wildcard.

Unknown pattern names are not an error here: `allowed_names` returns every
name it parsed, whether or not that name is a real pattern. The caller
decides what to do with an unrecognised name (declutter.cli treats it as a
no-op exemption, so a typo silently fails to exempt anything -- a test can
still see the typo in the returned set).
"""

from __future__ import annotations

import re

_NAME = r"[A-Za-z0-9_]+"
_PRAGMA_RE = re.compile(
    r"declutter:\s*allow=(" + _NAME + r"(?:\s*,\s*" + _NAME + r")*)"
)


def allowed_names(line: str) -> frozenset[str]:
    """Return the set of pattern names exempted for `line`.

    Every `declutter: allow=...` occurrence in the line is parsed and the
    named pattern names are unioned. Names are returned exactly as written,
    including names that do not correspond to any known pattern.
    """
    names: set[str] = set()
    for match in _PRAGMA_RE.finditer(line):
        for raw in match.group(1).split(","):
            name = raw.strip()
            if name:
                names.add(name)
    return frozenset(names)
