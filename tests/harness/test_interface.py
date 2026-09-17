from __future__ import annotations

from declutter.harness.interface import diff_module, snapshot_source


SOURCE = '''
__all__ = ["greet", "Greeter"]

CONST: int = 1
_private_const = 2

def greet(name: str, *, loud: bool = False) -> str:
    return name

def _hidden(x):
    return x

class Greeter:
    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self, /, times: int = 1, *args, **kwargs) -> str:
        return self.name

    def _private_method(self):
        pass

class _Hidden:
    pass
'''


def test_snapshot_captures_all() -> None:
    snap = snapshot_source(SOURCE)
    assert snap["all"] == ["Greeter", "greet"]


def test_snapshot_captures_public_functions_only() -> None:
    snap = snapshot_source(SOURCE)
    assert set(snap["functions"]) == {"greet"}
    sig = snap["functions"]["greet"]
    assert [p["name"] for p in sig["params"]] == ["name", "loud"]
    assert sig["params"][1]["kind"] == "KEYWORD_ONLY"
    assert sig["params"][1]["has_default"] is True
    assert sig["params"][1]["default"] == "False"
    assert sig["returns"] == "str"


def test_snapshot_captures_public_classes_and_methods_only() -> None:
    snap = snapshot_source(SOURCE)
    assert set(snap["classes"]) == {"Greeter"}
    methods = snap["classes"]["Greeter"]["methods"]
    # __init__ is a dunder: this package keeps no dunder exception, so it is
    # excluded along with every other leading-underscore name.
    assert set(methods) == {"greet"}
    greet_params = methods["greet"]["params"]
    kinds = [p["kind"] for p in greet_params]
    assert kinds == ["POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD", "VAR_POSITIONAL", "VAR_KEYWORD"]


def test_snapshot_captures_public_module_level_assignments() -> None:
    snap = snapshot_source(SOURCE)
    assert set(snap["assigned"]) == {"CONST"}
    assert snap["assigned"]["CONST"]["annotation"] == "int"


def test_leading_underscore_names_are_excluded_including_dunders() -> None:
    snap = snapshot_source(SOURCE)
    assert "_hidden" not in snap["functions"]
    assert "_private_method" not in snap["classes"]["Greeter"]["methods"]
    assert "__init__" not in snap["classes"]["Greeter"]["methods"]
    assert "_Hidden" not in snap["classes"]


def test_diff_module_reports_no_change_for_identical_snapshots() -> None:
    snap = snapshot_source(SOURCE)
    diff = diff_module(snap, snap)
    assert diff == {"status": "ok", "added": [], "removed": [], "changed": []}


def test_diff_module_reports_removed_function_as_removed_member() -> None:
    baseline = snapshot_source(SOURCE)
    candidate = snapshot_source(SOURCE.replace("def greet(name: str, *, loud: bool = False) -> str:\n    return name\n\n", ""))
    diff = diff_module(baseline, candidate)
    assert "function:greet" in diff["removed"]
    assert diff["status"] == "ok"


def test_diff_module_reports_changed_signature() -> None:
    baseline = snapshot_source(SOURCE)
    candidate = snapshot_source(SOURCE.replace("loud: bool = False", "loud: bool = True"))
    diff = diff_module(baseline, candidate)
    assert "function:greet" in diff["changed"]


def test_diff_module_reports_added_function_as_added_member() -> None:
    baseline = snapshot_source(SOURCE)
    candidate = snapshot_source(SOURCE + "\ndef extra() -> None:\n    pass\n")
    diff = diff_module(baseline, candidate)
    assert diff["added"] == ["function:extra"]
    assert diff["removed"] == []
    assert diff["changed"] == []


def test_diff_module_missing_in_candidate_is_removed_module() -> None:
    baseline = snapshot_source(SOURCE)
    diff = diff_module(baseline, None)
    assert diff["status"] == "removed_module"
