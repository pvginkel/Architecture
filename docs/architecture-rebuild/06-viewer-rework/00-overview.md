# Viewer rework — overview & shared anchor

The `viewer/` prototype (`viewer/src/data/architecture.ts`, a hand-built
capability/edge-type taxonomy) is being rebuilt into a **data-driven viewer over
the federated ArchiMate manifest**. This directory holds four standalone plans.
Each is self-contained and meant to be executed in its **own conversation**, in
order. This file is the shared context every plan assumes.

**Purpose of the viewer:** a portfolio piece on a personal site
(webathome.org), iframe-embedded. It gives a high-level impression of the stack
to someone having a quick look. It is *not* a production enterprise-architecture
tool. Views and filters are the core strength and must be user-friendly.

## Run order & dependencies

| Plan | Title | Depends on |
|---|---|---|
| [Plan 1](plan-1-foundation.md) | Foundation: real manifest + ArchiMate model, theme, icons, vocab codegen | — |
| [Plan 2](plan-2-logo-schema.md) | Logo schema widening + library enum | — (independent; can run any time) |
| [Plan 3](plan-3-filter-rail.md) | Two-panel filter rail | Plan 1 |
| [Plan 4](plan-4-views.md) | Curated views | Plan 1, Plan 3 |

Each plan leaves a **working, committed viewer**. Plan 2 is standalone (schema +
tooling + docs); it is listed second but could go first.

## How to execute a plan (cold start)

1. Read this overview, the target plan file, and the `project_viewer-rework`
   auto-memory.
2. Work the plan's steps. Commit each meaningful unit without being asked (house
   rule); do not push (no push rights).
3. Honour the repo's **fail-fast / no-defensive-coding** stance: no swallowed
   errors, no "just in case" fallbacks, loud failures over silent degradation.
4. Python tooling uses **Poetry** (`cd tooling && poetry run …`); no pip/venv.
5. Schema vocabulary spells names out (no abbreviations) — applies to any new
   metaschema attribute names introduced.

## The data contract — `/data/v0.1/architecture.json`

Produced by `tooling/collect.py` (`assemble_merged_dataset`), served CORS-open by
`service/` at `/data/v0.1/architecture.{json,yaml}`. Shape:

```jsonc
{
  "schemaVersion": "0.1",
  "producers": ["ansible", "helm", ...],     // registered producer ids
  "nodes": [ … ], "devices": [ … ], "systemSoftware": [ … ],
  "applicationComponents": [ … ], "applicationServices": [ … ],
  "applicationInterfaces": [ … ], "technologyServices": [ … ],
  "technologyInterfaces": [ … ], "capabilities": [ … ],
  "businessServices": [ … ], "groupings": [ … ],
  "relations": [ { "id", "source", "target", "type", "boundBy"?, "boundByDefaultValue"? } ],
  "derived": {
    "groupings": { "<grp-id>": ["<member-id>", …] },
    "capabilityRealizations": { "<cap-id>": ["<realising-element-id>", …] }
  }
}
```

The eleven element-kind arrays and their ArchiMate concept names are the
`ELEMENT_KIND_ARRAYS` / `ARRAY_TO_ARCHIMATE` maps in `tooling/collect.py:48`.

**Per-element fields:** `id` (prefix-typed, e.g. `ss:…`, `app:…`, `cap:…`),
`label`, `summary`, `introduced`, `lifecycle` (`active`/`deprecated`/`removed`),
`producer` (stamped by the collector), plus per-kind attributes: `environment`
(`dev`/`tst`/`uat`/`prd`), `cluster`, `stereotype`, `logo`, `homepage`,
`sourceRepository`, `stats` (free-form string→string).

**Per-element layer** is *not* in the data — it's a property of the element's
**kind**, declared in `schema/v0.1/subset.yaml` (`kinds.<Kind>.layer`). The viewer
gets it from the generated vocab (Plan 1). Kind→layer:

| Layer | Kinds |
|---|---|
| technology | Node, Device, SystemSoftware, TechnologyService, TechnologyInterface |
| application | ApplicationComponent, ApplicationService, ApplicationInterface |
| strategy | Capability |
| business | BusinessService |
| cross-cutting | Grouping |

**A node's realized capability** comes from inverting
`derived.capabilityRealizations` (cap → [elements] ⇒ element → cap).

## The schema contract — `/schema/v0.1/*`

`subset.yaml` declares the 11 kinds (each with `layer`, `archimateType`,
`idPrefix`, `idRegex`, attributes). `tooling/generate.py` reads it + the vendored
ArchiMate XSD/matrix and emits per-kind JSON Schemas + `relations.schema.yaml`
(the 13 relationship types + `x-allowedTriples`). Enums under
`schema/v0.1/enums/`: `capabilities.yaml` (curated, ~31, churns via PRs),
`lifecycle-states.yaml`, `environments.yaml`. All served as static files.

13 relationship types: Access, Aggregation, AndJunction, Assignment,
Association, Composition, Flow, Influence, OrJunction, Realization, Serving,
Specialization, Triggering.

## Locked design decisions

- **Data source:** viewer consumes the manifest via a `?src=<url>` query param
  (default = our own `/data/v0.1/architecture.json`). It can consume *any*
  conformant manifest; we point our iframe at ours. This is a **view-model
  rewrite** — derive nodes/edges from ArchiMate elements/relations, drop the old
  `capability`/`edge-type`/`status`/`strength` taxonomy entirely.
- **Metadata-driven + completeness guard:** extend `generate.py` to emit
  `viewer/src/generated/vocab.ts` (kind/relation/capability/layer unions +
  labels). Presentation theme maps are typed `Record<Kind, …>` so `tsc` fails on
  any missing or stale entry. Runtime skew (data newer than build, e.g. a new
  capability id) → **loud placeholder + `console.error`**, never a silent
  generic default. Background: `tmp/metadata-driven-viewer.md`.
- **Colour:** by **ArchiMate layer**, hues from the standard
  (technology=green, application=blue/cyan, business=yellow, strategy=orange,
  cross-cutting=grey) but **re-saturated to fit the light theme/site**, not the
  canonical pastel-on-white originals. Starting accents (tune in Plan 1):
  technology `#5b8c5a`, application `#4f7cac`, business `#c9a227`,
  strategy `#c2703d`, cross-cutting `#7c7f86`.
- **Icons — keep the two-icon node:** kind glyph **left** (Lucide, one per
  ArchiMate kind), product image **right**. The right image is the element's
  `logo` if set, else a **generic capability logo/icon** for the capability it
  realizes, else nothing.
- **Logo attribute:** widen `logo` from the `SoftwareProduct`-stereotype-only
  free-form filename to a **common attribute on every kind**, validated against
  an **enum generated from `viewer/public/logos/`** (Plan 2). Lets hardware
  (Devices, Nodes) carry logos; build fails on a typo / missing file.
- **Views — hybrid:** each view = a declarative **predicate** over `{layers,
  kinds, producers, capabilities, lifecycle, environments}` + optional explicit
  **include/exclude** id lists + a **neighbour-expansion depth**. Views live as
  YAML in this repo and are **inlined into `architecture.json`** by the collector
  (one document for the viewer to fetch). **No `default:` flag** — list order is
  authoritative, the viewer opens `views[0]`. Ship all seven, Landscape first:
  Landscape, Delivery pipeline, Infrastructure & network, Application landscape,
  Identity & secrets, Data & storage, Home automation. Plus a final **Everything**
  view (no predicate, full filter machinery, still prd-defaulted) as the
  explore/escape hatch.
- **Environments (DTAP):** the merged model carries separate elements per env
  (e.g. `ss:keycloak-prd`). Default to **prd only** (and elements with no
  `environment`); an Environment filter group reveals dev/tst/uat. No
  node-merging in the viewer.
- **Filters:** within a group **OR**, across groups **AND**. No relation type
  selected → show all relations among visible nodes; relation types selected →
  restrict to those. Left rail follows the UDM topology-filter pattern
  (`tmp/udm-filter-panel.png`): scrollable group list, collapsible groups,
  per-group search + nested scroll + Select-All when a group has ≥8 options, a
  selected-summary row, and a fixed **Clear filters** footer. Collapsed state in
  `localStorage`, keyed by a hash of the `?src` URL.
- **Canvas:** keep the current ReactFlow + ELK layered layout as-is. Shell
  becomes two panels (left filter rail / canvas) with a **view tab strip** across
  the top of the canvas.

## Target layout (filter rail, from the UDM reference)

```
+----------------------------+  +-------------------------------------+
| Scrollable filter groups   |  |  [Landscape][Delivery][Infra]…[All] | <- view tabs
|                            |  +-------------------------------------+
|  Element types       ^     |  |                                     |
|   [ ] Node (3)             |  |                                     |
|   [ ] SystemSoftware (12)  |  |            ReactFlow canvas          |
|                            |  |            (ELK layered)            |
|  Producer            ^     |  |                                     |
|   +----------------------+ |  |                                     |
|   | search             | |  |                                     |
|   | Selected (2)       v | |  |                                     |
|   | [x] helm (40)      # | |  |                                     |
|   | [ ] ansible (9)    # | |  |                                     |
|   | Select All           | |  |                                     |
|   +----------------------+ |  |                                     |
+----------------------------+  |                                     |
| Clear filters              |  |                                     |
+----------------------------+  +-------------------------------------+
```
