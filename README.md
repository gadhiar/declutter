# declutter

A deterministic, stdlib-only checker that keeps code and prose free of AI
slop and needless clutter: emoji, arrow-symbol soup, hype words, and a
handful of other patterns pinned from mist.ai's own slop detector. Pin this
repository by commit; there is no released version to track instead.

## Install

```
pip install --no-deps -e /path/to/declutter
```

or, from a consumer's own environment, add `src/` to `PYTHONPATH` if you do
not want to install it at all. declutter has no runtime dependencies.

## Usage

```
python -m declutter check <selection> [--critical-only] [--output FILE]
```

Exactly one selection mode is required:

- `--files PATH [PATH ...]` -- check exactly these files.
- `--staged` -- check files staged in git
  (`git diff --name-only --cached --diff-filter=ACMR`).
- `--changed-since REF` -- check files changed since `REF`. This is the
  union of `git diff --name-only --diff-filter=ACMR REF` and
  `git ls-files --others --exclude-standard`, so a file that is new and
  staged, and a file that is new and still untracked, are both found.
  `--staged` and `--changed-since` require git; `--files` and `--all` do
  not, and work the same with or without a repository present.
- `--all` -- check every file under the extension and directory exclusion
  policy, walked from the git top level when one is available, otherwise
  from the current directory.

`--critical-only` filters what is *reported*, not what blocks: only
critical findings ever make the exit code non-zero, with or without this
flag. Warning and info findings are always detected and always reported
unless you pass `--critical-only`, but they never fail a run on their own.

`--output FILE` writes the JSON report to `FILE`. `--output -` writes the
JSON report to stdout instead of the human-readable one, so stdout is pure
JSON and safe to pipe into `jq` or `json.load`. Without `--output`, a
human-readable report goes to stdout. Progress, status and any diagnostic
message always go to stderr, never stdout, regardless of `--output`.

### Exit codes

- `0` -- no critical finding survived pragma filtering.
- `1` -- at least one critical finding survived pragma filtering.
- `2` -- a usage or I/O error (bad arguments, a missing explicit file, git
  required but unavailable, a report that could not be written).

### There is no `--fix`

declutter only reports. It never rewrites a file, and it never will as
part of this package -- fixing slop is a model's job, done under review,
not a regex substitution run unattended over your working tree. The
pattern catalogue does carry `fixable` and `replacement` fields for parity
with the upstream mist.ai catalogue and for a future consumer that wants
them, but this package does not act on them.

## Checked extensions

`py`, `md`, `txt`, `yaml`, `yml`, `json`, `ts`, `tsx`, `js`, `rs`, `ps1`,
`sh`, `dart`. Matching is case-insensitive. `--all` additionally skips
`.git`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.mypy_cache`,
`.pytest_cache`, `.tox`, `build`, `dist`, and any `*.egg-info` directory.

## Inline exceptions

Add `declutter: allow=<name>[,<name>...]` anywhere on a line -- in whatever
comment syntax the file already uses -- to exempt that line from the named
pattern(s) only. There is no wildcard, and the pragma only covers the line
it appears on.

```python
arrow = "->"  # this uses -> already, not a literal arrow glyph
count = "!!!"  # declutter: allow=exclamation_spam
```

An unrecognised pattern name in a pragma is not an error; it simply
exempts nothing, so a typo silently fails to protect the line it was meant
to cover. Double-check the pattern name against `src/declutter/patterns.py`
if a pragma does not seem to be taking effect.

## Using the pre-commit hook

Pin this repository by commit in the consumer's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://example.invalid/declutter
    rev: <full commit SHA>
    hooks:
      - id: declutter-check
```

The hook runs `declutter check --critical-only --files` against whatever
files pre-commit passes it, filtered to the checked extensions above, and
only blocks the commit on a critical finding.

## Licence

MIT. See [LICENSE](LICENSE).
