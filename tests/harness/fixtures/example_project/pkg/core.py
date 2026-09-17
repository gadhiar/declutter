"""A tiny module with a handful of branches, for the fixture manifest's mutation demo."""

from __future__ import annotations


def classify(n: int) -> str:
    if n > 0:
        return "positive"
    elif n < 0:
        return "negative"
    else:
        return "zero"


def is_even(n: int) -> bool:
    return n % 2 == 0


def clamp(n: int, low: int, high: int) -> int:
    if n < low:
        return low
    if n > high:
        return high
    return n
