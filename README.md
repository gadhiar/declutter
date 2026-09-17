# declutter

Deterministic checks that keep code and prose free of AI slop and needless clutter, plus a differential harness that makes model-driven cleanup safe to accept.

Status: bootstrap. The checker, harness, reusable workflow and cleanup prompt are being built.

## What it will provide

- A stdlib-only pattern catalogue and a `python -m declutter check` command, which checks named files, staged files, changes since a ref, or everything.
- An inline exception, `declutter: allow=<pattern>`, for lines where a symbol is intended.
- A reusable GitHub Actions workflow and a pre-commit hook definition, both pinned by commit.
- A harness that rejects a cleanup when it changes behaviour: CLI byte differential, public-interface snapshot, and mutation kill rate.
- A cleanup prompt for Python code that keeps rationale comments and runs the tests.

## Licence

MIT. See [LICENSE](LICENSE).
