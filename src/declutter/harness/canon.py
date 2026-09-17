"""Canonical JSON: the encoding every harness artefact and report is written in.

Two baseline runs over the same unchanged tree must produce byte-identical
artefacts. That is a property of *this* module, not of anything that calls
it: every structure passed here is dumped with sorted keys, a fixed indent
of two spaces, fixed ``(",", ": ")`` separators, and exactly one trailing
newline, and is always written as bytes (never through a text-mode file
object, which on Windows would translate ``\\n`` to ``\\r\\n`` and break the
byte-identical guarantee).

Nothing in an artefact may depend on wall-clock time, process id, absolute
path, host name, user name, or dict/set iteration order that is not itself
sorted before serialisation. Paths are recorded relative to the tree root
with forward slashes (see :func:`to_posix_relative`).
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath


def canonical_dumps(obj: object) -> str:
    """Render `obj` as canonical JSON text, including the trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def canonical_bytes(obj: object) -> bytes:
    """Render `obj` as the canonical JSON bytes written to every artefact."""
    return canonical_dumps(obj).encode("utf-8")


def write_canonical_json(path: Path, obj: object) -> None:
    """Write `obj` to `path` as canonical JSON, in binary mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(obj))


def to_posix_relative(path: Path, root: Path) -> str:
    """`path` made relative to `root` and rendered with forward slashes."""
    rel = path.resolve().relative_to(root.resolve())
    return PurePosixPath(rel.as_posix()).as_posix()
