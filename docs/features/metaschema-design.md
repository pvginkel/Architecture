# Metaschema v0.1 — design

The executable design of the architecture metaschema. Delivers the `schema/v0.1/` package: per-kind schemas, enum files, master artifact wrapper.

Inspiration and rationale: [`docs/architecture-rebuild/02-metaschema.md`](../architecture-rebuild/02-metaschema.md). That doc is the brainstorm; this doc is the spec to execute against. Where they differ, this doc wins; cross-references back to `02` exist for the "why."

This doc is schema-only. The validation service that consumes these schemas is in [`validation-service.md`](./validation-service.md). Data migration of the existing 145 nodes is in [`docs/architecture-rebuild/03-data-migration.md`](../architecture-rebuild/03-data-migration.md).

## Decisions locked

- **JSON Schema dialect:** `https://json-schema.org/draft/2020-12/schema`.
- **Authoring format:** YAML. Files live in the repo as `.yaml`; the service exposes both `.yaml` and a canonical `.json` form at the public URLs.
- **Validator library (downstream concern, called out here):** `ajv` with `ajv-formats`. Schemas must compile under `ajv --strict`.
- **ID formats:**
  - Components: `comp:<uuid4>`.
  - Capabilities: `cap:<kebab-case>` (lowercase letters, digits, hyphens; must start with a letter).
  - Products: `prod:<kebab-case>`.
  - Groups: `group:<uuid4>`.
  - Edges: `edge:<uuid4>`.
- **`additionalProperties: false` on every object schema.** Producers cannot smuggle in render-only or speculative fields.
- **Enum constraints for capability and product references are NOT encoded in the JSON Schema.** They are looked up at validation time against the loaded enum files. This keeps the schema files static while letting the enum lists evolve independently.
- **Edge types, lifecycle states, and producer profiles ARE encoded as JSON Schema enums.** Their value space is small, churn is low, and changes deserve a schema-version bump.
- **The component `producer` field is declared, not derived.** Required on every component.
- **Render-only fields are rejected by schema, not by convention.** No `position`, no `x`/`y`, no hardcoded sizes, no layer assignments anywhere in artifacts.

## Repository layout

```
schema/
  v0.1/
    architecture.schema.yaml     # top-level artifact wrapper
    capability.schema.yaml
    component.schema.yaml
    product.schema.yaml
    edge.schema.yaml
    group.schema.yaml
    enums/
      capabilities.yaml
      products.yaml
      edge-types.yaml
      lifecycle-states.yaml
      producer-profiles.yaml
    examples/
      valid-minimal.yaml
      valid-full.yaml
      invalid-render-field.yaml
      invalid-unknown-capability.yaml
      invalid-uuid.yaml
      invalid-duplicate-edge.yaml
```

The `examples/` directory holds golden artifacts used by the service's test suite and by anyone reading the schemas to understand them. Each example is small, single-purpose, and either valid (`valid-*`) or invalid in one specific way (`invalid-*`).

## Artifact envelope (master schema)

Every artifact submitted to the validator is one document with this shape:

```yaml
schemaVersion: "0.1"
producer: cluster-services        # one of the producer-profiles enum entries
generatedAt: 2026-05-26T14:00:00Z # ISO-8601, optional; informational
capabilities: []                  # array of capability documents (optional)
components: []                    # array of component documents
products: []                      # array of product documents (optional)
edges: []                         # array of edge documents
groups: []                        # array of group documents (optional)
```

- `schemaVersion` is required and must equal the schema version this artifact is being validated against. v0.1 accepts only `"0.1"`.
- `producer` is required and constrains what the artifact may declare — see "Producer profiles" below. The constraint is structural (which arrays may be non-empty, which document IDs may appear) but is enforced at the collector level, not at the per-artifact JSON Schema level. The schema permits any profile to emit any kind; the collector rejects out-of-profile content.
- All document arrays default to empty. An artifact that declares only edges is valid.

## Document kinds

### Capability

Defines a logical role the system needs filled. Curated as a finite enumeration; producers may reference but not declare new capabilities.

```yaml
id: cap:sso
label: Single Sign-On
summary: Centralized identity for browser-based and CLI clients.
lifecycle: active                 # active | deprecated | removed
introduced: 2024-07-12            # ISO-8601 date, required
replacedBy: cap:other             # required iff lifecycle=deprecated AND a replacement exists
retirementBy: 2026-12-31          # required iff lifecycle=deprecated AND no replacement
```

Fields:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^cap:[a-z][a-z0-9-]*$` |
| `label` | string | yes | display string; may change without ID change |
| `summary` | string | yes | one or two sentences |
| `lifecycle` | enum | yes | from `lifecycle-states.yaml` |
| `introduced` | date | yes | first declared in the architecture |
| `replacedBy` | string | conditional | matches `^cap:[a-z][a-z0-9-]*$` |
| `retirementBy` | date | conditional | |

Conditional rules expressed via `if`/`then`/`else` in the schema:

- `lifecycle == deprecated` → exactly one of `replacedBy` or `retirementBy` must be present.
- `lifecycle == removed` → both `replacedBy` and `retirementBy` are forbidden.

### Component

The concrete runtime instance — a Helm release, a VM, a pod. Carries a GUID for stable cross-repo referencing. The bulk of the data in the system is components.

```yaml
id: comp:7f3a2b1c-1234-4abc-9def-1234567890ab
label: Keycloak (prd)
summary: Production Keycloak instance backing all internal apps.
realizes:
  - cap:sso
packagedAs: prod:keycloak
group: group:9c1d2e3f-...         # optional
lifecycle: active
producer: cluster-services
introduced: 2024-09-04
replacedBy: comp:other-uuid       # required iff lifecycle=deprecated AND a replacement exists
retirementBy: 2026-12-31          # required iff lifecycle=deprecated AND no replacement
stats:                             # free-form key/value bag, shape-checked but not value-checked
  sourceRepo: pvginkel/HelmCharts
  version: "24.0.4"
  url: https://auth.webathome.org
```

Fields:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^comp:<uuid4-regex>$` |
| `label` | string | yes | display string |
| `summary` | string | yes | |
| `realizes` | array of cap-id | yes | min 1; "a component without `realizes` is rejected" per 02 |
| `packagedAs` | string | yes | a prod-id; required even when the product is trivial (e.g., bespoke services get their own `prod:*`) |
| `group` | string | no | a group-id |
| `lifecycle` | enum | yes | from `lifecycle-states.yaml` |
| `producer` | enum | yes | from `producer-profiles.yaml`; declared, not derived |
| `introduced` | date | yes | |
| `replacedBy` | string | conditional | matches `^comp:<uuid4-regex>$` |
| `retirementBy` | date | conditional | |
| `stats` | object | no | free-form string→string; render hints, links, version stamps |

Same conditional rules around `lifecycle == deprecated/removed` as Capability.

### Product

The software identity that joins the architecture diagram to the webathome.org stack ticker. Curated enumeration; producers may reference but not declare.

```yaml
id: prod:keycloak
label: Keycloak
summary: Open-source IAM.
lifecycle: active
homepage: https://www.keycloak.org/
logo: keycloak.svg
introduced: 2024-07-12
```

Fields:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | matches `^prod:[a-z][a-z0-9-]*$` |
| `label` | string | yes | |
| `summary` | string | yes | |
| `lifecycle` | enum | yes | |
| `homepage` | uri | no | |
| `logo` | string | no | filename under `viewer/public/logos/` |
| `introduced` | date | yes | |
| `replacedBy` / `retirementBy` | | conditional | as above |

### Edge

Connects two components. Capability and product nodes never appear as edge endpoints — those are derived views.

```yaml
id: edge:1a2b3c4d-...
source: comp:7f3a2b1c-...
target: comp:8a9b0c1d-...
type: authenticates-via
protocol: oidc                    # optional, free-text
criticality: primary              # primary | secondary (default primary)
summary: optional free text
```

Fields:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | `^edge:<uuid4-regex>$` |
| `source` | string | yes | component-id |
| `target` | string | yes | component-id |
| `type` | enum | yes | from `edge-types.yaml` |
| `protocol` | string | no | free-text; render hint |
| `criticality` | enum | no | `primary` (default) or `secondary` |
| `summary` | string | no | |

Cardinality rules (collector-enforced, not schema-enforced because they need merged-dataset context):

- A given `(source, target, type)` triple may appear at most once across the whole merged artifact set.
- Different types between the same pair are allowed.

### Group

A producer-declared logical cluster of components. The viewer collapses groups at higher zoom levels.

```yaml
id: group:9c1d2e3f-...
label: Observability
summary: Logs, metrics, traces.
producer: cluster-services
```

Fields:

| field | type | required | notes |
|---|---|---|---|
| `id` | string | yes | `^group:<uuid4-regex>$` |
| `label` | string | yes | |
| `summary` | string | yes | |
| `producer` | enum | yes | groups cannot span producers |

A component declares its group membership via the component's `group` field, not via group-side enumeration.

## Enums

### `capabilities.yaml`

Curated list of capability IDs the system recognizes. Each entry carries its own metadata so capabilities can be queried without needing them as standalone documents in artifacts.

```yaml
$id: https://architecture.webathome.org/schema/v0.1/enums/capabilities.json
entries:
  - id: cap:sso
    label: Single Sign-On
    lifecycle: active
    introduced: 2024-07-12
  - id: cap:object-storage
    label: Object Storage
    lifecycle: active
    introduced: 2024-07-12
  # … rest of the curated set
```

Initial entries — derived from `02-metaschema.md` examples and the existing 145-node taxonomy — get authored as part of work item 1 below. Capability enum is the gate the user wanted: adding a capability requires a PR to this repo.

### `products.yaml`

Same shape as `capabilities.yaml`. Should align one-to-one with the webathome.org stack ticker (`src/data/stack.ts`). One-time reconciliation pass is part of work item 1.

### `edge-types.yaml`

Closed set; the full list from `02-metaschema.md`:

```yaml
$id: https://architecture.webathome.org/schema/v0.1/enums/edge-types.json
entries:
  - id: depends-on
    description: Generic dependency, when no more specific edge applies. Discouraged.
  - id: routes-to
    description: HTTP, gRPC, TCP traffic.
  - id: authenticates-via
    description: A trusts B for identity.
  # … rest
```

Encoded in the per-kind schema as a JSON Schema `enum` referencing the entry IDs.

### `lifecycle-states.yaml`

```yaml
$id: https://architecture.webathome.org/schema/v0.1/enums/lifecycle-states.json
entries:
  - id: active
    description: Live, referenceable.
  - id: deprecated
    description: Being phased out. Requires replacedBy or retirementBy.
  - id: removed
    description: No longer deployed. Producer still emits the entry until references are gone.
```

### `producer-profiles.yaml`

```yaml
$id: https://architecture.webathome.org/schema/v0.1/enums/producer-profiles.json
entries:
  - id: infra-physical
    description: Ansible-owned hardware, VMs, OS-level installs.
  - id: cluster-services
    description: HelmCharts-owned shared cluster services.
  - id: images
    description: DockerImages-owned image identity and build provenance.
  - id: application
    description: Application repos (EI, IOT, others) — own pods, queues, storage, ingress.
```

## Producer profiles — constraint placement

The "profile constrains what an artifact may declare" rule lives at the collector layer, not the JSON Schema layer. The schema accepts any producer declaring any kind; the collector applies the matrix in `02-metaschema.md` and rejects mismatches.

Rationale: per-artifact JSON Schema validation is the wrong place to express "this producer may only own these node kinds" because it requires knowledge that lives one level up (the matrix in the collector config). Keeping the schema simple here also means a misconfigured producer can still produce a parseable artifact — and get a clear collector-level error rather than a cryptic schema error.

## Inclusion rule

Not enforced by schema (it's a judgment, not a constraint), but documented here so producer authors and reviewers have one place to look:

> A component, edge, queue, storage location, or API belongs in the data **if and only if it has a stable external identity that another component can reach by name.**
>
> **In:** DNS names, pod names, queue names, exchange names, topic names, bucket names, schema/database names, domain names, ingress routes, exposed API paths.
>
> **Out:** Classes, functions, internal methods, screens, in-process modules, environment variables that are not service-reachable identities.
>
> Borderline cases default to **out**.

Source: `02-metaschema.md`, "Inclusion rule." Repeated here verbatim because every producer author will read this doc and many will not read `02`.

## Anti-patterns rejected at validation time

These are catchable at single-artifact JSON Schema time and so live in this design:

- Component without a `realizes` capability (`minItems: 1` on the array).
- Edge whose `source` or `target` doesn't match the component ID regex (catches typo'd or wrong-kind references; existence is still a collector concern).
- Any document with a render-only field (`additionalProperties: false`).
- ID that fails its kind's regex.
- Component with `lifecycle: deprecated` and neither `replacedBy` nor `retirementBy`.
- Component with `lifecycle: removed` and a `replacedBy` or `retirementBy` field present.

Caught only at collector time, listed for completeness:

- Reference to a component GUID that doesn't exist in the merged dataset.
- Two components with the same GUID.
- Multiple edges of the same type between the same pair of components.
- Producer declaring a kind not permitted by its profile.

## Versioning policy

- **`v0.1`** is the initial version. Files at `schema/v0.1/...` are the canonical reference.
- **Patch (0.1 → 0.1.1):** clarifications, descriptions, non-breaking additions. Patches overwrite in place at the same URL; cache TTL on the published files is short (300s) to bound staleness.
- **Minor (0.1 → 0.2):** new optional fields, new enum entries that don't break old artifacts, new edge types. Cuts a new directory `schema/v0.2/`; the old `v0.1/` URLs remain live.
- **Major (0.x → 1.0):** field renames, removed fields, semantic changes. New directory, new URL space.

### Schema-version compatibility window

The validation service accepts artifacts whose `schemaVersion` matches a configured allowlist. The rule:

- **At v0.1:** the service accepts only `"0.1"`. No compatibility window yet because there's only one version. Don't pre-build the multi-version dispatcher.
- **When `v0.2` lands:** the service accepts `["0.1", "0.2"]`. Each compiles against its own schema files.
- **When `v1.0` lands:** the service accepts the current major's minors plus the previous major for **one release cycle** of the previous major (i.e., until `v1.1` ships, `v0.x` is still accepted). After that, the previous major returns `400 Unknown schema-version`.

Implementation: a small list in the service config, not a dynamic policy. When the list changes, that's the deployment that bumps the compatibility window.

## Work items

### 1. Author the enum files

Create all five enum files with their initial entries:

- `capabilities.yaml` — derived from the existing 145-node taxonomy + the canonical capability list from `02-metaschema.md`. Cross-check against the broken `CapabilityId` union in `viewer/src/data/architecture.ts` and rationalize (the current set conflates layer-ish things — `compute`, `delivery` — with real capabilities — `identity`, `observability`).
- `products.yaml` — derived from `viewer/src/data/architecture.ts` and `webathome.org`'s `src/data/stack.ts` (one-time reconciliation; flag mismatches in a comment).
- `edge-types.yaml` — exactly the 13 types listed in `02-metaschema.md`.
- `lifecycle-states.yaml` — `active`, `deprecated`, `removed`.
- `producer-profiles.yaml` — `infra-physical`, `cluster-services`, `images`, `application`.

**Exit criteria:**

- [ ] All five files committed under `schema/v0.1/enums/`.
- [ ] Capability set is sufficient to express every existing node's role (verify by spot-check against the 145 nodes; full migration is `03`'s job).
- [ ] Product set aligns with the stack ticker; mismatches documented.

### 2. Author the per-kind schemas

Five files: `capability.schema.yaml`, `component.schema.yaml`, `product.schema.yaml`, `edge.schema.yaml`, `group.schema.yaml`. Each:

- Declares `$id`, `$schema`, `type: object`, `additionalProperties: false`.
- Enumerates required and optional fields per the tables above.
- Encodes regexes for IDs, the `lifecycle == deprecated` conditional rules, the `lifecycle == removed` forbidden-field rules, and enum references where applicable.
- Carries `description` on every field — these are user-facing docs when JSON Schema tooling renders them.

**Exit criteria:**

- [ ] Each file compiles under `ajv --strict` with no warnings.
- [ ] `additionalProperties: false` confirmed on every object.
- [ ] Conditional rules verified against the example artifacts in step 4.

### 3. Author the master schema (`architecture.schema.yaml`)

The artifact-envelope wrapper. `$ref`s into the five per-kind schemas via `items` constraints on each array. Required top-level fields: `schemaVersion`, `producer`. Optional: `generatedAt`, all five document arrays.

**Exit criteria:**

- [ ] Master compiles standalone via `ajv` after resolving all `$ref`s from the repo.
- [ ] An artifact with only `{schemaVersion, producer}` and empty arrays is valid.

### 4. Author golden example artifacts

Under `schema/v0.1/examples/`:

- `valid-minimal.yaml` — one component, one edge, one capability reference.
- `valid-full.yaml` — exercises every optional field across all five kinds.
- `invalid-render-field.yaml` — component with a `position` field; expected error: `additionalProperties` rejection at the component's path.
- `invalid-unknown-capability.yaml` — component references a `cap:does-not-exist`; expected error: capability not found at validation time (collector-style check the service does at validate time against loaded enums).
- `invalid-uuid.yaml` — component with `id: comp:not-a-uuid`; expected error: pattern mismatch.
- `invalid-duplicate-edge.yaml` — two edges with the same `(source, target, type)`; documented but **not failing** at single-artifact time (this is a collector check). Annotate the example to call out that schema validation passes; collector validation does not.

**Exit criteria:**

- [ ] All examples committed.
- [ ] `valid-*` examples pass `ajv` against the master schema.
- [ ] `invalid-*` examples fail in the expected way (capture expected error JSON pointer in a comment header).

### 5. Self-meta-validate

Every schema file is itself JSON Schema 2020-12. The repo's CI (later, via the validation service's test suite) loads each schema and meta-validates it against `https://json-schema.org/draft/2020-12/schema`. This catches structural mistakes (misspelled keywords, invalid `enum` shapes).

**Exit criteria:**

- [ ] A test in the validation service's suite meta-validates every `schema/v0.1/*.yaml` at startup; service fails to boot if any schema is malformed.

## Exit criteria for the design phase

- [ ] All schema files committed under `schema/v0.1/` (work items 1, 2, 3).
- [ ] All enum files have entries sufficient for the existing 145-node taxonomy.
- [ ] Golden examples committed and behave as specified (work item 4).
- [ ] Schema self-meta-validation wired into the service test suite (work item 5).
- [ ] Versioning policy and compatibility window documented (this doc).

Once these are met, the validation service work in [`validation-service.md`](./validation-service.md) becomes unblocked and the data migration in [`03-data-migration.md`](../architecture-rebuild/03-data-migration.md) has a stable target to migrate to.
