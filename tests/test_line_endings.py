"""Line endings are preserved and never rewritten.

A CRLF file and its LF twin must produce identical findings at identical
line numbers, and no run may modify any file it checks.
"""

from __future__ import annotations

import hashlib
import json


CONTENT_LF = "This is amazing.\nGreat work \U0001F40D\nnothing here\n"


def test_crlf_and_lf_twins_produce_identical_findings(tmp_path, run_declutter):
    lf_file = tmp_path / "lf.md"
    crlf_file = tmp_path / "crlf.md"
    lf_file.write_bytes(CONTENT_LF.encode("utf-8"))
    crlf_file.write_bytes(CONTENT_LF.replace("\n", "\r\n").encode("utf-8"))

    lf_result = run_declutter(["check", "--files", str(lf_file), "--output", "-"], tmp_path)
    crlf_result = run_declutter(["check", "--files", str(crlf_file), "--output", "-"], tmp_path)

    lf_report = json.loads(lf_result.stdout)
    crlf_report = json.loads(crlf_result.stdout)

    def strip_path(findings):
        return [
            {k: v for k, v in finding.items() if k != "path"}
            for finding in findings
        ]

    assert strip_path(lf_report["findings"]) == strip_path(crlf_report["findings"])
    assert lf_report["exit_code"] == crlf_report["exit_code"]


def test_run_does_not_modify_the_file(tmp_path, run_declutter):
    f = tmp_path / "crlf.md"
    raw = CONTENT_LF.replace("\n", "\r\n").encode("utf-8")
    f.write_bytes(raw)
    before = hashlib.sha256(f.read_bytes()).hexdigest()

    run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)

    after_bytes = f.read_bytes()
    after = hashlib.sha256(after_bytes).hexdigest()
    assert before == after
    assert after_bytes == raw
