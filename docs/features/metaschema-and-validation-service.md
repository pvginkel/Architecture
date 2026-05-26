# Metaschema v0.1 + validation service

Execution plan for `docs/architecture-rebuild/02-metaschema.md`. Delivers the schema package, the hosted validation endpoint, and the schema publication path. Does **not** touch the existing 145-node dataset — that is `03-data-migration.md`.

## Decisions locked (delta from 02-metaschema.md)

These supersede the relevant sections of `02-metaschema.md`; the source doc gets updated in the final work item.

- **Validation is a hosted service, not a single-binary CLI.** `POST https://architecture.webathome.org/api/validate` with the artifact as the JSON body. Primary consumer is the `arch-validate` dev CLI (item 5), which is just a bash wrapper around `curl`; CI is a secondary mode of the same tool. The doc's "Validator CLI" section is rewritten accordingly.
- **The viewer container drops nginx.** Replaced by a single Node/Express service that serves the static viewer build, serves the schema files, and exposes the validate endpoint. One process, one image.
- **Schema and enums are authored in YAML.** The service parses YAML in memory at startup using `js-yaml` — no separate build tool. The hosted schema URLs serve canonical JSON (converted at startup) so external JSON Schema tooling and IDE extensions work unchanged.
- **The validate endpoint accepts both YAML and JSON artifacts**, distinguished by `Content-Type`. Producers and the dev CLI may submit whichever format is more convenient.
- **Enum files live at `schema/v0.1/enums/`.**
- **Component `producer` field is declared, not derived.** Robust to producer-repo reorganization.
- **JSON Schema validator library: `ajv` (strict mode, with `ajv-formats`).** Most mature option in the Node ecosystem.

## Endpoint contract

```
POST /api/validate
Content-Type: application/json   |   application/yaml   |   text/yaml
Body: <artifact in the matching format>

200 OK
{ "valid": true, "schemaVersion": "0.1" }

200 OK
{ "valid": false, "schemaVersion": "0.1", "errors": [ { "path": "...", "message": "...", "value": ..., "keyword": "...", "schemaUrl": "...", "hint": "..." } ] }

400 Bad Request   — body not parseable as the declared Content-Type, or missing `schema-version`
415 Unsupported Media Type   — Content-Type other than the three above
500 Internal Server Error  — server-side bug
```

- HTTP status reflects request handling, not validation outcome. `valid` is the signal.
- The artifact's top-level `schema-version` selects which schema to validate against. Unknown versions → 400.
- YAML bodies are parsed into the same JS object shape as JSON, so error `path` values (JSON Pointers) are identical regardless of source format. The error response is always JSON.
- Error objects follow the LLM-friendly shape spelled out in work item 2.

Producer-side usage is a single shell script committed into each producer repo (template in work item 5).

## Out of scope for this doc

- Data migration of the existing 145 nodes (→ `03-data-migration.md`).
- Cross-artifact reference resolution, dangling-reference detection, multi-edge collision rules, producer-profile enforcement on merged data (→ `05-collector-and-pipeline.md`).
- Federated producer onboarding (→ `04-producer-protocol.md`).
- Any logo or asset changes (`docs/todo.md` items stand).

---

## Work items

Each item is self-contained and independently committable. Order is roughly dependency-driven; items 1–4 are required for the v1 exit criteria, item 5 is a producer-facing artifact, item 6 closes the loop on the source doc.

### 1. Schema package — `schema/v0.1/`

Lay down the JSON Schema and enum files in the repo. No service code yet; the schema must stand on its own.

**Layout:**

```
schema/
  v0.1/
    architecture.schema.yaml     # master schema; oneOf over the five document kinds
    capability.schema.yaml
    component.schema.yaml
    product.schema.yaml
    edge.schema.yaml
    group.schema.yaml
    enums/
      capabilities.yaml          # entries list + per-entry metadata (label, lifecycle, ...)
      products.yaml
      edge-types.yaml
      lifecycle-states.yaml
      producer-profiles.yaml
```

YAML is the authoring format in the repo. The service loads these at startup with `js-yaml`, validates them against JSON Schema 2020-12 self-meta, and republishes them as JSON at the public URLs (so external tooling sees canonical JSON Schema).

**Decisions inside the schema:**

- `schema-version` is a required top-level field on every artifact, fixed to `"0.1"` at this version.
- An artifact is `{ schemaVersion, capabilities?, components?, products?, edges?, groups? }`. Each field is an array of the corresponding document kind. Empty arrays allowed.
- Component IDs: `^comp:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` (UUIDv4).
- Capability/product/group IDs: `^cap:[a-z][a-z0-9-]*$` / `^prod:...` / `^group:<uuidv4>$`.
- `realizes`, `packaged-as`, `group` fields are string references to the appropriate ID space; the JSON Schema enforces format only — actual existence is a collector concern.
- Edge types and lifecycle states are `enum` constraints sourced from the enum files.
- Capability and product IDs are NOT enum-constrained at JSON Schema time — they're enum-constrained at collector time against `enums/capabilities.json` (so producers fail their own CI when they reference an unknown one). The validate endpoint accepts the enum files as part of its config and applies them at validation time; the JSON Schema itself stays open so the enum file is the single source of truth.
- Render-only fields (`position`, hardcoded sizes, layer assignment, `x`/`y`) are explicitly rejected via `additionalProperties: false` and `not` clauses.

**Enum file shape (example, `capabilities.yaml`):**

```yaml
$id: https://architecture.webathome.org/schema/v0.1/enums/capabilities.json
$schema: https://json-schema.org/draft/2020-12/schema
entries:
  - id: cap:sso
    label: Single Sign-On
    lifecycle: active
  - id: cap:object-storage
    label: Object Storage
    lifecycle: active
```

The master schema $refs the published JSON form; the service derives the allowed-ID list from the parsed YAML at startup. The `$id` deliberately points at the `.json` URL — that is the canonical reference; the `.yaml` source is a repo authoring convenience.

**Exit criteria:**

- [ ] All five document schemas exist and pass `ajv --strict` self-check.
- [ ] All five enum files exist with at least the entries named in `02-metaschema.md`.
- [ ] A hand-crafted minimal valid artifact (one component realizing one capability, packaged-as one product) validates green via `npx ajv validate`.
- [ ] A hand-crafted invalid artifact (component with `position` field) validates red.

### 2. Replace nginx with a Node/Express service

The container's web layer becomes a single Node service. Same image, same exposed port, same path layout, just no nginx.

**Service layout:**

```
service/
  package.json
  tsconfig.json
  src/
    index.ts                # bootstraps express, mounts routes
    static.ts               # serves /viewer/* and /schema/v0.1/*
    validate.ts             # POST /api/validate handler
    schema-loader.ts        # loads schemas and enums at startup
    csp.ts                  # CSP middleware (port from current nginx.conf)
  test/
    validate.test.ts        # endpoint smoke tests + a few golden artifacts
```

**Responsibilities, ported from `viewer/nginx.conf`:**

- Serve `viewer/dist/` under `/viewer/` with SPA fallback to `/viewer/index.html`.
- Serve schema files under `/schema/v0.1/...` as JSON, converted at startup from the YAML sources in `schema/v0.1/`. Both `.json` and `.yaml` URLs respond — JSON is canonical, YAML is a convenience for humans reading the schema in a browser.
- Apply the existing CSP / iframe-allow headers so the parent (`webathome.org`) embed still works.
- Health endpoint at `/healthz` returning `200 OK`.

**Validate handler (`/api/validate`):**

- Loads compiled `ajv` validators at startup, keyed by schema version. Schemas are parsed from YAML via `js-yaml`, then handed to `ajv` as JS objects.
- Parses the request body according to `Content-Type`: `application/json` → `JSON.parse`; `application/yaml` or `text/yaml` → `js-yaml` safe-load. Other types → 415.
- Reads `schema-version` from the parsed body, dispatches to the matching validator.
- Cross-checks `realizes` / `packaged-as` references against the loaded enum entries; emits errors in the same shape as schema errors.
- Body size limit: 5 MB (artifacts are tiny; this is just a safety bound).
- Logs each call with `{ schemaVersion, contentType, valid, errorCount, byteLength, durationMs }`. No request-body logging.

**Error shape (LLM- and human-friendly, not raw `ajv`):**

The primary consumer of validation errors is a developer or an LLM agent authoring an artifact. Raw `ajv` errors are too terse — short keyword names, vague messages, no snippet of the offending value. The handler translates each `ajv` error into:

```json
{
  "path": "/components/3/realizes/0",
  "message": "value 'cap:sso-v2' is not a known capability id",
  "value": "cap:sso-v2",
  "keyword": "enum",
  "schemaUrl": "https://architecture.webathome.org/schema/v0.1/enums/capabilities.json",
  "hint": "see the capabilities enum for the current list"
}
```

- `path` is a JSON Pointer into the submitted artifact.
- `message` is full-sentence English; includes the offending value inline when short enough.
- `schemaUrl` points at the most specific schema or enum file relevant to the error, so a reader (human or LLM) can fetch it without guessing.
- `keyword` and `value` are kept for tooling. Raw `ajv` `params` are dropped.

Errors are deduplicated when a single root cause produces multiple `ajv` errors (e.g., `oneOf` cascades).

**Exit criteria:**

- [ ] `npm --prefix service run start` boots the service locally and serves the viewer + schema.
- [ ] `curl -X POST .../api/validate` returns `{ valid: true }` for a known-good artifact.
- [ ] Same call returns `{ valid: false, errors: [...] }` for a known-bad artifact.
- [ ] CSP headers match what nginx was emitting (verify via `curl -I`).
- [ ] Test suite covers: valid artifact, missing `schema-version`, unknown `schema-version`, malformed JSON body, oversized body, each document-kind error class.

### 3. Dockerfile + Jenkinsfile updates

The image becomes Node-only.

**Dockerfile changes:**

- Stage 1 (`build-viewer`): unchanged — `npm ci && npm run build` in `viewer/`.
- Stage 2 (`build-service`): `npm ci && npm run build` in `service/` (TS → JS).
- Stage 3 (runtime): `node:20-alpine`. Copies `service/dist/`, `service/node_modules/` (prod-only), `viewer/dist/`, and `schema/`. Entrypoint `node service/dist/index.js`. Exposes `8080`.
- Drops `FROM nginx:alpine` and `nginx.conf` entirely.

**Jenkinsfile:**

- The user wires this. Note in the file (comment) that the build now produces a Node runtime image, not nginx.

**Exit criteria:**

- [ ] `docker build -t architecture .` succeeds.
- [ ] `docker run --rm -p 8080:8080 architecture` serves `/viewer/` and `/schema/v0.1/architecture.schema.json` and responds to `/api/validate`.
- [ ] Image size is acceptable (rough target: under 200 MB; not load-bearing).
- [ ] `viewer/nginx.conf` is deleted; no stragglers reference it.

### 4. Schema publication URL contract

The container is the CDN for the schema. Producers and tooling reference schemas by URL, not by file path.

**URLs (stable):**

```
https://architecture.webathome.org/schema/v0.1/architecture.schema.json
https://architecture.webathome.org/schema/v0.1/component.schema.json
https://architecture.webathome.org/schema/v0.1/enums/capabilities.json
... etc
```

**Headers:**

- `Cache-Control: public, max-age=300` on schema files. Short enough to roll a fix quickly; long enough to not hammer the container.
- `Access-Control-Allow-Origin: *` so browser-based tooling (JSON Schema viewers, IDE extensions) can fetch them.

**Versioning:**

- `v0.1` is immutable once published. A breaking change cuts `v0.2/` alongside; both URLs stay live until the deprecation window closes.
- Patch fixes inside `v0.1` are allowed and overwrite in place (cache TTL bounded above).

**Exit criteria:**

- [ ] All schema URLs respond 200 with `application/json` and the cache + CORS headers.
- [ ] A fresh `ajv` instance can fetch and compile `architecture.schema.json` purely via `$ref` traversal of the public URLs.

### 5. Dev CLI — `arch-validate`

This is the load-bearing dev-facing artifact of this phase. Primary audience: developers and LLM-driven authoring skills writing artifacts in producer repos. CI use is a secondary mode of the same tool.

**Location:** `scripts/arch-validate` in this repo, as the canonical copy. Producers drop the same script into their own `scripts/` directory; updates are coordinated by re-copying (no submodule, no curl-from-internet at run time).

**Implementation:** bash, single file. No language runtime beyond bash + `curl` + `jq`. The CLI is intentionally thin — all real work happens server-side at `/api/validate`. Keeping the script trivial means producer repos can read and trust it on sight.

**Behavior:**

- `arch-validate <path>` — validates a single artifact. Exits 0 on valid, 1 on invalid, 2 on transport/server error.
- `arch-validate <path1> <path2> ...` — validates multiple artifacts; exits non-zero if any fail. Per-file status to stderr.
- Default output: human-readable. One block per error: path, message, offending value, and the schema URL the reader should consult next. Colored when stderr is a TTY; plain otherwise.
- `--json` flag: emits the raw JSON response from the endpoint to stdout instead. For CI scripts and machine consumers.
- `--quiet` flag: suppresses the per-file "OK" lines; only prints on failure.
- `ARCHITECTURE_VALIDATE_URL` env var overrides the endpoint (for local-service testing).
- Reads from stdin when path is `-`, so an LLM can pipe a candidate artifact in without writing it to disk first.
- Content-Type is inferred from the file extension: `.json` → `application/json`; `.yaml`/`.yml` → `application/yaml`. For stdin, defaults to `application/yaml` (the authoring format); `--format json|yaml` overrides.

**Sketch:**

```bash
#!/usr/bin/env bash
# arch-validate — validate architecture artifact(s) against the hosted schema.
# Usage:
#   arch-validate <artifact.json> [<artifact.json> ...]
#   arch-validate --json <artifact.json>
#   cat artifact.json | arch-validate -
set -euo pipefail

endpoint="${ARCHITECTURE_VALIDATE_URL:-https://architecture.webathome.org/api/validate}"
mode="human"
status=0

while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --json) mode="json" ;;
    --quiet) mode="quiet" ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

for artifact in "$@"; do
  if [[ "$artifact" == "-" ]]; then
    body="$(cat)"
  else
    body="$(cat "$artifact")"
  fi

  case "$artifact" in
    *.json) ctype="application/json" ;;
    *.yaml|*.yml|-) ctype="application/yaml" ;;
    *) ctype="application/yaml" ;;
  esac

  response="$(curl -fsS -X POST \
    -H "Content-Type: $ctype" \
    --data-binary "$body" \
    "$endpoint")" || { echo "transport error" >&2; exit 2; }

  # ... print response in human/json/quiet form, set status=1 on .valid==false
done
exit "$status"
```

**Human output example:**

```
✗ component.json
  /components/3/realizes/0
    value 'cap:sso-v2' is not a known capability id
    hint: see the capabilities enum
    schema: https://architecture.webathome.org/schema/v0.1/enums/capabilities.json

  /components/3
    component is missing required field 'packaged-as'
    schema: https://architecture.webathome.org/schema/v0.1/component.schema.json
```

This is the format an LLM agent will read and act on; it should be intelligible in a single pass without consulting other context.

**Exit criteria:**

- [ ] `scripts/arch-validate` committed, executable, no external deps beyond bash/curl/jq.
- [ ] Single-file validates against a known-good and known-bad artifact, both human and `--json` modes.
- [ ] Multi-file mode aggregates failure correctly.
- [ ] Stdin mode (`-`) works.
- [ ] README has a short section showing the dev loop: edit artifact → `arch-validate file` → read errors → fix → re-run.

### 6. Update `docs/architecture-rebuild/02-metaschema.md`

The source doc still describes a single-binary CLI. Rewrite the affected sections to match the locked decisions.

**Sections to revise:**

- "Validator CLI" → "Validation service". Replace the binary description with the endpoint contract from this doc.
- "JSON Schema publication" → confirm the hosted URLs as the canonical reference, remove the line implying patch/minor are arbitrary (state the v0.1-immutable rule).
- "Open questions for v1 finalization" → resolve both open questions (enum location, `producer` declared vs derived).
- "Decisions locked" → add the new locked decisions (hosted endpoint, single Node service, JSON-only schema sources, `ajv` library).

**Exit criteria:**

- [ ] No remaining mentions of "single-binary validator" or "Linux/macOS binary release" in `02-metaschema.md`.
- [ ] Both open questions removed (resolved) or restated as decisions.
- [ ] Link from `02-metaschema.md` to this feature doc for the execution trail.

---

## Exit criteria for the whole phase

Aggregated from the items above and from `00-roadmap.md`'s v1 list:

- [ ] JSON Schema published from this repo, versioned `0.1`, reachable at the URLs in item 4.
- [ ] Validation service running in the container, accepting artifacts at `POST /api/validate`.
- [ ] Producer shell script committed and verified end-to-end against the deployed service.
- [ ] `02-metaschema.md` updated to match what was actually built.
- [ ] nginx fully removed from the container.

Data migration of the existing 145 nodes (the other half of the v1 exit criteria in `00-roadmap.md`) is the next document — `03-data-migration.md` — not this one.
