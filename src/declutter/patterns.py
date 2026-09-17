"""The declutter pattern catalogue.

This mirrors the mist.ai slop-detector catalogue verbatim. See
tests/fixtures/mist_ai_6ca9f74_patterns.py for the parity fixture and its
provenance note. The regex bodies below are copied character for character
from upstream and must not be edited to "improve", tidy, deduplicate or
re-order them.

The `emoji_symbols` and `arrow_symbols` entries contain literal emoji and
arrow characters as required regex data. Those two lines carry a
`declutter: allow=...` pragma so this file passes its own check; see
pragma.py for the grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SeverityLevel = str  # one of "critical", "warning", "info"

SEVERITIES: dict[str, int] = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


@dataclass(frozen=True)
class Pattern:
    name: str
    pattern: "re.Pattern[str]"
    severity: SeverityLevel
    fixable: bool
    replacement: str = ""


PATTERNS: list[Pattern] = [
    # CRITICAL: Emojis (absolute no-no)
    Pattern(
        name="emoji",
        pattern=re.compile(r"[\U0001F300-\U0001F9FF\U0001FA70-\U0001FAFF\U00002600-\U000027BF]"),
        severity="critical",
        fixable=True,
        replacement="",
    ),
    # CRITICAL: Common emoji-like unicode symbols
    Pattern(
        name="emoji_symbols",
        pattern=re.compile(r"[✓✗✅❌🎯🔧🚀💡⚠️📝📊🏗️🌟💪🤔👍👎🔥💯🎉🎊]"),  # declutter: allow=emoji,emoji_symbols
        severity="critical",
        fixable=True,
        replacement="",
    ),
    # CRITICAL: Arrow symbols (use -> instead)
    Pattern(
        name="arrow_symbols",
        pattern=re.compile(r"[→←↔↑↓⇒⇐⇔⟹⟸⟺➜➝➞➟➠➡➢➣➤]"),  # declutter: allow=emoji,arrow_symbols
        severity="critical",
        fixable=True,
        replacement="->",
    ),
    Pattern(
        name="superlatives",
        pattern=re.compile(
            r"\b(amazing|awesome|fantastic|incredible|wonderful|"
            r"outstanding|remarkable|extraordinary|exceptional|"
            r"phenomenal|spectacular|fabulous|magnificent|marvelous)\b",
            re.IGNORECASE,
        ),
        severity="warning",
        fixable=False,
    ),
    Pattern(
        name="hype_words",
        pattern=re.compile(
            r"\b(seamless|cutting-edge|state-of-the-art|"
            r"world-class|enterprise-grade|battle-tested|"
            r"game-changing)\b",
            re.IGNORECASE,
        ),
        severity="warning",
        fixable=False,
    ),
    Pattern(
        name="filler_phrases",
        pattern=re.compile(
            r"(let'?s dive (?:in|into)|first and foremost|"
            r"it'?s worth noting that|at the end of the day|moving forward)",
            re.IGNORECASE,
        ),
        severity="info",
        fixable=False,
    ),
    Pattern(
        name="exclamation_spam",
        pattern=re.compile(r"!{3,}"),
        severity="info",
        fixable=True,
        replacement="!",
    ),
    Pattern(
        name="bold_consulting",
        pattern=re.compile(r"\*\*[^*\n]{2,}\*\*"),
        severity="warning",
        fixable=False,
    ),
]

_BY_NAME: dict[str, Pattern] = {p.name: p for p in PATTERNS}


def get_pattern(name: str) -> Pattern | None:
    """Return the Pattern registered under `name`, or None if unknown."""
    return _BY_NAME.get(name)
