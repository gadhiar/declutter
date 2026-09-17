"""Parity fixture: the mist.ai slop pattern catalogue.

Source repository: mist.ai
Source path: backend/chat/slop_detector.py
Pinned commit: 6ca9f74

Provenance note: this content was captured from the mist.ai working tree. The
agents on this goal are confined to the declutter worktree and were refused
every git invocation against mist.ai, so these bytes are NOT verified equal to
the blob at commit 6ca9f74. Confirm with
`git -C <mist.ai> diff 6ca9f74 -- backend/chat/slop_detector.py`.

That diff is expected to be non-empty in exactly one respect: the two
`declutter: allow=...` pragma comments below, which cannot appear in a mist.ai
blob written before declutter existed, and which this repository needs in order
to pass its own checker. Ignore those two comments when comparing. If anything
else differs, the regex bodies here are wrong and this file should be corrected
to match the blob -- do not remove the pragmas, which would reintroduce 73
critical findings in this repository's own `check --all` run.

What the parity test does and does not establish: it proves that
`declutter.patterns` has not drifted from this local snapshot. It proves nothing
about mist.ai, because the snapshot itself is unverified against that commit.

Do not edit the regex bodies to improve them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SeverityLevel = Literal["critical", "warning", "info"]

_SEVERITY_ORDER: dict[SeverityLevel, int] = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}


@dataclass(frozen=True)
class SlopPattern:
    name: str
    pattern: "re.Pattern[str]"
    severity: SeverityLevel
    fixable: bool
    replacement: str = ""


@dataclass(frozen=True)
class SlopFinding:
    pattern_name: str
    severity: SeverityLevel
    line: int
    column: int
    matched_text: str


PATTERNS = [
    # CRITICAL: Emojis (absolute no-no)
    SlopPattern(
        name="emoji",
        pattern=re.compile(r"[\U0001F300-\U0001F9FF\U0001FA70-\U0001FAFF\U00002600-\U000027BF]"),
        severity="critical",
        fixable=True,
        replacement="",
    ),
    # CRITICAL: Common emoji-like unicode symbols
    SlopPattern(
        name="emoji_symbols",
        pattern=re.compile(r"[✓✗✅❌🎯🔧🚀💡⚠️📝📊🏗️🌟💪🤔👍👎🔥💯🎉🎊]"),  # declutter: allow=emoji,emoji_symbols
        severity="critical",
        fixable=True,
        replacement="",
    ),
    # CRITICAL: Arrow symbols (use -> instead)
    SlopPattern(
        name="arrow_symbols",
        pattern=re.compile(r"[→←↔↑↓⇒⇐⇔⟹⟸⟺➜➝➞➟➠➡➢➣➤]"),  # declutter: allow=emoji,arrow_symbols
        severity="critical",
        fixable=True,
        replacement="->",
    ),
    SlopPattern(
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
    SlopPattern(
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
    SlopPattern(
        name="filler_phrases",
        pattern=re.compile(
            r"(let'?s dive (?:in|into)|first and foremost|"
            r"it'?s worth noting that|at the end of the day|moving forward)",
            re.IGNORECASE,
        ),
        severity="info",
        fixable=False,
    ),
    SlopPattern(
        name="exclamation_spam",
        pattern=re.compile(r"!{3,}"),
        severity="info",
        fixable=True,
        replacement="!",
    ),
    SlopPattern(
        name="bold_consulting",
        pattern=re.compile(r"\*\*[^*\n]{2,}\*\*"),
        severity="warning",
        fixable=False,
    ),
]
