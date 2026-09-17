"""Deterministic subprocess execution shared by the CLI differential and mutation runner.

Every subprocess the harness starts runs `sys.executable` (never a bare
`python`), under a fixed environment overlay so runs are reproducible, and
under a timeout that is always a recorded outcome rather than an exception
that aborts the run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .manifest import ScrubRule

# Applied on top of the ambient environment for every subprocess the harness
# starts, before any invocation- or test-command-specific overlay from the
# manifest. This is what makes two runs of the same command reproducible.
FIXED_ENV_OVERLAY: dict[str, str] = {
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "LC_ALL": "C",
    "TZ": "UTC",
}


@dataclass(frozen=True)
class RunResult:
    """The outcome of one subprocess run, already scrub-applied."""

    exit_code: int | None  # None only when timed_out is True
    stdout: bytes
    stderr: bytes
    timed_out: bool


def build_env(overlay: dict[str, str]) -> dict[str, str]:
    """The ambient environment, with the fixed overlay and `overlay` applied."""
    env = dict(os.environ)
    env.update(FIXED_ENV_OVERLAY)
    env.update(overlay)
    return env


def run(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env_overlay: dict[str, str],
    timeout: float,
    scrub_rules: tuple[ScrubRule, ...] = (),
) -> RunResult:
    """Run `[sys.executable, *argv]` in `cwd`, capture bytes, apply scrub rules.

    A timeout is caught and recorded as `timed_out=True` with whatever
    partial output the subprocess had produced; it never raises.
    """
    full_argv = [sys.executable, *argv]
    env = build_env(env_overlay)
    try:
        completed = subprocess.run(
            full_argv,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        return RunResult(
            exit_code=None,
            stdout=apply_scrub_rules(stdout, scrub_rules),
            stderr=apply_scrub_rules(stderr, scrub_rules),
            timed_out=True,
        )
    return RunResult(
        exit_code=completed.returncode,
        stdout=apply_scrub_rules(completed.stdout, scrub_rules),
        stderr=apply_scrub_rules(completed.stderr, scrub_rules),
        timed_out=False,
    )


def apply_scrub_rules(data: bytes, scrub_rules: tuple[ScrubRule, ...]) -> bytes:
    """Apply each declared scrub rule's regex substitution, in manifest order."""
    for rule in scrub_rules:
        pattern = re.compile(rule.pattern.encode("utf-8"))
        data = pattern.sub(rule.replacement.encode("utf-8"), data)
    return data
