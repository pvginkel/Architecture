#!/usr/bin/env python3
"""Generate the `home-automation-fleet` architecture artifact from live Home Assistant.

This is a *generated* architecture producer (same pattern as HelmCharts /
DockerImages): the artifact is a build output, the source of truth is this
generator plus the per-element annotation layer (`annotations.yaml`). It is its
OWN producer (`producer: home-automation-fleet`), built by its OWN scheduled
Jenkins job, not the main collector pipeline — only this job touches HA.

It introspects HA's device/entity/area registries over the WebSocket API and
emits one `device:` element for every HA-integrated *home-automation* hardware
device, each related into `cap:home-automation` (via Z2M or HA), so the Home
Assistant view *is* the live network.

INCLUSION RULE (explicit allowlist; everything else is dropped and logged):
  - Zigbee leaves: a device whose registry `identifiers` carry an
    `("mqtt", "zigbee2mqtt_0x<ieee>")` tuple AND that walks `via_device_id` to a
    `Zigbee2MQTT / Bridge` pseudo-device. The bridge pseudo-devices themselves
    are excluded (the Z2M *software* is modeled by helm-charts).
  - Integration devices in ALLOWED_INTEGRATIONS (dsmr / ecowitt / smlight /
    matter / esphome) — the P1 energy meters, the Ecowitt weather gateway, the
    SLZB coordinators, Matter and ESPHome/WiFi devices.

EXCLUSION (dropped, with a logged reason):
  - `manufacturer == "Pieter"`: in-house esp-mdm firmware, modeled by the
    firmware producers + `cap:iot-device` (Phase 1). DOUBLE-MODELING is the main
    hazard — this dedupes against the firmware producers by intent. (This also
    drops the unowned "Humble Remote" Zigbee device, manufacturer Pieter, per
    operator instruction to ignore it.)
  - HACS virtual helpers ("Dimmer from Switches"), the two Z2M Bridge
    pseudo-devices, and everything outside the allowlist (AV/media/companion/
    HA-internal: sonos, samsungtv, cast, mobile_app, sun, backup, sql, …).

ID / SEED SCHEME — LOAD-BEARING, DO NOT CHANGE. Hand-authored cross-producer
relations (the PoE wiring in docs/architecture/home-automation.yaml) reference
these device ids by composite id, so the UUID must be stable across runs:
  id     = device:<slug>,<uuid5>
  uuid5  = uuid5(NAMESPACE, seed_key)
  seed_key, in priority order:
    1. Zigbee leaf  -> "zigbee:0x<ieee>"          (the Zigbee IEEE address)
    2. identifiers  -> "<domain>:<id>"            (the primary registry tuple)
    3. connections  -> "mac:<mac>"                (smlight/esphome carry no
                                                   identifiers but do carry a MAC)
  A device with none of the above is dropped + logged (cannot mint a stable id).
  slug   = "<classtag>-<slug(model|name)>-<uuid.hex[:6]>" — starts with a letter
           (schema id pattern requires it), readable, unique, and stable (the
           uuid suffix is derived from seed_key, not from the mutable name).

The generator merges `annotations.yaml` over the live snapshot (friendly names,
lifecycle overrides, an operator-owned exclusion set, and the bridge->Z2M-instance
map). Unknown annotation keys fail loudly. It prints a gap report to stderr and
exits non-zero on a hard error; it never silently drops without logging.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import ssl
import sys
import uuid
from pathlib import Path

import yaml

PRODUCER = "home-automation-fleet"

# Pinned UUID5 namespace. uuid5(NAMESPACE_URL, <producer url>) — deterministic,
# documented, and FROZEN. Value: 6e6f8d2e-... (printed by --show-namespace).
NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://architecture.webathome.org/producers/home-automation-fleet",
)

# Devices predating HA's created_at tracking carry created_at == 0; `introduced`
# is schema-required, so fall back to the v0.1 project baseline (overridable per
# device via the annotation layer). Pinned, never "today" — the generator must be
# deterministic given a fixed HA state.
DEFAULT_INTRODUCED = "2024-07-12"

# Non-Zigbee integration domains we emit (home-automation device classes).
ALLOWED_INTEGRATIONS = {"dsmr", "ecowitt", "smlight", "matter", "esphome"}

# Cross-producer element ids, referenced by full composite id (resolved at merge).
HA_PRD = "ss:home-assistant-prd,398e32ec-cbe7-40e4-8a66-094029653650"

# Recognised annotation keys — anything else fails loudly.
ANNOTATION_KEYS = {"zigbee_bridges", "exclude", "overrides", "integration_serving"}
OVERRIDE_KEYS = {"label", "summary", "introduced", "lifecycle", "retirementBy"}


# ─────────────────────────── HA access ───────────────────────────


def fetch_ha() -> dict:
    """Pull the device/entity/area registries + config entries over the HA WS API."""
    import websocket  # imported here so --raw runs need no extra dep

    base = os.environ["HA_URL"].replace("https://", "wss://").replace("http://", "ws://")
    url = base.rstrip("/") + "/api/websocket"
    ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=20)
    ws.recv()
    ws.send(json.dumps({"type": "auth", "access_token": os.environ["HA_TOKEN"]}))
    if json.loads(ws.recv()).get("type") != "auth_ok":
        raise SystemExit("HA auth failed")
    state = {"_mid": 0}

    def cmd(t: str, **x):
        state["_mid"] += 1
        mid = state["_mid"]
        ws.send(json.dumps({"id": mid, "type": t, **x}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == mid and m.get("type") == "result":
                if not m.get("success"):
                    raise SystemExit(f"HA command {t} failed: {m}")
                return m["result"]

    raw = {
        "devices": cmd("config/device_registry/list"),
        "entities": cmd("config/entity_registry/list"),
        "areas": cmd("config/area_registry/list"),
        "entries": cmd("config_entries/get"),
    }
    ws.close()
    return raw


# ─────────────────────────── classification ───────────────────────────


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "device"


def device_domains(dev: dict, emap: dict) -> set[str]:
    return {emap.get(ce, {}).get("domain") for ce in dev.get("config_entries", [])}


def zigbee_ieee(dev: dict) -> str | None:
    for tup in dev.get("identifiers") or []:
        if len(tup) == 2 and tup[0] == "mqtt" and str(tup[1]).startswith("zigbee2mqtt_0x"):
            return str(tup[1])[len("zigbee2mqtt_"):]  # "0x...."
    return None


def first_mac(dev: dict) -> str | None:
    for tup in dev.get("connections") or []:
        if len(tup) == 2 and tup[0] == "mac":
            return str(tup[1])
    return None


def seed_key(dev: dict) -> str | None:
    ieee = zigbee_ieee(dev)
    if ieee:
        return f"zigbee:{ieee}"
    idents = dev.get("identifiers") or []
    if idents:
        dom, val = idents[0][0], idents[0][1]
        return f"{dom}:{val}"
    mac = first_mac(dev)
    if mac:
        return f"mac:{mac}"
    return None


def device_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, key)


def classify(dev: dict, emap: dict, bridge_ids: set[str]) -> str:
    """Return one of: zigbee-leaf | <integration> | excl:<reason> | drop:<reason>."""
    doms = device_domains(dev, emap)
    man = dev.get("manufacturer")
    if dev["id"] in bridge_ids:
        return "excl:z2m-bridge"
    if "mqtt" in doms and man == "Pieter":
        return "excl:pieter-firmware"
    if "mqtt" in doms and man and "Dimmer from Switches" in man:
        return "excl:hacs-helper"
    if zigbee_ieee(dev):
        return "zigbee-leaf"  # an mqtt zigbee2mqtt_ device that isn't a bridge
    for dom in doms:
        if dom in ALLOWED_INTEGRATIONS:
            return dom
    return "drop:" + (",".join(sorted(d for d in doms if d)) or "no-integration")


# ─────────────────────────── build ───────────────────────────


def build(raw: dict, annotations: dict, gaps: list[str]) -> dict:
    devices, entries = raw["devices"], raw["entries"]
    emap = {e["entry_id"]: e for e in entries}
    amap = {a["area_id"]: a.get("name") for a in raw["areas"]}

    # Resolve the Mosquitto MQTT entry by (domain == mqtt, title ~ Mosquitto).
    mqtt_entries = [
        e for e in entries if e["domain"] == "mqtt" and "mosquitto" in (e.get("title") or "").lower()
    ]
    if not mqtt_entries:
        raise SystemExit("no Mosquitto MQTT config entry found (domain=mqtt, title~Mosquitto)")

    bridge_ids = {d["id"] for d in devices if d.get("manufacturer") == "Zigbee2MQTT"}
    bridge_map = annotations.get("zigbee_bridges") or {}
    excluded = set(annotations.get("exclude") or [])
    overrides = annotations.get("overrides") or {}
    integ_serving = annotations.get("integration_serving") or {}

    out_devices: list[dict] = []
    out_relations: list[dict] = []
    used_keys: dict[str, str] = {}
    drop_counts: dict[str, int] = {}

    for dev in sorted(devices, key=lambda d: d["id"]):
        cls = classify(dev, emap, bridge_ids)
        if cls.startswith(("excl:", "drop:")):
            drop_counts[cls] = drop_counts.get(cls, 0) + 1
            continue

        key = seed_key(dev)
        if key is None:
            gaps.append(f"no stable seed key for device {dev.get('name')!r} ({cls}); skipped")
            continue
        if key in excluded:
            drop_counts["excl:operator"] = drop_counts.get("excl:operator", 0) + 1
            continue
        if key in used_keys:
            gaps.append(f"seed-key collision {key!r} between {used_keys[key]} and {dev['id']}; skipped")
            continue
        used_keys[key] = dev["id"]

        uid = device_uuid(key)
        classtag = {"zigbee-leaf": "zb"}.get(cls, cls)  # cls is the integration domain otherwise
        base = slugify(dev.get("model") or dev.get("name") or cls)
        slug = f"{classtag}-{base}"[:48].strip("-") + "-" + uid.hex[:6]
        eid = f"device:{slug},{uid}"

        ov = overrides.get(key, {})
        bad = set(ov) - OVERRIDE_KEYS
        if bad:
            raise SystemExit(f"annotation override for {key!r} has unknown keys: {sorted(bad)}")

        label = ov.get("label") or dev.get("name_by_user") or dev.get("name") or slug
        area = amap.get(dev.get("area_id"))
        created = dev.get("created_at") or 0
        if "introduced" in ov:
            introduced = ov["introduced"]
        elif created:
            introduced = datetime.date.fromtimestamp(float(created)).isoformat()
        else:
            introduced = DEFAULT_INTRODUCED
            gaps.append(f"{label!r} ({key}) has no created_at; introduced pinned to {DEFAULT_INTRODUCED}")

        stats = {"integration": cls}
        if dev.get("model"):
            stats["model"] = str(dev["model"])
        if dev.get("manufacturer"):
            stats["manufacturer"] = str(dev["manufacturer"])
        if area:
            stats["area"] = str(area)
        stats["seedKey"] = key

        element = {
            "id": eid,
            "label": label,
            "summary": ov.get("summary") or summarise(cls, dev, area),
            "introduced": introduced,
            "lifecycle": ov.get("lifecycle", "active"),
            "stats": dict(sorted(stats.items())),
        }
        if "retirementBy" in ov:
            element["retirementBy"] = ov["retirementBy"]
        out_devices.append(element)

        # ── relations ──
        if cls == "zigbee-leaf":
            ieee = zigbee_ieee(dev)
            bridge_ieee = _owning_bridge_ieee(dev, raw, bridge_ids)
            target = bridge_map.get(bridge_ieee) if bridge_ieee else None
            if target is None:
                gaps.append(
                    f"zigbee leaf {label!r}: owning bridge {bridge_ieee!r} not in "
                    f"annotations.zigbee_bridges; emitted WITHOUT a Z2M edge (won't reach the view)"
                )
            else:
                out_relations.append({
                    "id": f"rel:{slug}-serves-z2m",
                    "source": eid,
                    "target": target,
                    "type": "Serving",
                })
        else:
            target = integ_serving.get(cls, HA_PRD)
            out_relations.append({
                "id": f"rel:{slug}-serves-ha",
                "source": eid,
                "target": target,
                "type": "Serving",
            })

    # gap report: dropped buckets
    for reason, n in sorted(drop_counts.items()):
        gaps.append(f"dropped {n} device(s): {reason}")

    out_devices.sort(key=lambda d: d["id"])
    out_relations.sort(key=lambda r: r["id"])
    return {
        "schemaVersion": "0.1",
        "producer": PRODUCER,
        "devices": out_devices,
        "relations": out_relations,
    }


def _owning_bridge_ieee(dev: dict, raw: dict, bridge_ids: set[str]) -> str | None:
    dmap = {d["id"]: d for d in raw["devices"]}
    seen: set[str] = set()
    cur = dev
    while cur is not None:
        if cur["id"] in bridge_ids:
            return zigbee_bridge_ieee(cur)
        vd = cur.get("via_device_id")
        if not vd or vd in seen:
            break
        seen.add(vd)
        cur = dmap.get(vd)
    return None


def zigbee_bridge_ieee(bridge: dict) -> str | None:
    for tup in bridge.get("identifiers") or []:
        if len(tup) == 2 and tup[0] == "mqtt" and str(tup[1]).startswith("zigbee2mqtt_bridge_0x"):
            return str(tup[1])[len("zigbee2mqtt_bridge_"):]  # "0x...."
    return None


def summarise(cls: str, dev: dict, area: str | None) -> str:
    man = dev.get("manufacturer") or "Unknown"
    model = dev.get("model") or "device"
    where = f" in {area}" if area else ""
    if cls == "zigbee-leaf":
        return f"{man} {model}{where} — Zigbee device bridged to Home Assistant via Zigbee2MQTT."
    if cls == "dsmr":
        return f"DSMR smart-meter device ({dev.get('name')}) read over the P1 port and surfaced in Home Assistant."
    if cls == "ecowitt":
        return f"Ecowitt {model} weather gateway surfaced in Home Assistant via the Ecowitt integration."
    if cls == "smlight":
        return f"SMLIGHT {model} Zigbee coordinator surfaced in Home Assistant via the SMLIGHT integration."
    if cls == "matter":
        return f"{man} {model}{where} — Matter device surfaced in Home Assistant."
    if cls == "esphome":
        return f"ESPHome device ({model}){where} surfaced in Home Assistant via the ESPHome (WiFi) integration."
    return f"{man} {model}{where} surfaced in Home Assistant via the {cls} integration."


def load_annotations(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    bad = set(data) - ANNOTATION_KEYS
    if bad:
        raise SystemExit(f"{path}: unknown annotation keys {sorted(bad)} (allowed: {sorted(ANNOTATION_KEYS)})")
    return data


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="Generate the home-automation-fleet artifact from HA.")
    ap.add_argument("--out", default=str(here / "out"), help="output directory (artifact written under <out>/architecture/)")
    ap.add_argument("--annotations", default=str(here / "annotations.yaml"))
    ap.add_argument("--raw", help="load registries from a JSON file instead of live HA (testing/determinism)")
    ap.add_argument("--show-namespace", action="store_true", help="print the pinned UUID5 namespace and exit")
    args = ap.parse_args()

    if args.show_namespace:
        print(NAMESPACE)
        return

    raw = json.loads(Path(args.raw).read_text()) if args.raw else fetch_ha()
    annotations = load_annotations(Path(args.annotations))

    gaps: list[str] = []
    doc = build(raw, annotations, gaps)

    out_dir = Path(args.out) / "architecture"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "home-automation-fleet.yaml"
    out_path.write_text(yaml.safe_dump(doc, sort_keys=False, width=120, allow_unicode=True))

    print(f"wrote {out_path}: {len(doc['devices'])} devices, {len(doc['relations'])} relations", file=sys.stderr)
    if gaps:
        print(f"\n── gap report ({len(gaps)}) ──", file=sys.stderr)
        for g in gaps:
            print(f"  • {g}", file=sys.stderr)


if __name__ == "__main__":
    main()
