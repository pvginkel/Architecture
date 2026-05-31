# Plan 4 — Curated views

**Read first:** [`00-overview.md`](00-overview.md) and the `project_viewer-rework`
auto-memory.

**Goal:** add **views** — curated, named scopings of the model — as the
up-front navigation. Views are authored as YAML in this repo, validated and
**inlined into `architecture.json`** by the collector, and surfaced as a **tab
strip across the top of the canvas**. The viewer opens the first view
(Landscape). A final **Everything** view is the explore-by-filters escape hatch.

**Prerequisites:** Plan 1 (model/vocab) and Plan 3 (filter groups + state — a
view sets a baseline into that state).

---

## View model (locked: hybrid predicate + overrides)

A view selects an element set by:

1. a **predicate** over existing dimensions — within a field OR, across fields
   AND;
2. optional explicit **include** / **exclude** id lists for sets no predicate
   cleanly expresses;
3. a **neighbour-expansion depth** — after the base set is chosen, pull in
   elements within N relation-hops (so a view can show a spine plus its immediate
   context).

Resolution algorithm (document this in the schema file and the viewer):

```
base   = elements matching predicate (AND across fields, OR within)
base   = (base ∪ include) − exclude
scoped = base ∪ { elements within neighbourDepth hops of base, following relations }
scoped = scoped filtered by environment (view.defaultEnvironment, default "prd";
         env-agnostic elements always pass)
edges  = relations among scoped (then narrowed by the user's relation-type filter)
```

No `default:` flag — **list order is authoritative**, Landscape first, the viewer
opens `views[0]`.

## Step 1 — View schema + the seven view files

- `views.schema.yaml` (repo root, alongside `pipeline-producers.schema.yaml`):
  one view = `{ id, label, description, icon, predicate?, include?, exclude?,
  neighbourDepth?, defaultEnvironment? }`. `icon` is a PascalCase lucide-react
  icon name rendered on the view tab. `predicate` fields:
  `layers?`, `kinds?`, `producers?`, `capabilities?`, `lifecycle?`,
  `environments?` (each an array of vocab values). `additionalProperties: false`.
- `views/` directory with one file per view, plus an ordering source. Two viable
  orderings: (a) an explicit `views/_order.yaml` listing ids; (b) numeric file
  prefixes (`01-landscape.yaml`…). Pick (a) — explicit and self-documenting.
- Author the seven (Landscape first), each a predicate + minimal overrides:

  | View | Sketch of selection |
  |---|---|
  | **Landscape** (opens) | `layers: [strategy, application]` + key SystemSoftware; capabilities + their realizers + the apps; hide interfaces/low-level services via `exclude` or by not selecting `applicationInterface`/`technologyInterface` kinds. `neighbourDepth: 1`. |
  | **Delivery pipeline** | the CI/CD chain — `capabilities: [cap:delivery]` realizers, or explicit `include` of GitHub/Jenkins/Kaniko/Registry/Helm/Ansible/Terraform ids; `neighbourDepth: 1`. |
  | **Infrastructure & network** | `layers: [technology]`, `kinds: [Device, Node, SystemSoftware]`; LAN topology. |
  | **Application landscape** | `kinds: [ApplicationComponent]` + their consumed services/capabilities + data stores; `neighbourDepth: 1`. |
  | **Identity & secrets** | `capabilities: [cap:iam, cap:secrets-management, cap:pki]` realizers + consumers; `neighbourDepth: 1`. |
  | **Data & storage** | storage SystemSoftware/TechnologyServices + `stores-data`/relevant relations; `neighbourDepth: 1`. |
  | **Home automation** | `producers`/`capabilities` for the home-automation slice + IoT Devices. |

  Tune predicates against the **real** merged dataset once the validation build
  has produced `/data/v0.1/architecture.json` — the sketches above name the
  intent, not final selectors. Prefer predicates; reach for `include`/`exclude`
  only where an attribute can't express the set.

- **Everything** view: not a file you have to over-specify — either author
  `views/everything.yaml` with an empty predicate (matches all) or synthesise it
  in the collector/viewer as the last entry. No predicate, no include/exclude;
  `defaultEnvironment: prd` still applies. It is the only view where the full
  filter machinery roams the whole model.

## Step 2 — Collector inlines + validates views

In `tooling/collect.py`:

- Add `--views` option (default `views`), and load + validate the view files
  against `views.schema.yaml` (reuse the `_arch` yaml/validate helpers).
- Add a cross-check phase (raise `CollectorError("views", …)` on any violation):
  - every `predicate.capabilities` id ∈ the capability enum;
  - every `predicate.producers` ∈ registered producers;
  - every `predicate.layers/kinds/lifecycle/environments` ∈ vocab;
  - every `include`/`exclude` id **resolves** in the merged set (use the existing
    `ResolutionIndex`). A view referencing a non-existent element is a hard
    failure — same fail-loud stance as dangling relation refs.
- In `assemble_merged_dataset` (`collect.py:709`), add a top-level
  `views: [ …in order… ]` key to the merged doc (after `derived`, or wherever
  reads cleanly). The viewer fetches one document; views ride along.
- Determinism: emit views in the authored order; keep `sort_keys=False` (already
  set in `emit_outputs`).

The Architecture repo is itself the pipeline host, so `views/` is read directly
by the collector — it is **not** a producer artifact and does not go through
`producer-artifacts/`.

Update `docs/architecture-rebuild/05-collector-and-pipeline.md` "Named views"
section to match what you build (it currently sketches `views/` as a v5 idea with
slightly different fields).

## Step 3 — Viewer: view tab strip + baseline wiring

- Read `manifest.views`. Render a **tab strip** across the top of the canvas
  region (above ReactFlow), one tab per view in order, Everything last.
- **Open `views[0]`** (Landscape) on load. Optional: honour `?view=<id>` to open
  a specific view (overrides the default); a malformed/unknown id falls back to
  `views[0]` with a `console.warn` (loud, non-fatal — this is user-supplied URL
  input, a boundary).
- Selecting a view computes its scoped element/edge set (resolution algorithm
  above) **and** seeds the Plan 3 filter state to the view's baseline (predicate →
  the matching filter groups, environment → its `defaultEnvironment`). The user's
  filter tweaks then refine *within* the view.
- **Clear filters** (Plan 3 footer) now resets to the **active view's baseline**,
  not empty.
- Switching views resets filter state to the new view's baseline.

## Step 4 — Parent bridge / URL state (optional polish)

- Emit the active view id in the `view-change` postMessage payload; accept a
  `set-view` that names a view id.
- Reflect the active view + filter state in a transient URL hash so a custom
  state is shareable (per doc 05). Optional; gate on time.

## Acceptance criteria

- `cd tooling && poetry run python collect.py …` inlines `views` into
  `architecture.json` in authored order; a view with a bogus `include` id or an
  unknown capability/producer **fails the build** with a clear message.
- Viewer shows the tab strip; **Landscape opens by default**; Everything is last.
- Each view scopes the canvas per its predicate + include/exclude + neighbour
  depth; prd-default holds; revealing dev/tst/uat works within a view.
- Clear filters returns to the active view's baseline; switching views re-seeds.
- `npm run build` passes; collector test fixtures updated if the merged-doc shape
  assertion now includes `views`.

## Suggested commits

1. `views.schema.yaml` + `views/` files (the seven + Everything + `_order.yaml`).
2. `collect.py`: load/validate/inline views + cross-checks; update fixtures.
3. viewer: view tab strip + baseline wiring + Clear-to-baseline.
4. (optional) parent-bridge view id + URL hash state.
5. doc 05 "Named views" section updated to the shipped model.
