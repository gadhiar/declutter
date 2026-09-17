from __future__ import annotations

from declutter.pragma import allowed_names


def test_no_pragma_returns_empty():
    assert allowed_names("just an ordinary line") == frozenset()


def test_single_name_hash_comment():
    assert allowed_names("x = 1  # declutter: allow=emoji") == frozenset({"emoji"})


def test_comma_separated_names():
    line = "x = 1  # declutter: allow=emoji,arrow_symbols"
    assert allowed_names(line) == frozenset({"emoji", "arrow_symbols"})


def test_comma_separated_names_with_spaces():
    line = "x = 1  # declutter: allow=emoji, arrow_symbols , bold_consulting"
    assert allowed_names(line) == frozenset(
        {"emoji", "arrow_symbols", "bold_consulting"}
    )


def test_matches_any_comment_syntax():
    assert allowed_names("// declutter: allow=emoji") == frozenset({"emoji"})
    assert allowed_names("<!-- declutter: allow=emoji -->") == frozenset({"emoji"})
    assert allowed_names("-- declutter: allow=emoji") == frozenset({"emoji"})
    assert allowed_names("' declutter: allow=emoji") == frozenset({"emoji"})


def test_multiple_pragmas_on_one_line_union():
    line = "# declutter: allow=emoji -- declutter: allow=arrow_symbols"
    assert allowed_names(line) == frozenset({"emoji", "arrow_symbols"})


def test_no_wildcard_support():
    # "*" is not a valid name character, so it is never captured.
    assert allowed_names("# declutter: allow=*") == frozenset()


def test_unknown_name_is_still_returned():
    # allowed_names does not validate names against the pattern catalogue;
    # it exposes exactly what was written so a typo stays visible.
    result = allowed_names("# declutter: allow=emojji")
    assert result == frozenset({"emojji"})
    assert "emoji" not in result
