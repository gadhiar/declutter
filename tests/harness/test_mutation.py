from __future__ import annotations

from declutter.harness.mutation import enumerate_sites


SOURCE = '''
def classify(n):
    if n > 0:
        return "positive"
    elif n < 0:
        return "negative"
    else:
        return "zero"

def is_even(n):
    return n % 2 == 0

FLAG = True

class Box:
    LIMIT = 10

    def over_limit(self, n):
        return n > self.LIMIT
'''


def test_enumerate_sites_is_deterministic_across_repeated_calls() -> None:
    first = enumerate_sites(SOURCE, "pkg/core.py")
    second = enumerate_sites(SOURCE, "pkg/core.py")
    assert [s.mutant_id for s in first] == [s.mutant_id for s in second]


def test_sites_are_sorted_by_the_total_key() -> None:
    sites = enumerate_sites(SOURCE, "pkg/core.py")
    keys = [s.sort_key for s in sites]
    assert keys == sorted(keys)


def test_mutant_id_is_derived_from_the_key_not_a_counter() -> None:
    sites = enumerate_sites(SOURCE, "pkg/core.py")
    for site in sites:
        assert site.mutant_id == f"{site.path}:{site.lineno}:{site.col_offset}:{site.node_class}:{site.operator_id}"
    # ids are unique
    assert len({s.mutant_id for s in sites}) == len(sites)


def test_sites_inside_functions_are_attributed_to_qualified_function_names() -> None:
    sites = enumerate_sites(SOURCE, "pkg/core.py")
    by_id = {s.mutant_id: s for s in sites}
    classify_sites = [s for s in sites if s.qualified_name == "pkg/core.py::classify"]
    assert len(classify_sites) >= 2  # the two comparisons n > 0 / n < 0
    is_even_sites = [s for s in sites if s.qualified_name == "pkg/core.py::is_even"]
    assert any(s.operator_id == "cmp_swap" for s in is_even_sites)


def test_site_in_method_gets_class_dotted_qualified_name() -> None:
    sites = enumerate_sites(SOURCE, "pkg/core.py")
    method_sites = [s for s in sites if s.qualified_name == "pkg/core.py::Box.over_limit"]
    assert len(method_sites) == 1
    assert method_sites[0].operator_id == "cmp_swap"


def test_module_level_and_class_body_sites_go_to_module_bucket() -> None:
    sites = enumerate_sites(SOURCE, "pkg/core.py")
    module_sites = [s for s in sites if s.qualified_name == "pkg/core.py::<module>"]
    # FLAG = True is a module-level bool constant; Box.LIMIT = 10 is a class-body
    # assignment, not inside any method, so it also lands in the module bucket.
    assert any(s.operator_id == "bool_const_invert" for s in module_sites)
    assert any(s.operator_id == "num_const_perturb" and s.node_class == "Constant" for s in module_sites)


def test_chained_comparison_is_not_a_mutation_site() -> None:
    sites = enumerate_sites("def f(a, b, c):\n    return a < b < c\n", "m.py")
    assert all(s.node_class != "Compare" for s in sites)
