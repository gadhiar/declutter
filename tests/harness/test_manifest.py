from __future__ import annotations

import pytest

from declutter.harness.manifest import ManifestError, manifest_to_dict, parse_manifest
from .conftest import build_manifest_dict


def test_parses_a_well_formed_manifest() -> None:
    manifest = parse_manifest(build_manifest_dict())
    assert manifest.schema_version == 1
    assert len(manifest.invocations) == 3
    assert manifest.interface_modules == ("pkg/core.py",)
    assert manifest.mutation.target_modules == ("pkg/core.py",)
    assert manifest.mutation.kill_rate_tolerance == 0.0


def test_round_trips_through_manifest_to_dict() -> None:
    manifest = parse_manifest(build_manifest_dict())
    again = parse_manifest(manifest_to_dict(manifest))
    assert again == manifest


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("schema_version"),
        lambda d: d.__setitem__("schema_version", 99),
        lambda d: d.__setitem__("invocations", "not-a-list"),
        lambda d: d["invocations"].append({"id": "dup", "argv": ["-m", "pkg"]}) or d["invocations"].append(
            {"id": "dup", "argv": ["-m", "pkg"]}
        ),
        lambda d: d["invocations"][0].pop("argv"),
        lambda d: d["mutation"].pop("test_command"),
    ],
)
def test_rejects_malformed_manifests(mutate) -> None:
    data = build_manifest_dict()
    mutate(data)
    with pytest.raises(ManifestError):
        parse_manifest(data)


def test_empty_manifest_sections_are_allowed() -> None:
    manifest = parse_manifest(
        {
            "schema_version": 1,
            "invocations": [],
            "interface_modules": [],
            "mutation": {},
            "scrub_rules": [],
        }
    )
    assert manifest.invocations == ()
    assert manifest.mutation.target_modules == ()
    assert manifest.mutation.test_command is None
