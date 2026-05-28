# 05 — Collector and pipeline

The collector is a Python script that runs as a Docker build stage in the Architecture image. It reads each registered producer's YAML files (one or more per producer) from a build-context directory populated by the Jenkinsfile (via Jenkins's native `copyArtifacts` step with `flatten: true`), validates each file against the v0.1 schema, merges per producer, then merges across producers, runs cross-producer checks, and writes the consolidated dataset that the validation service serves at a static URL.

The collector is **not** part of the validation service. The service validates (POST /api/validate) and publishes (static HTTP). Assembly happens inside the image build, where rebuild semantics, retry policy, and failure handling are easy to reason about and the input set is captured in the build context.

The producer-side counterpart is [`04-producer-protocol.md`](./04-producer-protocol.md). The schema is [`../features/metaschema-design.md`](../features/metaschema-design.md). The service that serves the merged artifact is [`../features/validation-service.md`](../features/validation-service.md). The v3 work-item index is [`../features/collector-and-pipeline.md`](../features/collector-and-pipeline.md).

## Where the collector lives

`tooling/collect.py` in this repo. Python (Poetry), runs under the same `tooling/pyproject.toml` as `generate.py` and `validate.py`. Single-file Click CLI. The shared schema-load / registry-build / validator machinery is extracted from `validate.py` into a small internal module that both scripts import.

There is no separate `architecture-tooling:<tag>` registry image. The collector runs as a stage in the main `Dockerfile`, sandwiched between `check-schemas` and the final runtime stage. The Jenkinsfile copies producer artifacts into the build context before kaniko runs; the build does the rest.

## Inputs

- `pipeline-producers.yaml` in this repo: the registered producer list. Each entry: `id`, `profile`, the Jenkins job to copy from. Adding a producer is a PR. The Jenkinsfile reads this file (Groovy) to know which `copyArtifacts` calls to issue. The collector reads the same file to know which directories to expect.
- `producer-artifacts/<producer-id>/*.yaml` — populated by the Jenkinsfile via `copyArtifacts` (with `flatten: true`) from each registered producer's last-successful build. Lives in the workspace; included in the kaniko build context. A producer may publish one or more YAML files; filenames within a single producer must be distinct.
- The vendored ArchiMate XSD + Archi matrix + `subset.yaml` + generated schemas (already present in this repo) — for re-validation inside the build.

Jenkins's "last successful build" *is* the cache. No collector-side cache layer, no staleness window, no HTTP retry handling — Jenkins owns fetching.

## Outputs

- `dist/data/v0.1/architecture.yaml` — the merged dataset (YAML).
- `dist/data/v0.1/architecture.json` — canonical JSON form of the same dataset.
- `dist/data/v0.1/validation-report.json` — structured report of warnings, alias-hint divergences, deprecated references, and any other non-fatal observations.

These are produced inside the `run-collector` Docker stage and copied into the final runtime stage via `COPY --from=run-collector`. The v2 service serves `/data/v0.1/architecture.yaml`, `/data/v0.1/architecture.json`, and `/data/v0.1/validation-report.json` directly from disk.

## Pipeline (this repo's Jenkinsfile)

```
1. Checkout architecture repo.
2. Read pipeline-producers.yaml.
3. For each registered producer: copyArtifacts from <jenkins-job>, lastSuccessful,
     into producer-artifacts/<producer-id>/.
4. kaniko build of the multi-stage Dockerfile:
     - check-schemas stage: generate.py --check, validate.py meta.
     - build-viewer stage.
     - build-service stage.
     - run-collector stage: tooling/collect.py against producer-artifacts/,
       writing dist/data/v0.1/*.
     - final stage: COPY service + viewer + schema + USAGE.md + dist/data.
5. Push image to registry.
6. Archive dist/data/v0.1/validation-report.json as a Jenkins artifact
     (extracted from the built image via `docker create` + `docker cp`,
     or by re-running collect.py in a sidecar — TBD at implementation time).
7. Trigger Helm-side redeploy.
```

Schema-out-of-sync and schema-meta-invalid are caught early in the build (the existing `check-schemas` stage already runs `generate.py --check`). The collector stage is where all federation-level work happens.

### Triggers

- **On producer success**: each registered producer's Jenkins job, on successful build, triggers the Architecture repo's job downstream. Native Jenkins upstream-build trigger; no custom infra. The Jenkinsfile reads `pipeline-producers.yaml` and writes the `upstream()` trigger into the job's persisted properties — adding a producer to the registry auto-wires the dispatch path on the next run.
- **On Architecture repo push**: any commit triggers a rebuild (schema change, collector change, viewer change, doc change — anything that changes container contents).
- **Manual**: button in Jenkins for ad-hoc reruns (debugging, schema preview).

No scheduled rebuild. The earlier draft proposed a nightly cron "as a hedge against missed triggers and to surface staleness warnings" — with the locked decisions (no staleness window, deterministic outputs) the cron caught nothing the other three triggers don't already cover, so it's gone.

Concurrent producer completions are coalesced by Jenkins's pending-build merging on the Architecture job. Not a v3 concern.

## Collector responsibilities (in order)

1. **Discover.** Walk `producer-artifacts/`. Every `<producer-id>/*.yaml` (one or more) is a candidate input. Producers listed in `pipeline-producers.yaml` whose directory is missing or empty of YAML files fail the build (the Jenkinsfile should have copied at least one in; the collector refuses to silently merge a partial set). Stowaway directories (present in `producer-artifacts/`, not registered) also fail the build.
2. **Per-file validate** against `schema/v0.1/architecture.schema.yaml` (using the shared validator module). Cross-file producer-level checks then verify each file's envelope `producer:` matches the directory name, every file in a producer agrees on `schemaVersion`, and no id is declared in two files of the same producer. Per-producer files are merged into one virtual doc at this step. Any error fails the entire build.
3. **Reconcile the capability enum.** Every `Capability` id referenced from any artifact must exist in `schema/v0.1/enums/capabilities.yaml`. Unknown reference = build failure (a producer must PR the enum first).
4. **Synthesise provenance attribute.** For every declared element, stamp `producer: <bare-id>` onto the element using the envelope `producer:` key as the source. Producers must not emit `producer:` themselves (rejected by `additionalProperties: false` at per-artifact validation). Provenance lives as a filter on the merged dataset, not a graph edge — see v0.1.1 in `../features/metaschema-design.md`.
5. **Merge.** Combine all element-kind arrays across artifacts. Detect duplicate ids (composite or bare kebab) — a real ownership conflict, fail the build with both producers reported.
6. **Cross-reference resolution.** A single `ResolutionIndex` over the merged set offers three lookups: UUID (the UUID portion of any composite id), full string (catalogue / curated kebab ids), and per-producer hint (instance-kind hint-only refs, internal-only). Every relation's `source` and `target` id must resolve. Dangling = build failure. Reference to a `deprecated` element = warning. Reference to a `removed` element = build failure.
7. **Hint divergence.** For every composite reference, compare the hint portion against the owner's declared hint. Same UUID, different hints = warning, captured in the report. The owner's spelling lands in the merged element's id; uuid-only and matching-hint references produce no entry.
8. **Triple-matrix check.** Every relation's `(source-kind, type, target-kind)` triple must be in the allowed-triples enumeration (already encoded as `x-allowedTriples` in `generated/relations.schema.yaml`). JSON Schema doesn't enforce the matrix on its own — the collector enforces it for both in-artifact and cross-artifact relations.
9. **Grouping checks.** Groupings are producer-local. A Grouping that aggregates members from a different producer fails the build. A Grouping with zero Aggregation relations sourced from it (empty Grouping) also fails the build — dead data.
10. **Rollup.** Compute Grouping memberships and Capability-realisation maps; sort and de-duplicate so reruns are byte-identical.
11. **Emit.** Write `dist/data/v0.1/architecture.yaml`, `architecture.json`, and `validation-report.json` with deterministic key ordering so the image build is reproducible.

## Failure modes summary

| Condition | Behavior |
|---|---|
| Producer listed in `pipeline-producers.yaml` but no artifact present | Build fails. |
| Per-artifact schema-invalid | Build fails. |
| Capability reference not in enum | Build fails. |
| Duplicate id across producers | Build fails. |
| Dangling cross-producer id reference | Build fails. |
| Reference to a `removed` element | Build fails. |
| Reference to a `deprecated` element | Warning. |
| Hint divergence (composite refs with differing hint portion) | Warning. |
| Triple-matrix violation (in-artifact or cross-artifact) | Build fails. |
| Grouping has no Aggregation members declared | Build fails. |
| Grouping spans producers | Build fails (groupings are producer-local). |
| Hint-only cross-producer reference | Build fails (use UUID for cross-producer refs). |

The validation report is a first-class artifact of the build. The viewer eventually exposes a "data quality" link surfacing it in the UI.

Producer-side fetch failures (e.g. a producer's Jenkins down) are not a collector failure mode — the Jenkinsfile's `copyArtifacts` either succeeds against the last-successful build (whatever its age) or the upstream job has never produced a successful build at all, in which case the producer hasn't onboarded yet and shouldn't be in `pipeline-producers.yaml`.

## Implementation notes

- Python 3.13, Poetry. No new top-level dependencies expected — `pyyaml`, `jsonschema`, `click`, `referencing` already present. No `requests` / `httpx` because there are no HTTP calls.
- The collector reuses the per-artifact validator via the shared module described under "Where the collector lives."
- `x-allowedTriples` is already embedded in `generated/relations.schema.yaml` — the collector reads it directly.
- All file paths in `dist/` are deterministic so the container image build is reproducible.
- The `run-collector` Dockerfile stage installs the same Poetry environment as the `check-schemas` stage; consider sharing layers if cache hit rate matters.

## Named views

Saved filter / zoom configurations, committed to this repo as YAML under `views/`:

```
views/
├── portfolio.yaml         # the recruiter-facing default view
├── data-plane.yaml
├── identity-flows.yaml
└── delivery.yaml
```

Each defines initial zoom/pan/centre, active filters (kinds shown, layers shown, lifecycle states shown), pinned UUIDs, and a one-line description for the view picker.

URL state: `architecture.webathome.org/?view=portfolio` loads a named view. Filter changes update a transient URL hash; users can copy and share custom states.

The viewer ships with a view picker UI. The portfolio view is the default route.

Named-view authoring is v5 work (after the viewer is repointed at the merged dataset).

## Performance considerations

At full federation, the merged dataset is maybe a few thousand elements. Python merge + cross-checks are sub-second on modest hardware. The viewer is the only piece where performance is non-trivial (ReactFlow with 1000+ nodes), and that's auto-layout + aggressive filtering at the data layer — separate from collector work.

## Open questions

- **Should named-view authoring be lifted earlier than v5?** If the merged dataset is large enough mid-bootstrap that filter presets help, yes. Defer the decision until we have real Ansible + Helm data flowing.
- **Should the collector publish a producer-readable index** (`/data/v0.1/index.yaml` enumerating every id with its owning producer and aliasHint)? Useful for producer authors looking up UUIDs without scanning the full merged dataset. Low-cost. Likely yes; finalise when the second producer comes online.
- ~~**How does the validation report get out of the image** for Jenkins archival?~~ **Resolved (v3 #13).** The Jenkinsfile runs the collector twice: once Jenkins-side in a Python sidecar (output archived via `archiveArtifacts`), once inside the `run-collector` Dockerfile stage (baked into the image at `/data/v0.1/`). Same inputs produce byte-identical outputs by the collector's determinism guarantee, so the archived report matches what the running container serves.
