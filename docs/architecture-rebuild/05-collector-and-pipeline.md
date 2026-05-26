# 05 — Collector and pipeline (v2/v3)

The collector is the piece of software in the architecture repo that pulls every producer's artifact, validates and merges them, resolves cross-producer references, and emits the final dataset the viewer consumes. The Jenkins pipeline is the orchestration around it.

These are bundled in one plan because the collector's behavior dictates the pipeline shape: what triggers rebuilds, what fails the build, what the output artifact looks like.

## Collector responsibilities

In order of execution:

1. **Fetch** the latest successful build's `architecture.json` from each registered producer.
2. **Validate** each artifact independently against the schema for its profile (re-running what the producer already ran, as a defense-in-depth check).
3. **Reconcile enums.** Every `cap:*` and `prod:*` reference must exist in the architecture repo's enum YAML files. Unknown enum values are a failure.
4. **Merge.** Combine all components, edges, and groups across artifacts into a single dataset. Detect GUID collisions.
5. **Resolve cross-references.** Every edge endpoint must be either a GUID present in the merged components list or a known capability/product. Dangling = failure (per user requirement). Reference to a `deprecated` component = warning. Reference to a `removed` component = failure.
6. **Rollup.** Compute group memberships, capability-realization maps, and any derived structures the viewer uses for filtering. Render-only — does not change the canonical data.
7. **Emit.** Produce `dist/architecture.json` (the canonical merged dataset), `dist/index/<profile>.json` (one per producer, listing every component's GUID + label for cross-producer GUID discovery), and `dist/validation-report.json` (warnings, dangling refs, deprecated refs).
8. **Build the viewer.** Vite build consumes `dist/architecture.json` and produces static HTML/JS/CSS.
9. **Package the container.** nginx serving the viewer + the JSON datasets + the schema versions at stable URLs.

## Failure modes

| Condition | Behavior |
|---|---|
| Producer artifact missing (build never produced one, or producer repo is offline) | Warning; build continues with last-known artifact for that producer (cached). After 7 days of staleness, escalate to failure. |
| Producer artifact present but schema-invalid | Build fails. Should have been caught upstream; if we're seeing it here, the upstream validator is misconfigured. |
| Capability or product reference not in enum | Build fails. Producer must PR the enum first. |
| Dangling cross-producer GUID reference | Build fails. User-required. |
| Reference to `removed` component | Build fails. Producers must remove references before marking a component `removed`. |
| Reference to `deprecated` component | Warning, counted in report. Render with deprecated styling. |
| GUID collision between producers | Build fails. Indicates a serious bug — GUIDs are unique by construction. |
| Group references a non-existent group | Build fails. |
| Component declares a group from another producer | Build fails (groups don't cross producers; `02-metaschema.md`). |

The validation report is a first-class artifact of the build. Surface it in the viewer (a small "system health" badge that opens a panel listing warnings and deprecated references). Recruiters reading the diagram seeing this is a positive signal.

## Cached / fallback behavior

The collector keeps a `cache/` directory of the last-known-good artifact per producer, indexed by producer name + schema version + git commit. If fetching fresh fails, the cached version is used and a warning is recorded.

Cache invalidation: a successful fetch + validate pass updates the cache entry for that producer. Old entries are pruned after 30 days.

This is what makes the system robust to individual producer downtime. The diagram doesn't disappear because Ansible's Jenkins is rebooting.

## Merge logic specifics

### Capabilities and products

Definitions come from the architecture repo's enum YAML. Producers reference; they don't define. The collector verifies references and is otherwise a passthrough.

### Components

Each producer contributes some. Union them. GUID collisions are an error. If two producers both want to claim the same logical component — for instance, an app declares "the Postgres I use" with a different GUID than HelmCharts assigned — that's the producer profile bug: apps reference, they don't redeclare.

### Edges

Union, with deduplication on `(source, target, type)`. Two producers describing the same edge with the same type is allowed (no-op); with different attributes is a collision (the collector picks the higher-criticality one and records a warning).

### Groups

Each group lives entirely within one producer. Union with no merging needed.

## Cross-reference resolution and the published index

Apps reference Keycloak by its GUID. They get that GUID from somewhere. Two options:

- **Option A: published index.** The collector publishes per-profile indexes at stable URLs. App authors look up the GUID once, paste it into their artifact source.
- **Option B: registry API.** A small API that resolves slugs (`cluster-services:keycloak-prd`) to GUIDs at producer build time.

Option B is overengineering for this scale. Option A is fine:

```
https://architecture.webathome.org/index/cluster-services.json
https://architecture.webathome.org/index/infra-physical.json
```

Each entry has `id` (GUID), `slug` (producer-assigned, may not be unique long-term), `label`, `lifecycle`, `summary`. App authors hand-pick GUIDs from this index. The architecture repo's README documents the workflow.

To make this slightly less error-prone, the validator can accept a `--resolve-index <url>` flag and validate that referenced GUIDs exist in the published index at build time. Optional; warns rather than fails locally.

## Named views

Saved filter / zoom configurations, committed to the architecture repo as YAML:

```
views/
├── portfolio.yaml         # the recruiter-facing default view
├── data-plane.yaml
├── identity-flows.yaml
└── delivery.yaml
```

Each defines:
- Initial zoom / pan / center.
- Active filters (capabilities shown, edge types shown, lifecycle states shown).
- Optional pinned components (always shown, override filters).
- Title and one-line description displayed in a view picker.

URL state: `architecture.webathome.org/?view=portfolio` loads the named view. Filter changes update a transient URL hash; users can copy and share custom states.

The viewer ships with a view picker UI. The portfolio view is the default route.

## Jenkins pipeline shape

Architecture repo's `Jenkinsfile` runs:

1. **Checkout** architecture repo.
2. **Build the validator and collector** (if their source has changed).
3. **Fetch all producer artifacts** via Jenkins API. Concurrent.
4. **Run the collector.** Outputs `dist/` and `dist/validation-report.json`.
5. **Fail the build** on collector exit != 0.
6. **Build the viewer** (Vite).
7. **Build the container image** (nginx + dist).
8. **Push to registry** (existing flow).
9. **Trigger downstream deploy** (existing Ansible / K8s flow).
10. **Archive `dist/validation-report.json`** as a Jenkins artifact for postmortem on warnings.

### Triggers

- **On producer success**: each producer's Jenkins job, on successful build, triggers the architecture repo's job downstream. Jenkins-native, no custom infra.
- **Scheduled**: nightly rebuild, as a hedge against missed triggers and to surface cache staleness warnings.
- **Manual**: button in Jenkins, for trying schema changes.
- **On architecture repo push**: any commit to the architecture repo (schema change, view edit, viewer code change) triggers a rebuild.

### Concurrent producer triggers

If three producers finish within a minute of each other, they trigger three sequential collector runs. Jenkins's coalescing of pending builds on the same job handles this fine; if the queue depth becomes a problem, configure the architecture job as non-concurrent with a coalescing wait. Not a v2 concern.

## Performance considerations (not v2-critical, noted for later)

At full federation the collector handles maybe a thousand components. JSON parsing, GUID-keyed maps, edge resolution — all sub-second on modest hardware. The viewer is the only piece where performance is non-trivial: ReactFlow with 1000+ nodes wants auto-layout caching and aggressive filtering at the data layer.

Caching strategy if needed:
- Pre-computed layouts per named view, written to disk by the collector and shipped with the container.
- The viewer loads the layout for the active view rather than computing it client-side.

Worth implementing once the diagram is actually at scale, not before.

## Open questions

- **Named views: committed YAML vs URL state only?** Committed YAML is concrete decision above. Transient URL state for ad-hoc filtering. Both coexist. If maintenance friction emerges, lean on URL state.
- **Should the validation report surface in the embedded iframe on webathome.org?** Probably yes, behind a small "data quality" link in the viewer chrome. Visible from the iframe, helpful for credibility, not in the recruiter's face.
- **postMessage events for filter changes?** Wired up in `01-repo-extraction.md` already; no consumer in v0. Possible v3 use: site can deep-link to filter states with `set-view` messages. Worth nothing more than reserving the message names now.
