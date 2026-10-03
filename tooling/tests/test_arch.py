"""`_arch.validate_doc` builds its validator once per process.

The collector validates every producer file through it; rebuilding the schema
registry per file made per-artifact validation take most of a collector run.
"""

from __future__ import annotations

import pytest
from referencing import Registry

import _arch


def test_validate_doc_builds_the_schema_registry_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arch.artifact_validator.cache_clear()
    builds: list[Registry] = []
    real_build_registry = _arch.build_registry

    def counting_build_registry() -> Registry:
        registry = real_build_registry()
        builds.append(registry)
        return registry

    monkeypatch.setattr(_arch, "build_registry", counting_build_registry)
    doc = {"schemaVersion": "0.1", "producer": "example"}

    assert _arch.validate_doc(doc) == []
    assert _arch.validate_doc(doc) == []
    assert len(builds) == 1
