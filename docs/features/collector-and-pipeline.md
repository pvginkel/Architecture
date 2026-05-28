# Collector + pipeline (v3)

The runtime side of phase v3 of the Architecture rebuild. Delivers `tooling/collect.py` and the Architecture-repo Jenkinsfile that drives it; ships the consolidated `dist/data/v0.1/` payload inside the validation-service container.

Design documents (the "what and why"):

- [`../architecture-rebuild/04-producer-protocol.md`](../architecture-rebuild/04-producer-protocol.md) — how a repo becomes a producer.
- [`../architecture-rebuild/05-collector-and-pipeline.md`](../architecture-rebuild/05-collector-and-pipeline.md) — collector responsibilities and pipeline shape.

This doc is the **execution plan**: ordered work items with exit criteria, in the same shape as [`validation-service.md`](./validation-service.md).

## Decisions locked

- **Jenkins owns fetching.** The Groovy Jenkinsfile uses `copyArtifacts` (with `flatten: true`) against each registered producer's last-successful build, populating `producer-artifacts/<producer-id>/*.yaml` in the workspace. Each producer may publish one or more YAML files. No HTTP client, no auth handling, no cache layer on the Python side.
- **Jenkins's last-successful-build is the cache.** No staleness window, no fallback file system, no 7-day rule. If a producer's build is months stale, that's what gets merged.
- **Fail fast, fail loud.** Any per-artifact schema error, dangling reference, unknown capability id, duplicate id, removed-element reference, cross-producer triple violation, missing-grouping-member, or cross-producer grouping fails the entire pipeline. No drop-and-continue paths. A partial merged dataset never ships.
- **No machine-enforced profile constraints.** The producer-profile field is descriptive metadata for diagnostics and reporting; the collector does not reject artifacts on a per-kind allow-list. Ownership patterns live in `04-producer-protocol.md` as guidance for review-time judgment.
- **SoftwareProduct catalog entries are owner-emitted.** No central catalog file in this repo. The producer that publishes the upstream product publishes its `«SoftwareProduct»` entry alongside its instances; ownership tracks where the upstream lives. Cross-producer references resolve through the same dangling-reference machinery as UUIDs.
- **Collector runs as a Dockerfile stage.** No separate `architecture-tooling:<tag>` registry image. The existing multi-stage build gains a `run-collector` stage between `check-schemas` and the final runtime; the final stage `COPY --from=run-collector`s the merged `dist/data/`.
- **Shared validator module.** The schema-load / registry-build / per-artifact validate machinery is extracted from `tooling/validate.py` into a small internal module that both `validate.py` and `collect.py` import.

## Work items

### 1. Shared validation module

Extract the schema-load / registry-build / per-artifact validate machinery from `tooling/validate.py` into an internal module (`tooling/_arch/` or similar) that both `validate.py` and `collect.py` can import. No behaviour change in `validate.py`.

**Exit criteria:**

- [x] `poetry run python tooling/validate.py meta` behaves identically to before.
- [x] `poetry run python tooling/validate.py <artifact>` behaves identically to before.
- [x] Module exposes at minimum: `load_master_schema()`, `build_registry()`, `validate_doc(doc) -> list[error]`, `load_allowed_triples()`, `load_capability_enum()`.
- [x] `collect.py` (later items) uses the module without re-implementing parsing.

### 2. Producer registry — `pipeline-producers.yaml`

The list of registered producers, consumed by both the Jenkinsfile (for `copyArtifacts` calls) and the collector (for "must be present" checks). Seed file at repo root with `producers: []` — v3 ships with no producers yet.

Entry shape (proposed):

```yaml
producers:
  - id: ansible
    profile: infra-physical
    jenkinsJob: ansible/master
  - id: helmcharts
    profile: cluster-services
    jenkinsJob: HelmCharts/master
```

JSON-schema-validated at collector startup; the schema lives next to the file.

**Exit criteria:**

- [x] `pipeline-producers.yaml` committed at repo root with `producers: []`.
- [x] JSON schema for the file (inline or sibling) committed; entries that don't match fail collector startup.
- [x] Collector reads the file and treats it as authoritative for "which producers must be present in `producer-artifacts/`".

### 3. Per-artifact validation pass

`collect.py` walks `producer-artifacts/` and runs the shared validator on every `<producer-id>/*.yaml` (one or more per producer). Cross-file checks within a producer then verify the envelope `producer:` matches the directory name, all files agree on `schemaVersion`, and no id is declared in two files of the same producer. The files of one producer are merged into a single virtual doc at that point. Any error fails the entire run. A producer listed in `pipeline-producers.yaml` but absent (or empty of YAML) is itself a fatal error.

**Exit criteria:**

- [x] Per-artifact validation error fails the run with a clear message naming the producer and the JSON pointer.
- [x] Missing-producer-artifact fails the run.
- [x] Extra directories in `producer-artifacts/` not listed in `pipeline-producers.yaml` fail the run (no stowaway producers).

### 4. Capability-enum reconciliation

Every `Capability` id referenced from any merged element must exist in `schema/v0.1/enums/capabilities.yaml`. Unknown reference fails the run with the offending producer + reference path.

**Exit criteria:**

- [x] Unknown capability id fails the run.
- [x] Known capability id passes.
- [x] Test fixture covers both cases.

### 5. Merge + duplicate-id detection

Combine all element-kind arrays across artifacts. Detect two producers emitting the same id (UUID *or* kebab-case) — fail the run with both producer ids reported. The same machinery covers SoftwareProduct id collisions and UUID collisions.

**Exit criteria:**

- [x] Merged dataset is the union of valid producers' arrays.
- [x] Duplicate id across producers fails the run.
- [x] *(v0.1.1)* The `producer` attribute on individual elements is
      collector-synthesised, not producer-emitted. The collector stamps
      `producer: <bare-id>` onto every merged element from the envelope
      `producer:` key (which is now a bare kebab token matching the
      `pipeline-producers.yaml` entry). The earlier «Producer» Artifact
      + synthesised Association edge model was dropped; see
      `../architecture-rebuild/00-roadmap.md` § v0.1.1.

### 6. Cross-producer reference resolution

Every relation's `source` and `target` id must resolve to an element in the merged dataset. Dangling fails the run. Reference to a `removed` element fails the run. Reference to a `deprecated` element produces a warning in the report.

**Exit criteria:**

- [x] Dangling reference fails the run with the offending relation pointer.
- [x] `removed`-target reference fails the run.
- [x] `deprecated`-target reference is captured as a warning in the report; run succeeds.
- [x] All three id forms (composite `<kind>:<hint>,<uuid>`, uuid-only,
      hint-only) and bare-kebab catalog/curated refs flow through the
      same `ResolutionIndex.resolve()` lookup. Hint-only refs only
      resolve within the relation's own producer; cross-producer
      hint-only refs surface as dangling with a message pointing the
      author at the UUID.

### 7. Alias-hint reconciliation

*(Implementation deviation)* No `aliasHint` field was added. The hint
rides in the id itself: instance-kind declarations are composite
(`<kind>:<hint>,<uuid4>`), and references may carry the hint portion
alongside the UUID. The collector compares the hint portion of every
composite reference against the owner's declared hint; differing
spellings of the same UUID are captured as divergences in the report.

**Exit criteria:**

- [x] Divergent hints captured per-id in the report, with all observed hints listed.
- [x] Owner-retained hint (the declaring artifact's spelling) is what
      lands in the merged dataset's element id.
- [x] Convergent hints (composite reference matches the owner's hint)
      produce no entry. Uuid-only references also produce no entry.

### 8. Cross-producer triple-matrix check

Every relation's `(source-kind, type, target-kind)` triple must be in `x-allowedTriples` (already in `generated/relations.schema.yaml`). Per-artifact validation already catches in-artifact violations; this is the cross-producer pass where source and target live in different artifacts.

**Exit criteria:**

- [x] Cross-producer triple violation fails the run.
- [x] Triple-matrix data loaded once via the shared module from item 1.

### 9. Grouping checks + rollup

Groupings are producer-local. A Grouping that aggregates members owned by a different producer fails the run. Missing Grouping members fail the run. Compute Grouping memberships and Capability-realisation maps as derived structures in the output.

**Exit criteria:**

- [x] Cross-producer Grouping fails the run.
- [x] Missing Grouping member fails the run.
- [x] Rolled-up structures present in `architecture.json`.

### 10. Emit `dist/data/v0.1/`

Write `architecture.yaml`, `architecture.json`, `validation-report.json` with deterministic key ordering. Re-running with identical inputs produces byte-identical outputs.

**Exit criteria:**

- [x] All three files written.
- [x] Re-run with identical inputs produces byte-identical outputs (sha256 match).
- [x] `validation-report.json` shape locked: top-level `summary`, `warnings[]`, `divergences[]` at minimum. Errors don't appear here because errors fail the run before emit.

### 11. Test fixtures + local end-to-end run

Fixture set under `tooling/tests/fixtures/`: two synthetic producer artifacts (one `infra-physical`-shaped, one `cluster-services`-shaped that references the first), plus a fixture `pipeline-producers.yaml`. Driver runs the collector against the fixtures and asserts the expected `dist/data/` shape.

**Exit criteria:**

- [x] `poetry run python tooling/collect.py --producers tests/fixtures/pipeline-producers.yaml --in tests/fixtures/producer-artifacts --out tmp/dist` succeeds on the happy-path fixture.
- [x] One fixture per failure mode (per-artifact invalid, missing producer artifact, unknown capability, duplicate id, dangling ref, removed-target ref, cross-producer triple violation, cross-producer Grouping, missing Grouping member) is driven by a single test runner; each asserts the expected exit code and error key.
- [x] Golden `architecture.yaml` / `architecture.json` / `validation-report.json` for the happy-path fixture committed.

### 12. Dockerfile: add `run-collector` stage

New stage in the multi-stage build, after `check-schemas` and before the final runtime stage. Reuses the schema-validated Poetry environment to run `tooling/collect.py` against `producer-artifacts/` copied in from the build context. Final stage uses `COPY --from=run-collector /work/dist/data ./data`, replacing the current `RUN mkdir -p ./data/v0.1` placeholder.

`.dockerignore` excludes `producer-artifacts/` from non-pipeline local builds so a developer running `docker build .` doesn't accidentally bundle local test fixtures into the production image (the pipeline opts in explicitly).

**Exit criteria:**

- [x] Stage builds successfully when `producer-artifacts/` is empty (v3 launch state).
- [x] Stage fails clearly when `producer-artifacts/` is missing entirely.
- [x] Stage fails clearly on any collector error (per-artifact invalid, dangling ref, etc.).
- [x] Built image serves `/data/v0.1/architecture.yaml`, `architecture.json`, `validation-report.json` (validation service already routes these).
- [x] `.dockerignore` excludes `producer-artifacts/` by default.
- [x] The `RUN mkdir -p ./data/v0.1` placeholder is gone.

### 13. Jenkinsfile rewrite

Replace the current nginx-era Jenkinsfile with the v3 pipeline:

```
1. Checkout.
2. Read pipeline-producers.yaml (Groovy YAML parser).
3. For each registered producer: copyArtifacts from <jenkinsJob>, lastSuccessful,
     into producer-artifacts/<producer-id>/.
4. kaniko build of the multi-stage Dockerfile.
5. Archive dist/data/v0.1/validation-report.json as a Jenkins artifact.
6. Trigger Helm-side redeploy.
```

Triggers per `05-collector-and-pipeline.md` §Triggers (producer upstream-builds, nightly cron, push to Architecture repo, manual).

**Exit criteria:**

- [x] All steps run green on an empty `pipeline-producers.yaml`.
- [x] `validation-report.json` archived as a Jenkins artifact (extraction-from-image approach decided and implemented; see `05` open question).
- [x] At least one producer-success upstream trigger wired to validate the dispatch path (a throwaway downstream-trigger from a known job is acceptable for v3 verification; real producer wiring is v4).
- [x] Helm-deploy step preserved.

### 14. Documentation pass

- [x] `00-roadmap.md` v3 entry updated when items 1–13 land; status flipped to **done**.
- [x] `USAGE.md` — short subsection on the merged-dataset endpoints (`/data/v0.1/*`) and the validation-report URL.
- [x] Any deviations from `04` / `05` introduced at implementation time backfilled into those docs.

## Exit criteria for the phase

- [x] `collect.py` runs end-to-end against fixtures and produces the three `dist/data/` files.
- [x] Dockerfile builds the container with the real `data/` payload from the `run-collector` stage.
- [x] Jenkinsfile runs the full pipeline on an empty producer list and produces a deployable image.
- [x] All cross-check failure modes verified by fixture (per-artifact invalid, missing artifact, unknown capability, duplicate id, dangling ref, removed-target ref, cross-producer triple, cross-producer Grouping, missing Grouping member).
- [x] Documentation updated.
