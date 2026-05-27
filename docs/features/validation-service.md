# Validation service + developer integration

The runtime side of the metaschema phase. Delivers the container that hosts the schema files, exposes `POST /api/validate`, renders developer docs at the container root, and ships the `arch-validate` dev CLI.

Depends on [`metaschema-design.md`](./metaschema-design.md) — the schema files this service serves and validates against must exist first.

Inspiration: [`docs/architecture-rebuild/02-metaschema.md`](../architecture-rebuild/02-metaschema.md), specifically the "Validator CLI" section, which is superseded by this doc (and rewritten back into `02-metaschema.md` as a final work item).

## Decisions locked

- **Single Node/Express service replaces nginx.** One process per container, no reverse-proxy gymnastics.
- **Validation is hosted, not distributed as a binary.** Primary consumer is the `arch-validate` dev CLI; CI is a secondary mode of the same tool.
- **`POST /api/validate` accepts JSON and YAML** artifacts, distinguished by `Content-Type`.
- **Error responses are LLM- and human-friendly**, not raw `ajv` output.
- **The endpoint is public, unauthenticated.** Same posture as the rest of the stack.
- **Schema URLs serve both `.json` (canonical) and `.yaml` (convenience).** External JSON Schema tooling sees JSON.
- **Container root (`/`) serves rendered `USAGE.md`** so developers landing on the bare domain get integration docs.
- **Prometheus metrics at `/metrics`.** Keep it minimal — request counts, validation outcomes, duration histogram.
- **Schema-version compatibility window:** see [`metaschema-design.md`](./metaschema-design.md). At v0.1, the service accepts only `"0.1"`.

## Service architecture

```
service/
  package.json
  tsconfig.json
  src/
    index.ts                # bootstraps express, mounts routes
    static.ts               # /viewer/*, /schema/v0.1/*
    validate.ts             # POST /api/validate
    schema-loader.ts        # parses YAML schemas + enums at startup
    error-translate.ts      # ajv errors → LLM-friendly shape
    usage.ts                # renders USAGE.md → HTML at startup
    metrics.ts              # prom-client counters/histograms
    csp.ts                  # CSP middleware (port from nginx.conf)
  test/
    validate.test.ts        # endpoint smoke + golden artifacts
    static.test.ts          # schema URLs, /viewer/, headers
    usage.test.ts           # / renders, links resolve
```

**One Node process. One image. No nginx.**

Routes:

| path | method | purpose |
|---|---|---|
| `/` | GET | rendered USAGE.md (HTML) |
| `/viewer/*` | GET | static viewer build, SPA fallback to `/viewer/index.html` |
| `/schema/v0.1/*.json` | GET | canonical JSON form of each schema/enum file |
| `/schema/v0.1/*.yaml` | GET | YAML source of each schema/enum file |
| `/api/validate` | POST | validate artifact |
| `/healthz` | GET | liveness/readiness, returns `200 OK` |
| `/metrics` | GET | Prometheus exposition |

## `POST /api/validate` contract

```
POST /api/validate
Content-Type: application/json | application/yaml | text/yaml
Body: artifact in the matching format (≤ 5 MB)

200 OK
{ "valid": true, "schemaVersion": "0.1" }

200 OK
{
  "valid": false,
  "schemaVersion": "0.1",
  "errors": [
    {
      "path": "/components/3/realizes/0",
      "message": "value 'cap:sso-v2' is not a known capability id",
      "value": "cap:sso-v2",
      "keyword": "enum",
      "schemaUrl": "https://architecture.webathome.org/schema/v0.1/enums/capabilities.json",
      "hint": "see the capabilities enum for the current list"
    }
  ]
}

400 Bad Request   — body unparseable as the declared Content-Type, missing schemaVersion, or unknown schemaVersion
415 Unsupported Media Type   — Content-Type other than the three above
500 Internal Server Error   — server bug
```

- HTTP status is for request handling. The `valid` field is the validation outcome signal — both pass and fail return `200`.
- The artifact's top-level `schemaVersion` selects which compiled validator to dispatch to. At v0.1, only `"0.1"` is accepted; any other value → `400`.
- YAML bodies are parsed into the same JS object shape as JSON, so the JSON-Pointer `path` values are identical regardless of source format.
- The error response is always JSON, regardless of input format.

## Error translation

Raw `ajv` errors are too terse for a human or LLM agent to act on without consulting other context. Every error is translated to the shape above:

| field | source | purpose |
|---|---|---|
| `path` | `ajv` `instancePath` | JSON Pointer into the submitted artifact |
| `message` | hand-written per keyword | full-sentence English; quotes the offending value when short |
| `value` | extracted from artifact at `path` | the value that failed, so the reader doesn't have to re-fetch it |
| `keyword` | `ajv` `keyword` | machine-readable error class (`enum`, `pattern`, `required`, …) |
| `schemaUrl` | derived from `ajv` `schemaPath` | the most specific schema or enum file relevant to the error |
| `hint` | hand-written per keyword | one-line next-step suggestion |

When a single root cause produces multiple `ajv` errors (e.g., `oneOf` cascades, `not` clauses), the translation layer deduplicates so the reader sees one error per real problem.

The full list of supported keywords and their translations is encoded in `service/src/error-translate.ts` and exercised by `service/test/validate.test.ts`.

## Schema publication

URLs:

```
https://architecture.webathome.org/schema/v0.1/architecture.schema.json
https://architecture.webathome.org/schema/v0.1/subset.json
https://architecture.webathome.org/schema/v0.1/generated/node.schema.json
https://architecture.webathome.org/schema/v0.1/generated/device.schema.json
https://architecture.webathome.org/schema/v0.1/generated/systemsoftware.schema.json
https://architecture.webathome.org/schema/v0.1/generated/applicationcomponent.schema.json
https://architecture.webathome.org/schema/v0.1/generated/applicationservice.schema.json
https://architecture.webathome.org/schema/v0.1/generated/applicationinterface.schema.json
https://architecture.webathome.org/schema/v0.1/generated/technologyservice.schema.json
https://architecture.webathome.org/schema/v0.1/generated/technologyinterface.schema.json
https://architecture.webathome.org/schema/v0.1/generated/artifact.schema.json
https://architecture.webathome.org/schema/v0.1/generated/capability.schema.json
https://architecture.webathome.org/schema/v0.1/generated/businessservice.schema.json
https://architecture.webathome.org/schema/v0.1/generated/grouping.schema.json
https://architecture.webathome.org/schema/v0.1/generated/relations.schema.json
https://architecture.webathome.org/schema/v0.1/enums/capabilities.json
https://architecture.webathome.org/schema/v0.1/enums/lifecycle-states.json
https://architecture.webathome.org/schema/v0.1/enums/environments.json
https://architecture.webathome.org/schema/v0.1/enums/producer-profiles.json
https://architecture.webathome.org/schema/v0.1/archimate/archimate3_Model.xsd
https://architecture.webathome.org/schema/v0.1/archimate/relationships.xml
https://architecture.webathome.org/schema/v0.1/archimate/relationships-keys.xml
```

Each YAML schema is also served at the same path with `.yaml`. The vendored ArchiMate XSD and the Archi relationship matrix are served as-is (XML); the validation service does not transform them.

Headers:

- `Content-Type`: `application/schema+json` for the `.json` URLs, `application/yaml` for the `.yaml` URLs.
- `Cache-Control: public, max-age=300`. Short enough to roll a fix quickly; long enough that producers' CI doesn't hammer the container.
- `Access-Control-Allow-Origin: *`. Browser-based JSON Schema tooling and IDE extensions need this.

JSON files are generated at service startup from the YAML sources via `js-yaml` and held in memory. They are not pre-built artifacts.

## Dev CLI — `arch-validate`

The load-bearing dev-facing artifact. Primary audience: developers and LLM-driven authoring skills writing artifacts in producer repos.

**Location:** `scripts/arch-validate` in this repo. Producers copy it into their own `scripts/` directory; updates are coordinated by re-copying (no submodule, no remote-fetch-at-run-time).

**Implementation:** single bash file. Dependencies: `bash`, `curl`, `jq`. Everything substantial happens server-side; keeping the script trivial means producers can read it on sight.

**Behavior:**

- `arch-validate <path>` — validates a single artifact. Exit 0 on valid, 1 on invalid, 2 on transport/server error.
- `arch-validate <path1> <path2> ...` — validates multiple; exits non-zero if any fail.
- `arch-validate -` — reads from stdin (so an LLM can pipe a candidate artifact without writing it to disk).
- Default output: human-readable, one block per error. Colored when stderr is a TTY.
- `--json` — emit the raw endpoint response to stdout. For CI scripts.
- `--quiet` — suppress per-file "OK" lines; only print on failure.
- `--format json|yaml` — override Content-Type detection (default: from file extension, `.yaml` for stdin).
- `ARCHITECTURE_VALIDATE_URL` env var — override the endpoint (for local-service testing).

**Sketch:**

```bash
#!/usr/bin/env bash
# arch-validate — validate architecture artifact(s) against the hosted schema.
set -euo pipefail

endpoint="${ARCHITECTURE_VALIDATE_URL:-https://architecture.webathome.org/api/validate}"
mode="human"
format_override=""
status=0

while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --json) mode="json" ;;
    --quiet) mode="quiet" ;;
    --format) shift; format_override="$1" ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

for artifact in "$@"; do
  if [[ "$artifact" == "-" ]]; then
    body="$(cat)"
    default_ctype="application/yaml"
  else
    body="$(cat "$artifact")"
    case "$artifact" in
      *.json) default_ctype="application/json" ;;
      *.yaml|*.yml) default_ctype="application/yaml" ;;
      *) default_ctype="application/yaml" ;;
    esac
  fi

  ctype="${format_override:+application/$format_override}"
  ctype="${ctype:-$default_ctype}"

  response="$(curl -fsS -X POST \
    -H "Content-Type: $ctype" \
    --data-binary "$body" \
    "$endpoint")" || { echo "transport error" >&2; exit 2; }

  # … print response in human/json/quiet form, set status=1 on .valid == false
done

exit "$status"
```

**Human output:**

```
✗ component.json
  /components/3/realizes/0
    value 'cap:sso-v2' is not a known capability id
    hint: see the capabilities enum
    schema: https://architecture.webathome.org/schema/v0.1/enums/capabilities.json

  /components/3
    component is missing required field 'packagedAs'
    schema: https://architecture.webathome.org/schema/v0.1/component.schema.json
```

This is the format an LLM agent will read and act on; intelligible in a single pass.

## USAGE.md and the container root

`USAGE.md` lives at the repo root. The service renders it to HTML at startup (using `markdown-it`, or equivalent) and serves the result at `/`. No request-time rendering — one render at startup, cached in memory.

**Content of USAGE.md (target outline):**

1. What this container does (one paragraph).
2. The `POST /api/validate` contract (compact version of the section above).
3. Schema URLs (table).
4. Curl example: validate a YAML artifact end-to-end.
5. The `arch-validate` CLI — how to drop it into a producer repo, basic usage.
6. Linking schemas from artifacts and editors (the `$schema` pragma).
7. Where to file schema-change requests (PR against `schema/v0.1/...` in this repo).

The rendered HTML uses a minimal embedded stylesheet — readable mono-and-prose, no JS, no external assets. Server-rendered Markdown shouldn't drag in a bundle.

## Prometheus `/metrics`

Keep it minimal. `prom-client`:

| metric | type | labels | purpose |
|---|---|---|---|
| `arch_validate_requests_total` | counter | `outcome` ∈ {`valid`, `invalid`, `bad_request`, `error`} | call volume by outcome |
| `arch_validate_duration_seconds` | histogram | `outcome` | latency distribution |
| `arch_validate_body_bytes` | histogram | — | artifact-size distribution |
| `arch_schema_load_errors_total` | counter | — | schema files that failed to parse at startup |
| `process_*`, `nodejs_*` | (defaults) | — | `prom-client` default collectors |

No per-error-keyword metrics, no per-producer metrics. If a need shows up later, add it then.

## Dockerfile

Multi-stage, three stages. Drops the `FROM nginx:alpine` stage entirely.

```
FROM python:3.13-slim AS check-schemas
WORKDIR /work
RUN pip install --no-cache-dir poetry
COPY tooling/pyproject.toml tooling/poetry.lock ./tooling/
RUN cd tooling && poetry install --no-root --only main
COPY schema/ ./schema/
COPY tooling/ ./tooling/
RUN cd tooling && poetry run python generate.py --check

FROM node:20-alpine AS build-viewer
WORKDIR /app
COPY viewer/package*.json ./
RUN npm ci
COPY viewer/ ./
RUN npm run build

FROM node:20-alpine AS build-service
WORKDIR /app
COPY service/package*.json ./
RUN npm ci
COPY service/ ./
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=build-service /app/dist ./dist
COPY --from=build-service /app/node_modules ./node_modules
COPY --from=build-viewer /app/dist ./viewer-dist
COPY --from=check-schemas /work/schema ./schema
COPY USAGE.md ./USAGE.md
ENV NODE_ENV=production
EXPOSE 8080
ENTRYPOINT ["node", "dist/index.js"]
```

The `check-schemas` stage runs `generate.py --check` against the committed `schema/v0.1/generated/` tree; the build fails if the generator would produce different output (i.e. if `subset.yaml` was changed without re-running the generator). The image then copies `schema/` from that stage, guaranteeing the in-container schemas match the checked-in form.

The service's `static.ts` resolves `./viewer-dist`, `./schema`, `./USAGE.md` relative to the working directory.

`viewer/nginx.conf` is deleted as part of this work — no stragglers.

## Helm deploy

The user deploys via Helm; the chart lives in a separate repo. Before this work begins, the user grants Claude access to that Helm repo.

Things the chart likely cares about:

- Container image tag (unchanged in shape, but the contents are now Node, not nginx).
- Exposed container port. The new service exposes `8080`; nginx may have been on `80`. Confirm and align.
- Liveness/readiness probes. Should hit `/healthz` rather than `/` (since `/` now does Markdown rendering and is heavier than necessary for probes).
- Resource requests/limits. Node has a different memory profile than nginx — probably needs a bump in `requests.memory`. Confirm with one round of running in-cluster before tightening.
- Service annotations for Prometheus scraping (if the cluster uses `prometheus.io/scrape` conventions) — point at `/metrics` on the service port.
- No `nginx`-specific config (`nginx.conf` ConfigMap, etc.) — strip if present.

**Action item:** when this phase begins, ask the user for access to the Helm repo before writing any deploy-side changes.

## Work items

### 1. Scaffold the service

Create `service/` with `package.json`, `tsconfig.json`, the empty source-file skeleton listed under "Service architecture" above. Dependencies: `express`, `ajv`, `ajv-formats`, `js-yaml`, `markdown-it`, `prom-client`. Dev dependencies: `typescript`, `@types/*`, a test runner (`vitest` is light and consistent with the existing Vite tooling).

**Exit criteria:**

- [ ] `npm --prefix service ci && npm --prefix service run build` succeeds.
- [ ] Empty service starts and serves `/healthz`.

### 2. Schema loader

Parses every YAML schema under `schema/v0.1/` at startup — specifically `architecture.schema.yaml`, `subset.schema.yaml`, `generated/*.yaml`, and `enums/*.yaml`. The per-kind schemas under `generated/` are produced by `tooling/generate.py` from `schema/v0.1/subset.yaml` + the vendored ArchiMate XSD + Archi relationship matrix; the Docker build verifies they are up to date by running `poetry run python tooling/generate.py --check` before assembling the image.

Compiles each YAML schema into an `ajv` validator. Meta-validates every schema against the JSON Schema 2020-12 self-meta. Fails the service boot if any schema is malformed.

Loads the `x-allowedTriples` block embedded in `generated/relations.schema.yaml` and exposes it as a structured lookup so the validate handler can enforce the (source-kind, type, target-kind) matrix at request time.

Also builds an in-memory map for the static handler: `path → { yaml: string, json: string, etag: string }`.

**Exit criteria:**

- [ ] All schema files load without error.
- [ ] A deliberately broken schema in a test fixture causes the loader to throw with a clear path-and-reason error.
- [ ] Schema-meta-validation wired in; covered by a test.
- [ ] Triple matrix loaded from `x-allowedTriples` and queryable in O(1).

### 3. Static handler — `/viewer/`, `/schema/`

Serves the built viewer at `/viewer/*` with SPA fallback to `/viewer/index.html`. Serves the schema files at the URLs listed above with the headers listed above. Includes the CSP and iframe-allow headers from the current `viewer/nginx.conf`.

**Exit criteria:**

- [ ] `curl https://.../viewer/` renders the diagram identically to the nginx-served version.
- [ ] All schema URLs respond `200` with the documented headers.
- [ ] CSP/iframe headers verified via `curl -I` against the embedded webathome.org page.
- [ ] `viewer/nginx.conf` deleted.

### 4. Validate handler — `POST /api/validate`

Parses by `Content-Type`. Dispatches by `schemaVersion`. Runs the compiled `ajv` validator. Translates errors. Returns the JSON response.

**Exit criteria:**

- [ ] Endpoint passes for each `schema/v0.1/examples/valid-*.yaml` (committed under that path; `valid-minimal.yaml` and `valid-full.yaml` exist today).
- [ ] Endpoint fails with the JSON pointer recorded in the example's `# expect:` header for each `schema/v0.1/examples/invalid-*.yaml` (today: `additional-property`, `malformed-id`, `deprecation-rule`, `removed-with-replacedby`, `unknown-relationship-type`).
- [ ] Relations validation enforces the triple matrix from `x-allowedTriples` in `generated/relations.schema.yaml`.
- [ ] Test suite covers: missing `schemaVersion`, unknown `schemaVersion`, malformed JSON, malformed YAML, oversized body, unsupported `Content-Type`.

### 5. Error translation

Implement `service/src/error-translate.ts`. Per-`ajv`-keyword translation functions; deduplication of `oneOf` cascades; `schemaUrl` derivation from `ajv`'s `schemaPath`.

**Exit criteria:**

- [ ] Each keyword used by the v0.1 schemas has a translation function with a unit test.
- [ ] An `invalid-*` golden example with cascading errors collapses to one error in the response.

### 6. Render and serve USAGE.md at `/`

Read `USAGE.md` at startup, render via `markdown-it`, wrap in a minimal HTML shell with an embedded stylesheet, serve at `/`. Cache the rendered HTML in memory.

**Exit criteria:**

- [ ] `curl https://architecture.webathome.org/` returns rendered HTML.
- [ ] All internal links (`#sections`, `/schema/...`, `/viewer/`) resolve.
- [ ] Page is usable without JS.

### 7. Author USAGE.md

Write the document per the outline above. Target audience: a developer (or LLM agent) integrating their producer repo with the architecture system for the first time.

**Exit criteria:**

- [ ] `USAGE.md` committed at the repo root.
- [ ] Covers the seven outline points.
- [ ] Curl example works against the deployed service verbatim.
- [ ] README links to USAGE.md.

### 8. `arch-validate` dev CLI

Per the spec above. Single bash file. No external runtime deps beyond `bash`, `curl`, `jq`.

**Exit criteria:**

- [ ] `scripts/arch-validate` committed, executable.
- [ ] Works against both deployed and local-service endpoints.
- [ ] Validates a known-good YAML artifact, a known-good JSON artifact, a known-bad of each.
- [ ] Multi-file mode aggregates failure correctly.
- [ ] `-` (stdin) mode works.
- [ ] README and USAGE.md show the dev loop: edit → `arch-validate file` → read errors → fix → re-run.

### 9. `/metrics`

`prom-client` defaults plus the four custom metrics listed above.

**Exit criteria:**

- [ ] `curl /metrics` returns valid Prometheus exposition.
- [ ] Counters increment on validate calls; histogram observes durations.
- [ ] Local Prometheus scrape (or `promtool check metrics`) accepts the output.

### 10. Dockerfile rework

Per the multi-stage sketch above.

**Exit criteria:**

- [ ] `docker build -t architecture .` succeeds.
- [ ] `docker run --rm -p 8080:8080 architecture` serves `/`, `/viewer/`, `/schema/v0.1/...`, `/api/validate`, `/healthz`, `/metrics`.
- [ ] Image size acceptable (target < 250 MB; not load-bearing).
- [ ] `viewer/nginx.conf` gone from the repo; no references remain.

### 11. Helm chart update

Coordinated with the user; depends on them granting access to the Helm repo. Align port, probes, resources, scrape annotations.

**Exit criteria:**

- [ ] Ask user for Helm repo access before starting.
- [ ] Chart deploys the new image cleanly to the homelab cluster.
- [ ] `architecture.webathome.org/viewer/` renders the diagram unchanged.
- [ ] `architecture.webathome.org/api/validate` reachable.
- [ ] Prometheus scrapes `/metrics`.

### 12. Update `02-metaschema.md`

Rewrite the source rebuild doc to match what was built.

- "Validator CLI" → "Validation service". Replace the binary description with the endpoint contract.
- "JSON Schema publication" → state the v0.1 immutability rule, confirm the canonical URLs.
- "Open questions for v1 finalization" → resolve both.
- "Decisions locked" → append the new locked decisions.
- Add a link to this feature doc and to `metaschema-design.md` for the execution trail.

**Exit criteria:**

- [ ] No remaining mentions of "single-binary validator" or "Linux/macOS binary release" in `02-metaschema.md`.
- [ ] Both open questions removed (resolved) or restated as decisions.
- [ ] Links to the two feature docs in place.

## Exit criteria for the phase

- [ ] Service running in the container, serving `/`, `/viewer/`, `/schema/v0.1/...`, `/api/validate`, `/healthz`, `/metrics`.
- [ ] Schema files reachable at their public URLs.
- [ ] `arch-validate` CLI committed and verified end-to-end.
- [ ] USAGE.md authored and rendered at the container root.
- [ ] Prometheus scraping the service.
- [ ] nginx fully removed from the container and the repo.
- [ ] Helm chart updated and deployed.
- [ ] `02-metaschema.md` rewritten to match.
