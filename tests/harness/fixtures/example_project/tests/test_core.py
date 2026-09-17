"""Stdlib unittest coverage for pkg.core, used as the fixture's mutation test command."""

from __future__ import annotations

import unittest

from pkg.core import classify, clamp, is_even


class CoreTests(unittest.TestCase):
    def test_classify_positive(self) -> None:
        self.assertEqual(classify(5), "positive")

    def test_classify_negative(self) -> None:
        self.assertEqual(classify(-5), "negative")

    def test_classify_zero(self) -> None:
        self.assertEqual(classify(0), "zero")

    def test_is_even(self) -> None:
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(3))

    def test_clamp(self) -> None:
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(11, 0, 10), 10)


if __name__ == "__main__":
    unittest.main()
