"""CLI byte differential: run declared invocations, compare exit code, stdout and stderr as bytes.

`run_invocations` captures one tree's behaviour, keyed by invocation id, in
the shape stored in a baseline artefact. `diff_invocation_results` compares
two such captures, one pair at a time; a mismatch on any field (exit code,
stdout, stderr, or timed-out status) is a byte differential rejection.
"""

from __future__ import annotations

from pathlib import Path

from .manifest import Invocation, Manifest
from .procrun import RunResult, run


def run_invocations(tree: Path, manifest: Manifest) -> dict[str, dict]:
    """Run every declared invocation against `tree`, return id -> result dict."""
    results: dict[str, dict] = {}
    for invocation in manifest.invocations:
        result = _run_one(tree, invocation, manifest.default_timeout, manifest.scrub_rules)
        results[invocation.id] = _result_to_dict(result)
    return results


def _run_one(tree: Path, invocation: Invocation, default_timeout: float, scrub_rules) -> RunResult:
    cwd = (tree / invocation.cwd).resolve()
    timeout = invocation.timeout if invocation.timeout is not None else default_timeout
    return run(
        invocation.argv,
        cwd=cwd,
        env_overlay=invocation.env_dict(),
        timeout=timeout,
        scrub_rules=scrub_rules,
    )


def _result_to_dict(result: RunResult) -> dict:
    return {
        "exit_code": result.exit_code,
        "stdout_hex": result.stdout.hex(),
        "stderr_hex": result.stderr.hex(),
        "timed_out": result.timed_out,
    }


def diff_invocation_results(baseline: dict[str, dict], candidate: dict[str, dict]) -> dict:
    """Compare two `run_invocations` outputs.

    Returns a dict keyed by invocation id, present in either side, each with
    `match: bool` and enough detail to see what differed. An id declared
    only on one side (a manifest changed between baseline and verify, which
    should not normally happen since the same manifest is meant to drive
    both) is reported as a mismatch rather than silently skipped.
    """
    ids = sorted(set(baseline) | set(candidate))
    diff: dict[str, dict] = {}
    for inv_id in ids:
        b = baseline.get(inv_id)
        c = candidate.get(inv_id)
        if b is None or c is None:
            diff[inv_id] = {
                "match": False,
                "detail": "invocation present in only one of baseline/candidate",
                "baseline": b,
                "candidate": c,
            }
            continue
        match = b == c
        diff[inv_id] = {
            "match": match,
            "baseline": b,
            "candidate": c,
        }
    return diff


def any_mismatch(diff: dict[str, dict]) -> bool:
    return any(not entry["match"] for entry in diff.values())
