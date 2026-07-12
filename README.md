# Architecture

A federated **Architecture-as-Code** system for [webathome.org](https://webathome.org)
and the homelab estate behind it. Every repo that owns a slice of the estate
(Ansible, HelmCharts, DockerImages, the app repos, …) emits an `architecture.yaml`
describing its elements in an ArchiMate-derived schema. A pipeline collects those
artifacts, merges them into one dataset, and a data-driven viewer renders the
whole estate as a single filterable diagram.

The viewer is served as a container at
[`architecture.webathome.org/viewer/`](https://architecture.webathome.org/viewer/)
and iframe-embedded back into webathome.org. The same container is the runtime
validation service producers call from CI.

## How it works

```
producer repos                    this repo (Architecture)
──────────────                    ────────────────────────
Ansible ─┐                        ┌─ schema/v0.1/   metaschema (ArchiMate subset)
Helm    ─┤  emit                  ├─ tooling/       generate · validate · collect
apps    ─┤  architecture.yaml     ├─ service/       validation API + static host
…        │  per build             ├─ viewer/        ReactFlow + ELK SPA
         │                        └─ views/         curated view definitions
         │  CI calls
         └─► POST /api/validate ──► fail build on schema / triple-matrix error
                                              │
                Jenkins pipeline (this repo) ─┘
                  copyArtifacts each producer's last-successful architecture.yaml
                  → collect.py merges + cross-checks → dist/data/v0.1/*
                  → kaniko build → deploy
                                              │
                  viewer fetches /data/v0.1/architecture.json ─► one diagram
```

Provenance is a **filter, not a graph edge**: the collector stamps a
`producer:` attribute onto every merged element rather than drawing
repo→element relations. Cross-producer references are by composite id
(`<kind>:<hint>,<uuid4>`); the owner mints the UUID, everyone else references
it, and the collector warns when the friendly hint diverges from the owner's.

## Layout

```
schema/v0.1/   # the metaschema
  subset.yaml          ArchiMate-3.2 subset: 11 element kinds + the allowed relation triples
  archimate/           vendored ArchiMate XSD + Archi relationship matrix (source of truth)
  generated/           per-kind JSON Schemas + relations.schema.yaml (built by generate.py)
  enums/               capabilities · lifecycle-states · environments
  examples/            golden valid-/invalid- artifacts
tooling/       # Python (Poetry)
  generate.py          subset.yaml + XSD → generated schemas, viewer vocab.ts, LOGO_FILES map
  validate.py          local validation CLI (incl. `meta` self-check)
  collect.py           federation collector: merge · cross-check · derive · inline views
  _arch.py             shared validator used by both validate.py and collect.py
  tests/               fixture-driven end-to-end collector tests (run_fixtures.py)
service/       # Node + Express (TypeScript), vitest
  src/                 routes: validate, static, usage, metrics, csp; schema loader; error-translate
viewer/        # React + ReactFlow + ELK SPA (Vite, TypeScript)
  src/                 model (manifest → graph), theme, filter rail, views, parent-bridge
  src/generated/       vocab.ts + LOGO_FILES — emitted by generate.py, typecheck-enforced
  public/logos/        product logos served at /viewer/logos/
views/         # curated view definitions (YAML) inlined into the dataset by the collector
docs/
  architecture/        the `architecture` self-producer's own artifacts (this repo's elements)
  backfill/            one-off onboarding harness that seeded producer artifacts
  todo.md              open deferred decisions
pipeline-producers.yaml  # registry: which repos are producers, and their Jenkins jobs
Dockerfile     # check-schemas → build-viewer → build-service → run-collector → node runtime
Jenkinsfile    # homelab Jenkins + Kaniko pipeline (collect → build → deploy)
USAGE.md       # producer-facing integration docs; rendered at the container root
```

## The metaschema

`schema/v0.1/subset.yaml` declares a curated subset of ArchiMate 3.2.
`tooling/generate.py` reads it together with the vendored XSD and relationship
matrix and emits per-kind JSON Schemas plus `relations.schema.yaml` (the 13
relationship types and the `x-allowedTriples` source/target matrix). Layer is a
property of an element's **kind**, not the element:

| Layer | Kinds |
|---|---|
| technology | Node, Device, SystemSoftware, TechnologyService, TechnologyInterface |
| application | ApplicationComponent, ApplicationService, ApplicationInterface |
| strategy | Capability |
| business | BusinessService |
| cross-cutting | Grouping |

Every element carries `id`, `label`, `summary`, `introduced`, `lifecycle`
(`active`/`deprecated`/`removed`), and the collector-stamped `producer`. Per-kind
attributes add `environment` (DTAP), `cluster`, `stereotype`, `logo`, `homepage`,
`sourceRepository`, and free-form `stats`. The full envelope and the producer
contract are in [`USAGE.md`](./USAGE.md).

Schema vocabulary changes (a new capability, kind, attribute, or relation triple)
are a PR against `schema/v0.1/`; the generator rebuilds everything downstream. See
USAGE.md § *Schema-change requests*.

## The pipeline

`pipeline-producers.yaml` is the registry. For each entry the Jenkinsfile either
`copyArtifacts` the producer's last-successful `architecture.yaml` from its Jenkins
job, or — for the `architecture` **self-producer**, which has no `jenkinsJob` —
copies this repo's own artifacts from `docs/architecture/`. The collector
(`tooling/collect.py`) then:

1. validates each artifact against the schema + triple matrix,
2. merges them, cross-checking every cross-producer reference resolves,
3. normalizes relation endpoints to canonical ids and projects instance-level
   relations onto their definitions,
4. derives the `groupings` and `capabilityRealizations` maps,
5. inlines the `views/` definitions (in `_order.yaml` order, Everything appended last),
6. emits `dist/data/v0.1/architecture.{json,yaml}` + `validation-report.json`.

Every step is **fail-fast** — a bad reference or an unknown capability fails the
build; nothing is dropped-and-continued. The merged files are baked into the image
and served as static HTTP by the service.

## The viewer

A view-model rewrite over the merged manifest — no hand-maintained taxonomy. It
fetches `/data/v0.1/architecture.json` (overridable via `?src=<url>`; it can render
any conformant manifest) and derives nodes and edges directly from ArchiMate
elements and relations.

- **Colour by ArchiMate layer**, re-saturated for the light/dark site theme.
- **Two-icon nodes:** a Lucide kind glyph on the left, the element's product `logo`
  (or a capability fallback) on the right. Theme maps are `Record<Kind, …>`, so a
  missing entry fails `tsc`; runtime data skew renders a loud placeholder + a
  `console.error`, never a silent default.
- **Filter rail:** five groups (element type, producer, capability, lifecycle,
  environment). Within a group OR, across groups AND. Large groups get search +
  Select-All; collapse state persists in `localStorage` keyed by the `?src` hash.
- **Views:** a tab strip across the canvas. Each view is a declarative predicate
  (`{layers, kinds, producers, capabilities, lifecycle, environments, releases}`)
  plus optional include/exclude id lists and a neighbour-expansion depth. Landscape
  opens by default; Everything (full filter machinery, no predicate) is last.
- **DTAP:** the model carries separate elements per environment; the viewer defaults
  to **prd** (and elements with no environment), and the Environment filter reveals
  dev/tst/uat.

The vocab the viewer types against (`viewer/src/generated/vocab.ts`, `LOGO_FILES`)
is generated by `tooling/generate.py`, so the build breaks if the data model and the
viewer drift apart.

### Iframe contract

The viewer is built to live in an iframe on webathome.org. It speaks a small
`postMessage` protocol (`viewer/src/parent-bridge.ts`):

- Outbound: `{ type: "ready" }` on mount, `{ type: "view-change", view }` on filter changes.
- Inbound: `{ type: "set-view", view }` to deep-link into a named filter state.

Origin is locked to `https://webathome.org`.

## Validation service

The runtime side of the metaschema. Hosts the schemas, validates artifacts via
`POST /api/validate`, serves the merged dataset and the viewer, and renders
`USAGE.md` at the container root. The full API — request/response shape, schema and
dataset URLs, the `arch-validate.py` CLI producers drop into their own `scripts/`,
the `$schema` editor pragma, and how to file schema-change requests — is documented
in [`USAGE.md`](./USAGE.md), which is also served live at
`architecture.webathome.org/`.

## Develop

```
./scripts/dev.sh        # Vite dev server at http://localhost:5173/viewer/
```

Regenerate schemas + viewer vocab after editing `subset.yaml` or the enums:

```
cd tooling && poetry run python generate.py          # writes generated/ + viewer vocab
cd tooling && poetry run python generate.py --check   # CI: fail if anything is stale
cd tooling && poetry run python validate.py meta      # self-validate every schema
cd tooling && poetry run python tests/run_fixtures.py # collector end-to-end fixtures
cd viewer  && npm run build                            # tsc --noEmit && vite build
```

## Build the container

```
docker build -t architecture .
docker run --rm -p 8080:8080 architecture
# http://localhost:8080/         rendered USAGE.md
# http://localhost:8080/viewer/  the diagram
# curl :8080/healthz /metrics /data/v0.1/architecture.json /schema/v0.1/architecture.schema.yaml
```

A developer `docker build` skips the collector (no producer artifacts in context);
the merged dataset is produced in CI by the Jenkinsfile, which clears the
`producer-artifacts/` exclusion so the `run-collector` stage sees them.

## Deployment

Self-hosted homelab: Kubernetes, Jenkins, Kaniko, Ansible. The Helm chart lives in
`pvginkel/HelmCharts`. The pipeline collects, builds with Kaniko, and redeploys.

## Design decisions worth knowing

- **Data is sourced from the repo that owns it.** Different repos own different
  element types (VMs, Helm releases, app pods); each is the authority for its own
  slice. The merge is the only integration point — producers never coordinate.
- **No migration of the legacy 145-node diagram.** The old hand-authored taxonomy
  was abandoned, not transformed; the federated dataset was built fresh from real
  producer emissions.
- **Inclusion rule:** a thing belongs in the diagram if it has a stable external
  identity another component can reach by name (DNS name, pod name, queue, bucket,
  API path). Classes, screens, internal functions are out; borderline cases default
  to out.
- **Fail loudly, no defensive padding.** Boundary validation (schema, references,
  triple matrix) is the point; beyond it there are no swallowed errors, no
  drop-the-bad-input paths, no "just in case" fallbacks. A broken build beats a
  silently half-correct dataset.

## Status & open threads

The system is built and live end-to-end: schema, validation service, federation
pipeline, ~20 onboarded producers, and the data-driven viewer. Remaining items are
deferred design decisions (logo single-sourcing, producer-supplied logos in the
image, a canonical service↔interface idiom) tracked in [`docs/todo.md`](docs/todo.md).

The operator-side onboarding workflow (producer manual, seeding skill, update
agents) is packaged as the `arch` Claude Code plugin under `arch/`, installed into
the operator's `~/.claude/` from this repo — see [`CLAUDE.md`](./CLAUDE.md).
