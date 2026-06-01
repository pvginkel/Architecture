# IoT device architecture — guidance for the IoT Support producer

How the in-house ESP32 device fleet is modeled in the federated Architecture-as-Code
system, and the spec for the **device generator** that IoT Support will grow to emit the
physical fleet and its realized dependency edges.

Audience: whoever builds the IoT Support architecture generator. Authoritative vocabulary
is `~/.claude/architecture/producer-manual.md`; this is the device-fleet-specific layer.

---

## 1. Division of ownership

Two producers, one clean split:

- **Firmware repos** (one producer each: `calendar-display`, `doorbell-receiver`,
  `gesture-device`, `underfloor-heating-controller`, `somfy-remote`, `paper-clock`,
  `intercom`, `infra-statistics-display`, …) declare **what the repo introduces: the
  firmware**. Each emits a single firmware «SoftwareProduct» plus its *logical*
  consumption edges. They do **not** model the physical device — a repo doesn't introduce
  hardware.
- **IoT Support** (this producer) owns the **device registry** and will generate the
  physical **`device:` fleet** from it, bind each device to the firmware it runs, and emit
  the **realized** `Serving` edges. This is the work this document specs.

The firmware producers are already live (seeded May–Jun 2026 backfill, batch 2). The device
generator is the missing half.

---

## 2. What a firmware producer declares (the input you consume)

Each firmware artifact (`docs/architecture/architecture.yaml`) contains:

- One **`ss:` «SoftwareProduct»** — the firmware, kind **SystemSoftware** (bare-metal
  firmware on the MCU), with `sourceRepository: git:pvginkel/<Repo>`. Chosen as
  SystemSoftware specifically so a generated `device: —Assignment→ ss:` reads cleanly.
- **Logical consumption edges** — `type: Association`, `source` = the firmware, **no
  `boundBy`** (see §3 for why). The edge set is *fixed by firmware code* and *uniform across
  every device running that firmware*.

### Edge vocabulary in the fleet

| Logical edge (target) | Meaning | Which firmware |
|---|---|---|
| `svc:iotsupport-api` (`b7c5b5ba-…`) | the MDM device API (config / firmware / provisioning / coredump) | **all** |
| `cap:pub-sub-broker` | the MQTT broker (logs, state, control) | **all** |
| `cap:iam` | Keycloak M2M (client-credentials) | **all** |
| `svc:home-assistant-mqtt` (`23572189-…`) | Home Assistant MQTT integration (publishes HA discovery entities, or consumes HA-published data) | doorbell, gesture, underfloor-heating, somfy, intercom (publish); paper-clock (consume) |
| `svc:calendar-support` (`e469b02a-…`) | device-specific backend | calendar-display |
| `svc:infra-statistics` (`e6a1608a-…`) | device-specific backend | infra-statistics-display |
| `svc:intercom` (`5914e568-…`) | the Intercom relay service (realized by `intercom-server`) | intercom |

The first three are the **universal MDM set** every device gets. The rest are device- or
family-specific. Read the authoritative, current set from each firmware «SoftwareProduct»'s
edges in the **published dataset**, not from this table — the table is orientation.

---

## 3. The realization model (the core rule)

Why firmware edges are realized differently from Helm app edges:

- **Helm-deployed apps are config-driven.** The same image across dev/tst/uat/prd gets
  different providers, and per-workload env scoping decides which edges even exist. So the
  deployer *must* read the rendered release config — hence `boundBy: env:VAR` as the recipe.
- **IoT firmware is code-fixed + registration-driven.** The edge set is baked into the
  firmware and is identical for every device running it. There is no per-instance variation
  to discover and no recipe to read — the only variable is **whether the device is
  registered**.

### The rule

> **For each registered device, every logical edge on its firmware is realized
> unconditionally as `provider-instance —Serving→ device`.**

The generator, per registered device:

1. Resolve the device's **firmware product** from the registry's firmware **image name**
   (the CMake `project()` name, snake_case, e.g. `calendar_display`) via the IoT Support
   **image→product mapping file** (§5). The model has no artifact/image element, so the
   image name is not an element identity — this mapping is a required generator input.
2. Read that firmware «SoftwareProduct»'s logical edges from the published dataset.
3. For each logical edge, resolve the **concrete provider instance** and emit a `Serving`
   edge to this device.

### Resolving the provider per edge

- **`cap:` targets** (`cap:pub-sub-broker`, `cap:iam`) resolve to the concrete provider from
  the **host IoT Support itself provisioned** into the device's NVS:
  - `cap:pub-sub-broker` → the broker at the device's `mqtt_url` → the **mosquitto** instance.
  - `cap:iam` → the issuer at the device's `token_url` → the **Keycloak** instance.
  - This is a fleet constant — IoT Support wrote those values, so it owns the mapping.
- **Concrete `svc:` targets** (`svc:iotsupport-api`, `svc:home-assistant-mqtt`,
  `svc:calendar-support`, `svc:infra-statistics`, `svc:intercom`) already name the provider;
  resolve to its realizing instance (the prd deployment) from the published dataset.

This is exactly why the firmware edges carry **no `boundBy`**: the realization input is
*registration + IoT Support's own provisioning records*, not a per-edge recipe.

### The one caveat — conditional edges

The unconditional rule holds **only while edges are uniform per firmware**. If a firmware
ever makes an edge depend on *device config* (only some of its devices hit a backend, driven
by the delivered config JSON rather than compiled-in code), that one edge needs
registry/config conditioning — and that is the place a new `boundBy: field:<dotted.path>`
recipe would finally earn its keep (it was deliberately **not** introduced now; nothing uses
it — the device-specific backends today are compile-time Kconfig constants). If you add it,
extend the `boundBy` regex in `schema/v0.1/subset.yaml` (currently pinned to `^env:…$`).

---

## 4. Element shapes to emit (recommended starting point — your call)

This is a **generated** producer, so model as-deployed and derive ids by **uuid5 from a
stable natural key** (the device MAC / `device_key`), under a fixed IoT Support namespace
UUID. Strip any deploy-time randomness; regenerate twice and diff to confirm byte-identical.

Recommended per registered device:

- A **`device:`** element — the physical unit. Natural key = MAC. Carry the model/firmware
  in `stats`; keep runtime state (online/health) out (identity fence).
- A **firmware SystemSoftware instance** `ss:<firmware>-<device>` that **`Specialization`**s
  the firmware «SoftwareProduct» (the type the firmware repo owns), with the device
  **`Assignment`**-ed to it (`device: —Assignment→ ss:`).
- The realized **`Serving`** edges from §3 target the firmware *instance* (the running
  consumer), mirroring how a pod instance specialises its app product and edges attach to
  the instance.

Keep `environment`/`cluster` consistent and use a `Grouping` per natural axis if the fleet
gets large, so instances collapse under their firmware product in the viewer.

(Alternative: attach `Serving` edges directly to the `device:` and `Assignment` it to the
firmware *product* — fewer elements, but a `device → product` assignment is a type-level
edge. The instance form above is cleaner and matches the manual's as-deployed guidance.
Pick one and apply it uniformly.)

---

## 5. Data sources & determinism

- **Device registry** (IoT Support's own data): MAC → firmware image name, and the
  provisioned `mqtt_url` / `token_url` / `base_url` per device. This is the generator's
  primary input and the source for `cap:` resolution.
- **Image→product mapping** (a single IoT Support annotation file): maps each firmware
  **image name** (`calendar_display`, `doorbell_receiver`, …) → the firmware
  «SoftwareProduct» (`ss:<hint>`). v0.1 has no artifact/image element, so this side-channel
  is how device→product resolves — the same shape HelmCharts uses for container images
  (`charts/<chart>/architecture.yaml` `images:`). Stopgap until the v0.2 Artifact element
  lands (§7).
- **Published dataset** (`https://architecture.webathome.org/data/v0.1/architecture.yaml`):
  resolve the firmware «SoftwareProduct»s, their logical edges, and the concrete provider
  instances (`hint`+kind → uuid, read-only). Overlay any not-yet-published sibling producer
  from a local checkout while testing, per the manual's resolver guidance. **Do not
  hand-copy UUIDs** — they're in the dataset.
- **Determinism:** uuid5 keys must be stable across renders or cross-producer refs dangle on
  every build. No `Date.now()`/random in keys or emitted fields.

---

## 6. Provider reference (orientation — resolve live from the dataset)

Logical targets are stable hand-authored ids; the realizing **instances** are HelmCharts /
self-producer uuid5 ids you should resolve from the published dataset at build time:

| Logical target | Realizing instance (resolve live) |
|---|---|
| `svc:iotsupport-api` `b7c5b5ba-…` | the prd `iotsupport-app` workload |
| `cap:pub-sub-broker` (via `mqtt_url`) | the `mosquitto` instance |
| `cap:iam` (via `token_url`) | the prd `keycloak` instance |
| `svc:home-assistant-mqtt` `23572189-…` | `ss:home-assistant-prd` (self-producer) |
| `svc:calendar-support` `e469b02a-…` | the prd `calendar-support` workload |
| `svc:infra-statistics` `e6a1608a-…` | the prd `infra-statistics` workload |
| `svc:intercom` `5914e568-…` | the `intercom-server` workload (once deployed) |

Until each firmware producer's first archived build publishes, references to its
«SoftwareProduct» dangle (reported, not fatal). `svc:home-assistant-mqtt` and `svc:intercom`
are new (self-producer / `intercom-server`); they resolve once those producers next build.

---

## 7. Background

- This doc stands alone: §3 is the full realization spec, not a digest — no external file
  is needed. (Its batch-2 working record lived in the gitignored `tmp/backfill/REVIEW-2.md`,
  now superseded by this doc.)
- Per-firmware modeling notes are committed inside each firmware repo at
  `docs/architecture/SEED-NOTES.md` (durable, not part of any backfill scratch folder).
- Trello card #25 ("Model the IoT device fleet that depends on iotsupport-app") is the
  umbrella this generator closes.
- The image→product mapping file is a stopgap for a v0.1 gap: build artifacts (container
  images, firmware binaries) have no element kind, so name→product is a side-channel in both
  HelmCharts and IoT Support. Proper fix tracked as a Trello backlog card: a v0.2 ArchiMate
  «Artifact» element (build-name identity + `Artifact —Realization→ «SoftwareProduct»`),
  after which both side-channels resolve through the model.
