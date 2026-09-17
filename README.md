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
python -m declutter check <selection> [--whole-files] [--critical-only] [--output FILE]
```

Exactly one selection mode is required. The modes fall into three scopes,
and the scope decides which findings are reported, not merely which files
are opened.

### Scope 1: changed lines

Only a finding that sits on a line the change touched is reported. A
pre-existing finding elsewhere in the same file is left alone. This is the
scope to use at edit time and on a pull request, because it measures new
work rather than history.

- `--staged` -- files staged in git, judged on the lines the staged change
  touched.
- `--changed-since REF` -- files changed since `REF`, judged on the lines
  that change touched. The file set is the union of
  `git diff --name-only --diff-filter=ACMR REF` and
  `git ls-files --others --exclude-standard`, so a file that is new and
  staged, and a file that is new and still untracked, are both found. An
  untracked file counts as touched in full, because every line in it is
  new.
- `--lines PATH:START-END` -- judge `PATH` on the given lines. Repeatable,
  and a caller that knows the file it just wrote but has no git range to
  quote should use this. Ranges are 1-based and inclusive. `PATH:N` names
  a single line. Repeating the flag for the same path adds its ranges
  together. The argument is split on its last colon, so an absolute
  Windows path such as `C:\src\app.py:10-12` parses correctly. An
  unparseable or backwards range is an error (exit code 2), never a
  silently empty selection.

`--staged` and `--changed-since` derive their line ranges from the diff
itself, via `git diff --unified=0 --find-renames`.

### Scope 2: changed files

Every finding in the selected file is reported, wherever it sits.

- `--files PATH [PATH ...]` -- check exactly these files. This is what the
  pre-commit hook uses, because pre-commit passes a file list and no range
  information.
- `--staged --whole-files` or `--changed-since REF --whole-files` --
  select files the git way, then judge them whole. This is the flag for a
  deliberate sweep over everything a branch has touched.

### Scope 3: everything

- `--all` -- check every file under the extension and directory exclusion
  policy. Inside a git repository the file list comes from
  `git ls-files --cached --others --exclude-standard`, so ignored files,
  build output and nested checkouts are skipped the same way git skips
  them; the directory exclusion policy below is applied on top of that
  list. Outside a repository, `--all` walks the current directory instead,
  and works exactly as it did before.

`--staged` and `--changed-since` require git. `--files`, `--lines` and
`--all` do not, and work with or without a repository present.

### What counts as a changed line

These follow from reading the added side of a `--unified=0` diff, and they
are worth stating outright because each one surprises somebody:

- A line that was moved without being edited counts as touched, and a
  finding on it is reported. Git records the move as an addition at the
  new position, and declutter does not second-guess that. Moving a block
  of old code therefore makes you responsible for the slop inside it.
- A deleted line is never reported. There is nothing left to fix.
- A file that was renamed without being edited reports nothing. Rename
  detection is requested explicitly, so a rename does not turn the whole
  file into touched lines.
- `--staged` reads the file as it exists on disk, not the staged blob,
  because that is the content you and your editor are looking at. When a
  file carries unstaged edits on top of staged ones, the two can disagree:
  the diff describes the index while the line numbers belong to the
  working tree, so a reported line may have shifted. Stage or discard the
  rest of the file if that matters to you.

`--critical-only` filters what is *reported*, not what blocks: only
critical findings ever make the exit code non-zero, with or without this
flag. Warning and info findings are always detected and always reported
unless you pass `--critical-only`, but they never fail a run on their own.

`--output FILE` writes the JSON report to `FILE`. `--output -` writes the
JSON report to stdout instead of the human-readable one, so stdout is pure
JSON and safe to pipe into `jq` or `json.load`. Without `--output`, a
human-readable report goes to stdout. Progress, status and any diagnostic
message always go to stderr, never stdout, regardless of `--output`.

### The JSON report

`schema_version` is `2`. Version 1 had no notion of scope, so every
finding it listed was a whole-file finding.

`summary.scope` records which of the three scopes the run used:
`changed-lines`, `changed-files` or `all`. `summary.out_of_scope_findings`
counts findings that were detected and then dropped because they sat
outside the touched lines, which is how you tell "this file is clean" from
"this file has history we chose not to look at".

`summary.counts_by_severity` counts in-scope findings only, and counts
them before `--critical-only` narrows the report. Those two rules together
mean the counts answer one question and answer it consistently: how much
slop did this scope find. A count is comparable with another run in the
same scope, and is not comparable across scopes.

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
`sh`, `dart`. Matching is case-insensitive.

Every selection mode additionally skips `.git`, `.venv`, `venv`,
`node_modules`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.tox`,
`build`, `dist`, and any `*.egg-info` directory. That policy is applied to
the git-derived modes as well as to `--all`, because git only filters
untracked files; a `build/` directory that is genuinely committed would
otherwise be skipped by one mode and reported by another.

Inside a repository, `--all` takes its file list from git, so anything
listed in `.gitignore` is skipped, and so is a nested checkout such as a
git worktree kept under `.claude/worktrees`. This is why an inventory run
no longer needs hand-filtering.

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

## Which scope a consumer should use

- An edit-time hook, which knows the file it just wrote and has no git
  range to quote: `--lines PATH:START-END`.
- CI on a pull request: `--changed-since` against the merge base with the
  target branch.
- CI on a push to the default branch: `--changed-since` against the
  commit's first parent (`HEAD^`). Do not use `--changed-since origin/main`
  here. On a push to `main`, `origin/main` already contains the commit
  under test, so the diff is empty and the check inspects nothing while
  reporting success. A green run that looked at no lines is worse than no
  run at all, because somebody trusts it.
- A pre-commit hook: `--files`, which is what the hook below already does.
- A retroactive sweep or an inventory: `--all`, or a git mode with
  `--whole-files` when you want the whole of only the files a branch
  touched.

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
