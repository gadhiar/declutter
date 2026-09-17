"""`python -m declutter.prompts`: print the layer 2 prompt's sha256 hash.

This is the printable-hash requirement for the layer 2 cleanup prompt: a
reviewer, a pinned test, or a caller wiring layer 2 into a harness can get
the hash of the prompt actually shipped in this installation without
reading the file by hand.
"""

from __future__ import annotations

import sys

from . import layer2_sha256


def main() -> int:
    print(layer2_sha256())
    return 0


if __name__ == "__main__":
    sys.exit(main())
