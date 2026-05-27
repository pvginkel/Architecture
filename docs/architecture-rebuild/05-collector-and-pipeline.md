# 05 — Collector and pipeline

The collector is a Python script in Docker, invoked from the Architecture repo's Jenkinsfile. It pulls every registered producer's latest-successful-build `architecture.yaml` from Jenkins, validates each against the v0.1 schema, merges them, runs cross-producer checks, and writes the consolidated dataset that the validation service serves at a static URL.

The collector is **not** part of the validation service. The service validates (POST /api/validate) and publishes (static HTTP). Assembly happens in the build, where rebuild semantics, retry policy, and failure handling are easy to reason about.

The producer-side counterpart is [`04-producer-protocol.md`](./04-producer-protocol.md). The schema is [`../features/metaschema-design.md`](../features/metaschema-design.md). The service that serves the merged artifact is [`../features/validation-service.md`](../features/validation-service.md).

## Where the collector lives

`tooling/collect.py` in this repo. Python (Poetry), runs under the same `tooling/pyproject.toml` as `generate.py` and `validate.py`. Single-file Click CLI. Same image (`registry:5000/architecture-tooling:<tag>`) used by other Architecture-pipeline Python steps.

The Architecture repo's Jenkinsfile runs the collector inside the Docker image. No collector logic lives in the validation service container; the service consumes the collector's output.

## Inputs

- `pipeline-producers.yaml` in this repo: the registered producer list. Each entry: `id`, `profile`, `jenkins-job-url`. Adding a producer is a PR.
- For each producer, the latest-successful-build's `architecture.yaml` artifact (HTTP fetch via the Jenkins API, anonymous read where possible; token-auth otherwise).
- The vendored ArchiMate XSD + Archi matrix + `subset.yaml` + generated schemas (already present in this repo) — for re-validation.

## Outputs

- `dist/data/v0.1/architecture.yaml` — the merged dataset (YAML).
- `dist/data/v0.1/architecture.json` — canonical JSON form of the same dataset.
- `dist/data/v0.1/validation-report.json` — structured report of warnings, dangling references, alias-hint divergences, deprecated references, profile violations, and any cached-fallback notes.

These are baked into the validation-service container image at build time (the v2 service serves `/data/v0.1/architecture.yaml` and `/data/v0.1/validation-report.json` directly from disk). When the merged dataset changes, the container image is rebuilt and redeployed via the existing Jenkins → Kaniko → Helm flow.

## Pipeline (this repo's Jenkinsfile)

```
1. Checkout architecture repo.
2. Build / pull tooling Docker image.
3. poetry run python tooling/generate.py --check      # schemas up to date
4. poetry run python tooling/validate.py meta          # schemas valid
5. poetry run python tooling/collect.py                # fetches, validates, merges
6. Build validation service (Node).
7. Build viewer (Vite).
8. Build container image with service + viewer + dist/data/.
9. Push to registry; trigger Helm-side deploy.
10. Archive dist/data/validation-report.json as a Jenkins artifact.
```

Steps 3 and 4 fail the build immediately if the schema package is out of sync or invalid (a defense against generated-files drift). Step 5 is the substantive work.

### Triggers

- **On producer success**: each registered producer's Jenkins job, on successful build, triggers the Architecture repo's job downstream. Native Jenkins; no custom infra.
- **Scheduled**: nightly rebuild as a hedge against missed triggers and to surface staleness warnings.
- **On Architecture repo push**: any commit triggers a rebuild (schema change, collector change, viewer change, doc change — anything that changes container contents).
- **Manual**: button in Jenkins for ad-hoc reruns (debugging, schema preview).

Concurrent producer completions are coalesced by Jenkins's pending-build merging on the Architecture job. Not a v3 concern.

## Collector responsibilities (in order)

1. **Fetch** the latest-successful-build `architecture.yaml` from each registered producer. Concurrent fetches with a 60s per-fetch timeout. A failed fetch falls back to the cached artifact (see "Caching" below) and records a warning.
2. **Per-artifact validate** against `schema/v0.1/architecture.schema.yaml` (using the existing `validate.py` machinery). Schema-invalid producer artifacts are reported but **do not fail** the build — the report lists them and the merge proceeds without that producer's data. (Rationale: a single misbehaving producer shouldn't blackhole the entire merged dataset. If schema-invalid persists for a producer, that producer's own CI should already be failing — fix is upstream.)
3. **Reconcile enums.** Every `Capability` id and `«SoftwareProduct»` id referenced from any artifact must exist in the curated enum / catalog. Unknown references fail the build (a producer needs to PR the enum first).
4. **Profile enforcement.** Each producer's artifact may only contain element kinds permitted by its profile (per `04-producer-protocol.md` § Profile constraints). Profile violations fail the build.
5. **Merge.** Combine all element-kind arrays across artifacts. Detect duplicate UUIDs (a real conflict between producers; fail the build).
6. **Cross-reference resolution.** Every relation's `source` and `target` UUID must resolve to an element in the merged dataset. Dangling = build failure. Reference to a `deprecated` element = warning. Reference to a `removed` element = build failure.
7. **Alias-hint reconciliation.** Same UUID with different `aliasHint` strings across producers = warning, captured in the report. Owner's hint (matched by element's `producer` back-pointer to its owning artifact) is the one retained in the merged dataset.
8. **Triple-matrix check.** Every relation's `(source-kind, type, target-kind)` triple must be in the allowed-triples enumeration (already encoded as `x-allowedTriples` in `generated/relations.schema.yaml`). Violations fail the build.
9. **Rollup.** Compute Grouping memberships, Capability-realisation maps, and any derived view structures.
10. **Emit.** Write `dist/data/v0.1/architecture.yaml`, `.json`, and `validation-report.json`.

## Failure modes summary

| Condition | Behavior |
|---|---|
| Producer fetch failed | Warning; fall back to cached artifact. After 7 days of staleness, escalate to failure. |
| Per-artifact schema-invalid | Warning; that producer's data is dropped from the merge. Build continues. |
| Capability or `«SoftwareProduct»` reference not in catalog | Build fails. |
| Profile violation (kind not permitted for profile) | Build fails. |
| Duplicate UUID across producers | Build fails. |
| Dangling cross-producer UUID reference | Build fails. |
| Reference to a `removed` element | Build fails. |
| Reference to a `deprecated` element | Warning. |
| Alias-hint divergence (same UUID, different hints) | Warning. |
| Triple-matrix violation | Build fails. |
| Grouping references missing member | Build fails. |
| Grouping spans producers | Build fails (groupings are producer-local). |

The validation report is a first-class artifact of the build. The viewer exposes a "data quality" link surfacing it in the UI.

## Caching / fallback

`dist/cache/<producer-id>/<schema-version>/<commit>.yaml` is the last-known-good artifact per producer. If a fetch fails, the cache entry is used and a staleness warning is recorded. A successful fetch + validate refreshes the cache entry. Entries older than 30 days are pruned.

The cache makes the system robust to individual producer downtime. The merged dataset doesn't disappear because Ansible's Jenkins is rebooting.

## Implementation notes

- Python 3.13, Poetry, same dependency set as `generate.py` / `validate.py` plus `requests` (or `httpx`) for fetches.
- The collector's per-artifact validation reuses `validate.py`'s machinery rather than reinventing.
- `x-allowedTriples` is already embedded in `generated/relations.schema.yaml` — the collector reads it directly.
- Concurrent fetches use a small `ThreadPoolExecutor`; nothing fancy.
- All file paths in `dist/` are deterministic so the container image build is reproducible.

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
- **Should the collector publish a producer-readable index** (`/data/v0.1/index.yaml` enumerating every UUID with its owning producer and aliasHint)? Useful for producer authors looking up UUIDs without scanning the full merged dataset. Low-cost. Likely yes; finalise when the second producer comes online.
