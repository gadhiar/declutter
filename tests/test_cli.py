from __future__ import annotations

import json

import pytest


def _write(path, text):
    path.write_text(text, encoding="utf-8", newline="")


def test_warning_only_does_not_block(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "This is amazing.\n")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["exit_code"] == 0
    names = {finding["pattern"] for finding in report["findings"]}
    assert "superlatives" in names


def test_critical_finding_blocks(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "Great work \U0001F40D\n")  # snake emoji: only the general emoji range
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)
    assert report["summary"]["counts_by_severity"]["critical"] >= 1
    assert result.returncode == 1
    assert report["exit_code"] == 1


def test_pragma_exempts_matching_line(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "Great work \U0001F40D <!-- declutter: allow=emoji -->\n")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)
    assert report["findings"] == []
    assert result.returncode == 0


def test_pragma_does_not_exempt_other_lines(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(
        f,
        "Great work \U0001F40D <!-- declutter: allow=emoji -->\n"
        "Bad line \U0001F40D\n",
    )
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)
    assert result.returncode == 1
    lines_with_findings = {finding["line"] for finding in report["findings"]}
    assert lines_with_findings == {2}


def test_critical_only_filters_report_not_exit_code(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "This is amazing \U0001F40D\n")
    full = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    full_report = json.loads(full.stdout)
    filtered = run_declutter(
        ["check", "--files", str(f), "--critical-only", "--output", "-"], tmp_path
    )
    filtered_report = json.loads(filtered.stdout)

    full_severities = {finding["severity"] for finding in full_report["findings"]}
    assert "warning" in full_severities
    assert "critical" in full_severities

    filtered_severities = {finding["severity"] for finding in filtered_report["findings"]}
    assert filtered_severities == {"critical"}

    assert full.returncode == filtered.returncode == 1


def test_output_dash_is_pure_json_on_stdout(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "plain text\n")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)  # raises if stdout is not pure JSON
    assert report["schema_version"] == 2
    assert "declutter:" not in result.stdout


def test_output_file_is_pure_json(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "plain text\n")
    out = tmp_path / "report.json"
    result = run_declutter(["check", "--files", str(f), "--output", str(out)], tmp_path)
    assert result.returncode == 0
    content = out.read_text(encoding="utf-8")
    report = json.loads(content)  # raises if not pure JSON
    assert report["schema_version"] == 2
    assert "declutter:" not in content


def test_progress_goes_to_stderr_not_stdout(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "plain text\n")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    assert "selected" in result.stderr
    assert "selected" not in result.stdout


def test_no_output_flag_prints_human_report_to_stdout(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "This is amazing.\n")
    result = run_declutter(["check", "--files", str(f)], tmp_path)
    assert result.returncode == 0
    assert "superlatives" in result.stdout
    assert str(f.name) in result.stdout or "note.md" in result.stdout


def test_undecodable_file_is_skipped_not_errored(tmp_path, run_declutter):
    f = tmp_path / "binaryish.py"
    f.write_bytes(b"\xff\xfe\x00\x01not valid utf8 \xff")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)
    assert report["summary"]["files_skipped"] == 1
    assert report["summary"]["files_checked"] == 0
    assert result.returncode == 0


def test_nonexistent_explicit_file_is_usage_error(tmp_path, run_declutter):
    result = run_declutter(["check", "--files", str(tmp_path / "missing.py")], tmp_path)
    assert result.returncode == 2
    assert result.stderr.strip() != ""
    assert result.stdout == ""


def test_selection_flags_are_mutually_exclusive(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "text\n")
    result = run_declutter(["check", "--files", str(f), "--all"], tmp_path)
    assert result.returncode == 2


def test_selection_flag_is_required(tmp_path, run_declutter):
    result = run_declutter(["check"], tmp_path)
    assert result.returncode == 2


def test_all_walks_from_git_toplevel(tmp_path, run_declutter, git_repo):
    (git_repo / "extra.py").write_text("This is amazing.\n", encoding="utf-8")
    subdir = git_repo / "sub"
    subdir.mkdir()
    (subdir / "deeper.py").write_text("This is amazing too.\n", encoding="utf-8")
    result = run_declutter(["check", "--all", "--output", "-"], subdir)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert "extra.py" in paths
    assert "sub/deeper.py" in paths


def test_all_excludes_default_directories(tmp_path, run_declutter, git_repo):
    excluded = git_repo / "node_modules"
    excluded.mkdir()
    (excluded / "vendored.js").write_text("This is amazing.\n", encoding="utf-8")
    result = run_declutter(["check", "--all", "--output", "-"], git_repo)
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert not any("node_modules" in p for p in paths)


def test_unchecked_extension_is_ignored_by_all(tmp_path, run_declutter, git_repo):
    (git_repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    result = run_declutter(["check", "--all", "--output", "-"], git_repo)
    assert result.returncode == 0
    report = json.loads(result.stdout)
    paths = {finding["path"] for finding in report["findings"]}
    assert not any(p.endswith(".png") for p in paths)


def test_findings_sorted_deterministically(tmp_path, run_declutter):
    f = tmp_path / "note.md"
    _write(f, "amazing amazing\nawesome\n")
    result = run_declutter(["check", "--files", str(f), "--output", "-"], tmp_path)
    report = json.loads(result.stdout)
    findings = report["findings"]
    keys = [(f["path"], f["line"], f["column"], f["pattern"]) for f in findings]
    assert keys == sorted(keys)
