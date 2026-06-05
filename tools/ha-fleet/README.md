# home-automation-fleet — generated architecture producer

A **separate** architecture producer that snapshots the live Home Assistant
device fleet once a day and emits it as an Architecture-as-Code artifact, so the
Home Assistant view *is* the live network. Same generated-producer pattern as
HelmCharts / DockerImages: the artifact is a build output; the source of truth is
`gen-ha-fleet.py` + the `annotations.yaml` layer.

It is its **own** producer (`producer: home-automation-fleet`) with its **own
scheduled Jenkins job** — only this job touches HA. The main collector pipeline
stays HA-free and deterministic; it just `copyArtifacts`-es the result.

## What it emits

One `device:` element per HA-integrated **home-automation** hardware device,
each related into `cap:home-automation`:

| Class | Source | Serving edge |
|---|---|---|
| Zigbee leaves | Z2M (`mqtt` + `via_device`→Bridge) | → its owning Z2M instance |
| P1 energy meters | `dsmr` | → Home Assistant (prd) |
| Ecowitt weather gateway | `ecowitt` | → Home Assistant (prd) |
| SLZB coordinators | `smlight` | → Home Assistant (prd) |
| Matter / ESPHome (WiFi) | `matter` / `esphome` | → Home Assistant (prd) |

**Excluded (logged):** `manufacturer == "Pieter"` (in-house firmware, modeled by
the firmware producers + `cap:iot-device` — avoids double-modeling), the Z2M
Bridge pseudo-devices (Z2M software is modeled by helm-charts), HACS virtual
helpers, and everything outside the allowlist (AV/media/companion/HA-internal:
sonos, samsungtv, cast, mobile_app, sun, backup, sql, …). The inclusion rule is
an explicit allowlist; every dropped device is counted in the stderr gap report.

## ID / seed scheme — LOAD-BEARING, FROZEN

Device ids are `device:<slug>,<uuid5>` where `uuid5 = uuid5(NAMESPACE, seed_key)`.
Hand-authored cross-producer relations (the PoE wiring in
`docs/architecture/home-automation.yaml`) reference these ids by composite id, so
the UUID **must** be stable across runs. Do not change `NAMESPACE` or the seed
scheme.

- `NAMESPACE` = `8f7a96b4-538b-5991-8906-7acd41c42af0`
  (`uuid5(NAMESPACE_URL, "https://architecture.webathome.org/producers/home-automation-fleet")`;
  print with `gen-ha-fleet.py --show-namespace`).
- `seed_key`, in priority order: Zigbee IEEE (`zigbee:0x…`) → primary registry
  `identifiers` tuple (`<domain>:<id>`) → MAC from `connections` (`mac:…`, used by
  smlight/esphome which carry no identifiers). No stable key → dropped + logged.

## Annotation layer (`annotations.yaml`)

Operator overrides merged over the live snapshot; unknown top-level keys fail
loudly. Keys are `seed_key`s.

- `zigbee_bridges`: bridge-IEEE → Z2M instance element id (puts each leaf within
  depth-1 of `cap:home-automation`). **Verify the floor assignment** — HA doesn't
  expose which physical coordinator a bridge is.
- `exclude`: seed_keys to suppress.
- `overrides`: per-device `{label, summary, introduced, lifecycle, retirementBy}`.
- `integration_serving`: per-integration Serving-target override (default HA-prd).

## Running

```bash
# live (needs HA_URL + HA_TOKEN and network reach to HA):
python3 gen-ha-fleet.py                 # writes out/architecture/home-automation-fleet.yaml
# offline / determinism test, from a pre-pulled registry dump:
python3 gen-ha-fleet.py --raw ha_raw.json
```
Runtime deps: `pyyaml`, `websocket-client` (the latter only for the live path).
Output is gitignored (a build output). The run is deterministic given a fixed HA
state; the gap report goes to stderr.

## Scheduled Jenkins job

The pipeline is `Jenkinsfile.ha-fleet` (at the repo root): a standalone job,
separate from the main AaC pipeline, that runs the generator, validates the
output against the validation service (`scripts/arch-validate.py` — fails without
publishing on a non-zero exit), and archives
`out/architecture/home-automation-fleet.yaml` (under an `architecture/` path so
the main pipeline's `copyArtifacts` filter `**/architecture/**/*.yaml` picks it
up — same contract as every other producer; no commit-back).

To wire it up: new Jenkins Pipeline job (e.g. `AaC/HomeAutomationFleet`),
*Pipeline script from SCM*, repo = this one, **Script Path =
`Jenkinsfile.ha-fleet`**. The pipeline declares **no trigger** — set the daily
schedule in the job config (Build Triggers → Build periodically).

Secrets:
- **`HA_TOKEN`** comes from OpenBao via `withVault` (same pattern as the other
  Vault-backed pipelines). Store it at **KV-v2 path `kv/jenkins/home-automation-fleet`,
  key `ha_token`** — a HA long-lived access token. The firmware repos' MQTT users
  are ACL-scoped, do **not** reuse one; the HA token is the only source that sees
  DSMR/Ecowitt/SLZB/WiFi, not just Zigbee. The controller-level Vault config
  supplies the address + auth.
- **`HA_URL`** is read from the ambient global Jenkins environment (already set),
  forwarded into the build container by the Jenkinsfile.

Registering the producer in `pipeline-producers.yaml` and migrating the
hand-authored HA devices out of `docs/architecture/home-automation.yaml` are
**activation steps** that must land together with this job — doing either before
the job produces an artifact breaks the main build / erases those devices from
the model. See the activation handoff.
