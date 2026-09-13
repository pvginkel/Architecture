"""Tests for the home-automation-fleet generator, `tools/ha-fleet/gen-ha-fleet.py`.

The generator is a script outside tooling, loaded here by path. `build` is fed a
registry dump shaped as Home Assistant's WebSocket API returns it, as `--raw` does.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

GENERATOR = Path(__file__).resolve().parents[2] / "tools" / "ha-fleet" / "gen-ha-fleet.py"

MOSQUITTO = {"entry_id": "e-mqtt", "domain": "mqtt", "title": "Mosquitto broker"}
OVERKIZ = {"entry_id": "e-overkiz", "domain": "overkiz", "title": "Somfy TaHoma"}
SONOS = {"entry_id": "e-sonos", "domain": "sonos", "title": "Sonos"}
# 2025-09-05 12:00 UTC: the same date in any local timezone the generator reads it in.
CREATED = 1757073600.0


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_ha_fleet", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _device(id_: str, entry: str, **fields: Any) -> dict[str, Any]:
    return {"id": id_, "config_entries": [entry], "created_at": CREATED, **fields}


def test_the_tahoma_gateway_and_the_devices_behind_it_surface_through_overkiz(
    gen: ModuleType,
) -> None:
    raw = {
        "entries": [MOSQUITTO, OVERKIZ, SONOS],
        "areas": [{"area_id": "hall", "name": "Hall"}],
        "devices": [
            _device(
                "d-gateway",
                "e-overkiz",
                identifiers=[["overkiz", "1234-5678-9012"]],
                manufacturer="Somfy",
                model="TaHoma Switch",
                name="TaHoma",
            ),
            _device(
                "d-blind",
                "e-overkiz",
                identifiers=[["overkiz", "io://1234-5678-9012/42"]],
                manufacturer="Somfy",
                model="Roller shutter",
                name="Hall blind",
                area_id="hall",
                via_device_id="d-gateway",
            ),
            _device(
                "d-speaker",
                "e-sonos",
                identifiers=[["sonos", "RINCON_1"]],
                manufacturer="Sonos",
                model="One",
                name="Speaker",
            ),
        ],
    }
    gaps: list[str] = []
    doc = gen.build(raw, {}, gaps)

    gateway = gen.device_uuid("overkiz:1234-5678-9012")
    blind = gen.device_uuid("overkiz:io://1234-5678-9012/42")
    gateway_slug = f"overkiz-tahoma-switch-{gateway.hex[:6]}"
    blind_slug = f"overkiz-roller-shutter-{blind.hex[:6]}"
    via = "surfaced in Home Assistant via the Overkiz (Somfy TaHoma) integration."
    assert {d["label"]: d for d in doc["devices"]} == {
        "TaHoma": {
            "id": f"device:{gateway_slug},{gateway}",
            "label": "TaHoma",
            "summary": f"Somfy TaHoma Switch {via}",
            "introduced": "2025-09-05",
            "lifecycle": "active",
            "stats": {
                "integration": "overkiz",
                "manufacturer": "Somfy",
                "model": "TaHoma Switch",
                "seedKey": "overkiz:1234-5678-9012",
            },
        },
        "Hall blind": {
            "id": f"device:{blind_slug},{blind}",
            "label": "Hall blind",
            "summary": f"Somfy Roller shutter in Hall {via}",
            "introduced": "2025-09-05",
            "lifecycle": "active",
            "stats": {
                "area": "Hall",
                "integration": "overkiz",
                "manufacturer": "Somfy",
                "model": "Roller shutter",
                "seedKey": "overkiz:io://1234-5678-9012/42",
            },
        },
    }
    assert sorted(doc["relations"], key=lambda r: r["source"]) == sorted(
        [
            {
                "id": f"rel:{slug}-serves-ha",
                "source": f"device:{slug},{uid}",
                "target": gen.HA_PRD,
                "type": "Serving",
            }
            for slug, uid in ((gateway_slug, gateway), (blind_slug, blind))
        ],
        key=lambda r: r["source"],
    )
    assert gaps == ["dropped 1 device(s): drop:sonos"]
