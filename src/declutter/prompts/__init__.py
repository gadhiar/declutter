"""Accessors for the prompts shipped inside this package.

Layer 2 -- the cleanup prompt a model runs under review -- lives at
`declutter/prompts/layer2.md`, packaged as data (see
`[tool.setuptools.package-data]` in pyproject.toml) so it is present in an
installed wheel, not only in a source checkout. Read it through
`importlib.resources`, not through a path built from `__file__`: that is
what keeps these accessors correct when declutter is installed from a
wheel whose on-disk layout does not match this source tree.
"""

from __future__ import annotations

import hashlib
from importlib import resources

LAYER2_FILENAME = "layer2.md"


def layer2_bytes() -> bytes:
    """The raw bytes of the layer 2 cleanup prompt, exactly as shipped."""
    return resources.files(__package__).joinpath(LAYER2_FILENAME).read_bytes()


def layer2_text() -> str:
    """The layer 2 cleanup prompt, decoded as UTF-8."""
    return layer2_bytes().decode("utf-8")


def layer2_sha256() -> str:
    """The hex sha256 digest of the layer 2 prompt's bytes, as shipped."""
    return hashlib.sha256(layer2_bytes()).hexdigest()
