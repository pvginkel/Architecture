# Architecture validation service

This container is the runtime side of the `webathome.org` architecture
metaschema. It hosts the v0.1 JSON Schemas, validates submitted architecture
artifacts via `POST /api/validate`, and serves the diagram viewer at `/viewer/`.

Producers (Ansible, HelmCharts, EI, IoT, …) emit one `architecture.yaml` per
build. Each producer's CI runs `arch-validate.py` against this service, fails the
build on non-zero exit, and archives the artifact for the Architecture
pipeline's collector to pick up.

## `POST /api/validate`

```
POST https://architecture.webathome.org/api/validate
Content-Type: application/json | application/yaml | text/yaml
Body: artifact in the matching format (≤ 5 MiB)
```

The artifact's top-level `schemaVersion` selects the validator. v0.1 accepts
only `"0.1"`; any other value returns `400`.

| status | meaning |
|---|---|
| `200` with `{"valid":true,...}` | artifact passes schema + triple matrix |
| `200` with `{"valid":false,"errors":[...]}` | one or more validation errors |
| `400` | unparseable body, missing/unknown `schemaVersion` |
| `415` | `Content-Type` other than the three above |
| `500` | server bug |

HTTP status is for request handling. The `valid` field is the validation
outcome — both pass and fail return `200`.

### Success

```json
{
  "valid": true,
  "schemaVersion": "0.1"
}
```

### Failure

Each error is normalised to a single LLM-friendly shape. The `path` is a JSON
Pointer into the submitted artifact, the `value` is extracted at that path so
the reader doesn't have to re-fetch it, and `schemaUrl` points at the most
specific schema or enum file relevant to the error.

```json
{
  "valid": false,
  "schemaVersion": "0.1",
  "errors": [
    {
      "path": "/nodes/0/id",
      "keyword": "pattern",
      "message": "value 'Node_BadId' does not match the required pattern /^node:[a-z][a-z0-9-]*,[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/",
      "value": "Node_BadId",
      "schemaUrl": "https://architecture.webathome.org/schema/v0.1/generated/node.schema.json",
      "hint": "see the schema's pattern for the exact rule"
    }
  ]
}
```

The service also enforces the ArchiMate 3.2 (source-kind, type, target-kind)
matrix on every relation whose endpoints are present in the submitted
artifact. Cross-producer references (ids not present locally) are skipped —
the Architecture pipeline's collector enforces them at merge time. Matrix
violations are reported with `keyword: "x-allowedTriples"`.

## Merged-dataset endpoints

The Architecture pipeline runs the federation collector (`tooling/collect.py`)
during the image build, merges every registered producer's last-successful
`architecture.yaml` into a single consolidated dataset, and bakes the three
output files into the container. The validation service serves them
verbatim from disk.

| URL | content |
|---|---|
| `/data/v0.1/architecture.yaml` | merged dataset (YAML) — every element kind, every relation, derived `groupings` and `capabilityRealizations` maps |
| `/data/v0.1/architecture.json` | same content, canonical JSON |
| `/data/v0.1/validation-report.json` | `summary` + `warnings[]` + `divergences[]` for the last successful pipeline run |

Errors fail the pipeline before emission, so the report never carries
errors — only non-fatal observations (deprecated-target references,
alias-hint divergence across producers, etc.). The Jenkinsfile also
archives `validation-report.json` as a Jenkins build artifact for
historical traceability.

## Schema URLs

Every schema is served at both `.yaml` (the canonical authoring form) and
`.json` (the canonical JSON Schema form). Use whichever your tooling prefers.

| URL | content |
|---|---|
| `/schema/v0.1/architecture.schema.yaml` | top-level artifact envelope |
| `/schema/v0.1/subset.schema.yaml` | meta-schema for `subset.yaml` |
| `/schema/v0.1/generated/<kind>.schema.yaml` | per-kind element schemas (node, applicationcomponent, …) |
| `/schema/v0.1/generated/relations.schema.yaml` | relation schema + `x-allowedTriples` matrix |
| `/schema/v0.1/enums/capabilities.yaml` | curated capability catalogue |
| `/schema/v0.1/enums/lifecycle-states.yaml` | lifecycle enum |
| `/schema/v0.1/enums/environments.yaml` | environment enum |
| `/schema/v0.1/enums/producer-profiles.yaml` | producer-profile catalogue |
| `/schema/v0.1/archimate/archimate3_Model.xsd` | vendored ArchiMate 3.2 XSD |
| `/schema/v0.1/archimate/relationships.xml` | Archi relationship matrix (source) |

All responses set `Access-Control-Allow-Origin: *` and
`Cache-Control: public, max-age=300`.

## End-to-end curl example

```bash
cat > artifact.yaml <<'EOF'
schemaVersion: "0.1"
producer: art:my-repo

artifacts:
  - id: art:my-repo
    label: My repo
    summary: Producer artifact for my repo.
    introduced: 2026-05-27
    lifecycle: active
    stereotype: Producer
    url: https://github.com/example/my-repo
    role: source
    owner: Example Owner
EOF

curl -sS \
  -H 'Content-Type: application/yaml' \
  --data-binary @artifact.yaml \
  https://architecture.webathome.org/api/validate \
  | jq .
```

## `arch-validate.py` CLI

The dev-facing artifact. A producer repo drops the file into its own
`scripts/` directory and runs it in CI.

```bash
# from a producer repo
./scripts/arch-validate.py architecture.yaml
./scripts/arch-validate.py dev.architecture.yaml prd.architecture.yaml
cat architecture.yaml | ./scripts/arch-validate.py -      # stdin
./scripts/arch-validate.py --json architecture.yaml       # raw endpoint JSON
./scripts/arch-validate.py --quiet architecture.yaml      # suppress OK lines
```

Exit codes: `0` valid, `1` invalid, `2` transport/server error.

Override the endpoint for local testing:

```bash
ARCHITECTURE_VALIDATE_URL=http://localhost:8080/api/validate \
  ./scripts/arch-validate.py artifact.yaml
```

The script is a single-file Python 3 program that uses only the standard
library — runs on any `python:slim` image or system `python3`, no `pip
install` step. Updates are coordinated by re-copying from this repo
(`scripts/arch-validate.py`).

## `$schema` pragma

For editor / IDE schema-completion (VS Code's YAML extension, IntelliJ's JSON
Schema mappings, etc.), reference the envelope schema at the top of your
artifact:

```yaml
# yaml-language-server: $schema=https://architecture.webathome.org/schema/v0.1/architecture.schema.json
schemaVersion: "0.1"
producer: art:my-repo
# …
```

The schema URL is stable; only the v0.1 immutability rule applies.

## Schema-change requests

To add a capability id, a relation kind, a stereotype, or any other vocabulary
extension: open a PR against this repo
([`pvginkel/Architecture`](https://github.com/pvginkel/Architecture)) editing
the relevant file under `schema/v0.1/`:

- New capability → `schema/v0.1/enums/capabilities.yaml`
- New producer profile → `schema/v0.1/enums/producer-profiles.yaml`
- New element kind / new attribute on an existing kind → `schema/v0.1/subset.yaml`
  (the generator rebuilds `schema/v0.1/generated/*.yaml`)
- New allowed relation triple → adjust `schema/v0.1/subset.yaml`'s subset of
  the ArchiMate matrix; the generator regenerates `relations.schema.yaml`.

After editing, run the generator and validator locally:

```bash
cd tooling && poetry run python generate.py
cd tooling && poetry run python validate.py meta
cd tooling && poetry run python validate.py ../schema/v0.1/examples/valid-full.yaml
```

CI on this repo runs the same checks plus the service's vitest suite.
