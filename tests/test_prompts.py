"""Tests for the layer 2 cleanup prompt and its accessor.

These tests check the prompt the way its actual consumers will reach it:
through `declutter.prompts`, not by building a path from `__file__` in the
test itself. That is the same route `importlib.resources` takes inside an
installed wheel, where the source tree layout this repository has does not
necessarily exist on disk.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import re
from pathlib import Path

from declutter import cli, prompts

# Pinned so an accidental, or silent, edit to the shipped prompt fails this
# test loudly. A deliberate edit to layer2.md must update this constant, and
# whoever updates it is acknowledging the change, not rubber-stamping it.
PINNED_SHA256 = "89446d48ff11e2faccd86d88c40439cb7af353d765b9664db5ed4c6c22c5b631"


def test_prompt_reachable_through_package_accessor():
    # Not "does a file exist at this path" -- does the package's own
    # resource-loading route find it, the way importlib.resources does
    # inside an installed wheel.
    resource = importlib.resources.files("declutter.prompts").joinpath("layer2.md")
    assert resource.is_file()
    text = prompts.layer2_text()
    assert text.startswith("# Layer 2: cleanup prompt")
    assert len(text.splitlines()) > 50


def test_hash_matches_sha256_of_the_bytes_on_disk():
    data = prompts.layer2_bytes()
    assert prompts.layer2_sha256() == hashlib.sha256(data).hexdigest()


def test_hash_matches_pinned_value():
    # If this fails, either the prompt changed (update the pin deliberately
    # and say why in the commit) or something touched it by accident.
    assert prompts.layer2_sha256() == PINNED_SHA256


def test_prompt_passes_the_checker_at_critical_level():
    # Dogfooding: the prompt that demands clean output must itself produce
    # none of the findings that would block a run.
    resource_path = Path(str(importlib.resources.files("declutter.prompts").joinpath("layer2.md")))
    report = cli._build_report([resource_path], resource_path.parent, critical_only=False)
    critical = [f for f in report["findings"] if f["severity"] == "critical"]
    assert critical == []
    assert report["exit_code"] == 0


# --------------------------------------------------------------------------
# The five commitments from the approved plan. Each check looks for more
# than one marker, so a single incidental word match cannot satisfy it.
# --------------------------------------------------------------------------


def test_commitment_python_aware():
    text = prompts.layer2_text()
    # The prompt must show it knows Python-specific structure, not just
    # "code" in the abstract: docstrings versus comments, public surface
    # (dunder-all, decorators), import breakage, and the dead-code-versus-
    # test-only-code distinction all need to be present together.
    required_terms = [
        "docstring",
        "__all__",
        "decorator",
        "importer",
        "dead code",
    ]
    missing = [term for term in required_terms if term not in text]
    assert missing == [], f"missing Python-aware terms: {missing}"
    # The dead-code / test-reached distinction must be an explicit
    # contrast, not two unrelated mentions of "test".
    assert re.search(
        r"[Dd]ead code and code that only a test reaches are not the same",
        text,
    )


def test_commitment_keeps_rationale_comments():
    text = prompts.layer2_text()
    # A narration example (the kind that should go) and a rationale example
    # (the kind that must stay) both need to appear, contrastively, not
    # just the word "comment" in passing.
    assert "# increment i" in text
    assert "Retry once" in text
    assert "incident" in text
    # The unsure-default must be explicit and must resolve to keep.
    assert re.search(r"cannot tell which one you are looking at", text)
    assert re.search(r"default is keep", text)


def test_commitment_requires_running_tests():
    text = prompts.layer2_text()
    # Must reject "consider running" in favour of actually running, and
    # must require the result to be reported, not just the act performed.
    # \s+ tolerates the prompt's own line wrapping between words.
    assert re.search(r'[Nn]ot ["“]consider\s+running\s+it', text)
    assert re.search(r"run it, and report", text)
    assert re.search(r"unverified\s+diff", text)


def test_commitment_one_commit_per_file():
    text = prompts.layer2_text()
    assert re.search(r"^## One commit per file$", text, re.MULTILINE)
    assert "Do not bundle two files" in text
    assert "declutter: clean up path/to/file.py" in text


def test_commitment_follows_slop_rules():
    text = prompts.layer2_text()
    # Names the actual critical patterns from the catalogue, not a vague
    # restatement, and forbids rewording slop to dodge the regex.
    assert "`emoji`, `emoji_symbols`, `arrow_symbols`" in text
    assert "arrows spelled `->`" in text
    assert "launder slop" in text
    # And the prompt does not itself contain a literal unicode arrow or
    # emoji anywhere -- checked structurally, not by re-running the whole
    # catalogue here.
    assert not re.search(r"[\U0001F300-\U0001F9FF\U0001FA70-\U0001FAFF]", text)
    assert not re.search(r"[→←↔⇒⇐⇔]", text)  # declutter: allow=arrow_symbols


def test_commitment_scope_boundaries_are_explicit():
    text = prompts.layer2_text()
    # Beyond the five commitments: what layer 2 must never do, and the
    # pragma escape hatch for false positives, both need to be unmistakable.
    assert re.search(r"^## What this pass must never do$", text, re.MULTILINE)
    assert "Change behaviour" in text
    assert "Alter a public interface" in text
    assert "Touch a test to make it pass" in text
    assert "Reformat wholesale" in text
    assert "declutter: allow=<pattern" in text
