"""A minimal CLI for the fixture package: prints the classification of one integer argument."""

from __future__ import annotations

import sys

from .core import classify


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    n = int(args[0]) if args else 0
    print(classify(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
