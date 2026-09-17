"""declutter.harness: proof that a model-driven cleanup did not change behaviour.

This subpackage is the differential-testing layer for the declutter project.
It compares a baseline tree against a candidate tree along three axes:

1. A byte-exact CLI differential, driven by a per-repository manifest
   (see :mod:`declutter.harness.manifest` for the manifest schema).
2. A public-interface snapshot of declared modules, taken by parsing source
   with ``ast`` rather than importing it (see
   :mod:`declutter.harness.interface`).
3. A deterministic mutation-testing run over declared target modules, with
   kill rate compared per qualified function name (see
   :mod:`declutter.harness.mutation`).

Everything in this package is stdlib-only. Every artefact it writes is
byte-identical between two runs over the same unchanged tree: no wall-clock
timestamps, no durations, no absolute paths, no process ids, no iteration
order that depends on hashing. See :mod:`declutter.harness.canon` for the
canonical JSON writer that enforces this.

Use ``python -m declutter.harness --help`` for the command line interface.
"""

from __future__ import annotations

__all__: list[str] = []
