"""The `webUi` interface attribute at the validation boundary.

Each case validates one in-memory artifact against
schema/v0.1/architecture.schema.yaml through `_arch.validate_doc`, the check
validate.py runs on an artifact file.
"""

from __future__ import annotations

from typing import Any

import pytest

from _arch import load_master_schema, validate_doc

UUID = "3f1c2a4e-9b7d-4e21-8c5a-0d6f1e2b3c4d"

# One schema-valid element id per element array of the master schema.
ELEMENT_IDS: dict[str, str] = {
    "nodes": f"node:host,{UUID}",
    "devices": f"device:board,{UUID}",
    "systemSoftware": f"ss:daemon,{UUID}",
    "applicationComponents": f"app:portal,{UUID}",
    "applicationServices": f"svc:portal,{UUID}",
    "applicationInterfaces": f"if:portal-web,{UUID}",
    "technologyServices": f"svc:store,{UUID}",
    "technologyInterfaces": f"if:store-console,{UUID}",
    "capabilities": "cap:iam",
    "businessServices": "bsvc:self-service",
    "groupings": f"grp:cluster,{UUID}",
}
INTERFACE_KEYS = ("applicationInterfaces", "technologyInterfaces")
OTHER_KEYS = sorted(set(ELEMENT_IDS) - set(INTERFACE_KEYS))


def artifact(key: str, **attributes: Any) -> dict[str, Any]:
    element = {
        "id": ELEMENT_IDS[key],
        "label": "Example",
        "summary": "An example element.",
        "introduced": "2026-09-14",
        "lifecycle": "active",
        **attributes,
    }
    return {"schemaVersion": "0.1", "producer": "example", key: [element]}


def error_sites(doc: dict[str, Any]) -> list[tuple[list[str | int], str]]:
    return [(list(e.absolute_path), str(e.validator)) for e in validate_doc(doc)]


def test_element_ids_cover_every_element_array() -> None:
    properties = load_master_schema()["properties"]
    element_keys = {
        key for key, spec in properties.items() if spec.get("type") == "array"
    } - {"relations"}
    assert element_keys == set(ELEMENT_IDS)


@pytest.mark.parametrize("key", sorted(ELEMENT_IDS))
def test_element_without_web_ui_validates(key: str) -> None:
    assert error_sites(artifact(key)) == []


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("key", INTERFACE_KEYS)
def test_interface_accepts_boolean_web_ui(key: str, value: bool) -> None:
    assert error_sites(artifact(key, webUi=value)) == []


@pytest.mark.parametrize("value", ["true", "yes", 1, 0, None])
@pytest.mark.parametrize("key", INTERFACE_KEYS)
def test_interface_rejects_non_boolean_web_ui(key: str, value: Any) -> None:
    assert error_sites(artifact(key, webUi=value)) == [([key, 0, "webUi"], "type")]


@pytest.mark.parametrize("key", OTHER_KEYS)
def test_other_kinds_reject_web_ui(key: str) -> None:
    assert error_sites(artifact(key, webUi=True)) == [([key, 0], "additionalProperties")]
