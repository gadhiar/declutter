"""Errors the harness CLI turns into exit code 2 (usage or I/O error)."""

from __future__ import annotations


class HarnessError(Exception):
    """A usage, manifest or I/O error: the CLI maps this to exit code 2.

    Never raised for a behavioural difference between baseline and
    candidate -- that is a rejection (exit code 1), reported in the
    comparison report, not an exception.
    """
