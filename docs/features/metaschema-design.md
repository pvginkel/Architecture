# Metaschema v0.1 — design

The executable design of the architecture metaschema. Delivers the `schema/v0.1/` package: the vendored ArchiMate XSDs, a `subset.yaml` declaring what we use, generated per-kind JSON Schemas, enum files, the master artifact wrapper, and golden examples.

Inspiration and rationale: [`docs/architecture-rebuild/02-metaschema.md`](../architecture-rebuild/02-metaschema.md). That doc is the original brainstorm; this doc is the spec to execute against. Where they differ, this doc wins; cross-references back to `02` exist for the "why" of individual choices.

This doc is schema-only. The validation service that consumes the schemas is in [`validation-service.md`](./validation-service.md). Data migration of the existing 145 nodes is in [`docs/architecture-rebuild/03-data-migration.md`](../architecture-rebuild/03-data-migration.md).

## Reference model: ArchiMate 3.x

The metaschema **is a constrained subset of ArchiMate 3.x**. We adopt The Open Group's vocabulary outright — element kinds, layer assignments, relationship grammar, and the Service / Interface distinction — rather than inventing parallel names. ArchiMate is the user's professional working vocabulary and it cleanly resolves several distinctions the original brainstorm conflated (Capability vs. BusinessService, ApplicationComponent vs. SystemSoftware, Service vs. Interface).

The Open Group's **ArchiMate Model Exchange File Format XSD** is vendored under `schema/v0.1/archimate/` and is the **authoritative source** for:

- The set of valid element type names (the `xsi:type` enumeration in the XSD).
- The set of valid relationship type names.
- The structural base attributes that every element carries (identifier, name, documentation, properties).
- The structural base attributes that every relationship carries (source, target, plus the inherited element base).

The XSDs published by The Open Group are versioned `3.1` and serve **both ArchiMate 3.1 and ArchiMate 3.2** — the exchange format did not change across that revision. See `schema/v0.1/archimate/SOURCE` for the retrieval URLs and date.

What is **not** in the XSD: the per-(source, relation, target) triple matrix from the ArchiMate specification appendices. The XSD treats relationships as untyped IDREF pairs with a type discriminator; it does not enforce which relationship types are valid between which element types.

The matrix is, however, machine-readable from another source: the Archi modelling tool (https://www.archimatetool.com/, MIT-licensed) ships ArchiMate 3.2's full triple matrix as `relationships.xml` + a key-letter dictionary `relationships-keys.xml`. Both files are vendored under `schema/v0.1/archimate/` and parsed by the generator. v0.1 of this metaschema therefore validates element-type names, relationship-type names, **and** the (source-kind, relation-type, target-kind) triple matrix at single-artifact time.

## Locked decisions

- **Authoring format:** YAML. The validation service exposes both YAML and canonical JSON at stable URLs.
- **Source of truth, layered:**
  1. The vendored ArchiMate XSDs are canonical for element kinds, relationship kinds, and structural base attributes.
  2. `schema/v0.1/subset.yaml` declares which element kinds we include for v0.1 plus our custom stereotypes and custom attributes.
  3. Per-kind JSON Schemas under `schema/v0.1/generated/` are **generated** from XSD + `subset.yaml`. They are not hand-authored.
- **Relationships:** the full ArchiMate relationship vocabulary is in scope. `subset.yaml` does not enumerate relationships; the generator extracts the relationship-type enumeration from the XSD and the (source, relation, target) triple matrix from the vendored Archi `relationships.xml`, and emits a `relations.schema.yaml` that accepts exactly the triples permitted by ArchiMate 3.2 between subset-included element kinds.
- **DTAP and lifecycle:** custom attributes layered on top of ArchiMate. ArchiMate's `Plateau` exists for time-state architecture snapshots and is **not** reused for per-element environment tagging — distinct concept.
- **Stereotypes (custom profile on ArchiMate):**
  - `«SoftwareProduct»` on `ApplicationComponent` and `SystemSoftware` — marks product identity (`prod:keycloak`) as distinct from a running instance.
  - `«Repository»` on `Artifact` — source / spec / config repositories.
  - `«Producer»` marker on a `«Repository»` Artifact — the repo emits artifacts into the federation pipeline.
- **Naming:** vocabulary names are not abbreviated. ArchiMate names retained verbatim (`ApplicationComponent`, not `AppComp`).
- **Importability:** v0.1 artifacts are structurally compatible with ArchiMate Exchange XML by construction. A formal YAML↔XML exporter is v0.2; the path is open.
- **Deferred to v0.2:** image identity, build provenance, variant matrices, certificate / rotation tracking, multi-environment rendering.

## v0.1 tightening landed (v3, 2026-05-27)

Two changes from the producer-protocol discussion landed during v3 — but
not exactly as originally framed.

1. **Composite ids for instance kinds.** `Node`, `Device`, `SystemSoftware` (instance), `ApplicationComponent` (instance), `Artifact` (non-stereotyped), `ApplicationService`, `TechnologyService`, `ApplicationInterface`, `TechnologyInterface`, `Grouping` require the composite form `<kind>:<hint>,<uuid4>` at the declaration site. References on relation source/target may use any of three forms: composite, uuid-only, or hint-only (internal-only). Curated kinds (`Capability`, `BusinessService`) and `«SoftwareProduct»` / `«Repository»` / `«Producer»` catalog entries keep bare kebab-case ids.

2. **Hint baked into the id, not a separate `aliasHint` attribute.** The hint portion of the composite id is the diagnostic alias; there is no `aliasHint` field on element schemas. The collector compares the hint portion of every composite reference against the owner's declared hint and warns on divergence.

Two additional cleanups also landed:

3. **`producer:` attribute removed.** Provenance is now expressed as an Association relation synthesised by the collector from the artifact's «Producer» Artifact to each declared element. Producers don't emit those relations explicitly.
4. **`replacedBy:` and lifecycle conditional rules removed.** No more "`deprecated` requires `replacedBy` or `retirementBy`" / "`removed` forbids both". `retirementBy` stays as plain optional informational metadata.

## ArchiMate subset for v0.1

Eleven element kinds across four ArchiMate layers. Renderer colors follow ArchiMate convention (green / blue / pink / yellow).

| Layer | Element kind | Purpose | Concrete examples |
|---|---|---|---|
| Technology (green) | `Node` | Execution host | Proxmox server, VM, Kubernetes cluster, Proxmox cluster, ESP32 device |
| Technology (green) | `Device` | Physical hardware | Switches, APs, IoT hardware, server hardware |
| Technology (green) | `SystemSoftware` | Infra/middleware runtime | A running Keycloak, Postgres, nginx, OpenBao daemon, dnsmasq |
| Technology (green) | `TechnologyService` | Infra consumption surface | Postgres on 5432, OIDC issuer, ZFS volume allocator API, GitHub API |
| Technology (green) | `TechnologyInterface` | Addressable point on a TechnologyService | A queue, topic, OpenBao path, database, CephFS subvolume, hostPath mount |
| Technology (green) | `Artifact` | Deployable bundle / repository content | Helm chart, Ansible role, TF module, source repo, Jenkinsfile |
| Application (blue) | `ApplicationComponent` | User-facing app workload | EI backend pod, EI frontend pod, DA portal, DA Celery worker |
| Application (blue) | `ApplicationService` | App-layer consumption surface | Internal HTTP API between app workloads |
| Application (blue) | `ApplicationInterface` | Addressable point on an ApplicationService | A specific endpoint path |
| Strategy (pink) | `Capability` | Business-architecture role | IAM, observability, secrets-management, messaging, data-store, etc. |
| Business (yellow, optional) | `BusinessService` | What the system delivers to humans | SSO (realized by IAM), self-service tooling |
| Cross-cutting | `Grouping` | Cosmetic clustering; no semantics | Producer-declared logical clusters |

## Stereotypes (v0.1 profile)

ArchiMate supports custom stereotypes natively. v0.1 defines three:

- **`«SoftwareProduct»`** — applicable to `ApplicationComponent` and `SystemSoftware`. Marks an element as a product identity (`Keycloak`, `Postgres`, `EI`) rather than a running instance. Instances reach the product via ArchiMate's `Specialization` relation. Carries `homepage`, `logo`, `sourceRepository`.
- **`«Repository»`** — applicable to `Artifact`. The Artifact is a source / spec / config repository. Carries `url`, `role` (`source` | `spec` | `config`), `languageMix`, `owner`.
- **`«Producer»`** — marker on a `«Repository»` Artifact. The repo emits architecture artifacts into the federation pipeline. Used by the collector to dispatch and authorize.

## Custom attributes (v0.1 profile)

Layered on every element kind via `subset.yaml`. ArchiMate's exchange format allows arbitrary `properties` (string key/value), which is where these land at serialization time; the JSON Schema enforces shape and required-ness.

| Attribute | Type | Required | Applies to | Notes |
|---|---|---|---|---|
| `id` | string | yes | all | The ArchiMate `identifier`. Subset-defined regex per kind. |
| `label` | string | yes | all | The ArchiMate `name`. Display string; may change without ID change. |
| `summary` | string | yes | all | The ArchiMate `documentation`. One or two sentences. |
| `introduced` | ISO-8601 date | yes | all | First declared in the architecture. |
| `lifecycle` | enum | yes | all | `active` \| `deprecated` \| `removed`. |
| `retirementBy` | ISO-8601 date | optional | all | Informational target retirement date. No conditional rule. |
| `environment` | enum | conditional | Node, Artifact, ApplicationComponent, SystemSoftware | `dev` \| `tst` \| `uat` \| `prd`. **Custom attribute, not Plateau.** |
| `cluster` | string | optional | elements scoped to a Kubernetes cluster | Cluster identifier. |
| `stats` | free-form string→string map | optional | all | Non-load-bearing facts: versions, URLs, image tags. Render hints. |

Provenance is no longer a per-element attribute. The artifact's
top-level `producer:` field still names the «Producer» Artifact that
emitted the file; the collector synthesises one Association relation
per declared element from that Artifact to the element, so the
federation graph carries producer back-pointers as real ArchiMate
edges.

Stereotype-specific attributes are carried only when the stereotype applies. The generator validates that no custom attribute name collides with a name reserved by the XSD.

## ID formats

Three id forms exist in v0.1; per-kind regex selects the one(s) acceptable at the declaration site.

| Element kind | ID prefix | Declaration format | Notes |
|---|---|---|---|
| `Node` | `node:` | composite | `node:prd-cluster,7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f` |
| `Device` | `device:` | composite | `device:switch-rack1,…` |
| `SystemSoftware` (instance) | `ss:` | composite | `ss:keycloak-prd,…` |
| `SystemSoftware` («SoftwareProduct») | `ss:` | bare kebab | `ss:keycloak`, `ss:postgresql` |
| `ApplicationComponent` (instance) | `app:` | composite | `app:ei-backend-prd,…` |
| `ApplicationComponent` («SoftwareProduct») | `app:` | bare kebab | `app:electronics-inventory` |
| `ApplicationService` / `TechnologyService` | `svc:` | composite | `svc:oidc-issuer,…` |
| `ApplicationInterface` / `TechnologyInterface` | `if:` | composite | `if:postgres-5432,…` |
| `Artifact` (non-stereotyped) | `art:` | composite | `art:ei-prd-chart,…` |
| `Artifact` («Repository» / «Producer») | `art:` | bare kebab | `art:helmcharts` |
| `Capability` | `cap:` | bare kebab | `cap:iam`, `cap:observability` |
| `BusinessService` | `bsvc:` | bare kebab | `bsvc:single-sign-on` |
| `Grouping` | `grp:` | composite | `grp:identity,…` |

Composite is `<kind>:<hint>,<uuid4>`. On *references* (relation source/target), three forms are accepted: composite, uuid-only (`<kind>:<uuid4>`), or hint-only (`<kind>:<hint>` — internal-only; cross-producer hint-only refs fail at merge time). Bare kebab is used for curated and catalog identities — capabilities, business services, SoftwareProduct/Repository/Producer entries — where the id IS the canonical name.

## Relationships

The full ArchiMate relationship vocabulary is in scope, sourced from the XSD's relationship-type enumeration. v0.1 accepts any of: `Composition`, `Aggregation`, `Assignment`, `Realization`, `Used-By` (`Serving`), `Access`, `Flow`, `Triggering`, `Specialization`, `Association`, `Influence`, `AndJunction`, `OrJunction`.

Relationship usage mapping for common architectural facts:

| Architectural fact | ArchiMate relationship | Source kind → Target kind |
|---|---|---|
| `runs-on` (a pod runs on a cluster) | `Assignment` | ApplicationComponent / SystemSoftware → Node |
| `realizes` (a Service realizes a Capability) | `Realization` | TechnologyService / ApplicationService → Capability |
| `routes-to` (frontend routes to backend) | `Serving` | ApplicationComponent → ApplicationComponent (via Service) |
| `stores-in` (a pod stores data in Postgres) | `Access` | ApplicationComponent → TechnologyService |
| `publishes-to` / `subscribes-to` | `Triggering` + `Flow` | ApplicationComponent ↔ TechnologyInterface |
| `composed-of` (chart contains pods) | `Composition` | Artifact → ApplicationComponent / SystemSoftware |
| `specializes` (an instance specializes a «SoftwareProduct») | `Specialization` | instance → product |
| `delivered-by` (BusinessService is delivered by IAM Capability) | `Realization` | BusinessService ← Capability |
| `aggregated-in` (a Grouping aggregates members) | `Aggregation` | Grouping → any |

The v0.1 generator validates that each relation's `type` is a known ArchiMate relationship type, that its `source` and `target` are subset-included element kinds, **and** that the specific (source-kind, relation-type, target-kind) triple is permitted by ArchiMate 3.2 as encoded in the vendored `schema/v0.1/archimate/relationships.xml`.

## Repository layout

```
schema/v0.1/
  archimate/
    archimate3_Model.xsd                 # vendored from The Open Group
    archimate3_View.xsd
    archimate3_Diagram.xsd
    relationships.xml                    # ArchiMate 3.2 triple matrix (vendored from Archi, MIT)
    relationships-keys.xml               # key-letter dictionary for the matrix
    LICENSE-archi.txt                    # MIT license covering relationships*.xml
    SOURCE                               # retrieval URLs + date
  subset.yaml                            # included element kinds + custom additions
  architecture.schema.yaml               # top-level artifact wrapper (hand-authored)
  generated/                             # generated from XSD + subset.yaml; committed
    node.schema.yaml
    device.schema.yaml
    systemsoftware.schema.yaml
    applicationcomponent.schema.yaml
    applicationservice.schema.yaml
    applicationinterface.schema.yaml
    technologyservice.schema.yaml
    technologyinterface.schema.yaml
    artifact.schema.yaml
    capability.schema.yaml
    businessservice.schema.yaml
    grouping.schema.yaml
    relations.schema.yaml                # accepts any XSD relationship type
  enums/
    capabilities.yaml
    lifecycle-states.yaml
    environments.yaml
    producer-profiles.yaml
  examples/
    valid-minimal.yaml
    valid-full.yaml
    invalid-additional-property.yaml
    invalid-malformed-id.yaml
    invalid-unknown-relationship-type.yaml

tooling/
  pyproject.toml                         # Poetry; xmlschema + jsonschema + pyyaml
  generate.py                            # XSD + subset.yaml → schema/v0.1/generated/
  validate.py                            # ajv wrapper for examples + CI
```

## Artifact envelope (master schema)

Every artifact submitted to the validator is one document with this shape:

```yaml
schemaVersion: "0.1"
producer: art:helmcharts-repo            # a «Producer» «Repository» Artifact id
generatedAt: 2026-05-27T14:00:00Z        # ISO-8601, optional; informational
nodes: []                                # arrays per element kind (all optional)
devices: []
systemSoftware: []
applicationComponents: []
applicationServices: []
applicationInterfaces: []
technologyServices: []
technologyInterfaces: []
artifacts: []
capabilities: []
businessServices: []
groupings: []
relations: []                            # {id, source, target, type}
```

- `schemaVersion` is required and must equal `"0.1"` for v0.1 artifacts.
- `producer` is required and matches an Artifact id stereotyped as «Producer».
- All element-kind arrays default to empty.
- `relations` carries the relationship documents. The `type` field is validated against the XSD's relationship-type enumeration.

## Schema generation flow

1. The vendored `archimate3_Model.xsd` is parsed by `tooling/generate.py` (using the `xmlschema` Python library).
2. The generator extracts the enumerations of element types and relationship types.
3. The generator loads `subset.yaml` and validates that every element kind named there exists in the XSD enumeration, and that custom attribute names do not collide with names reserved by the XSD (`identifier`, `name`, `documentation`, `properties`, `source`, `target`).
4. For each subset-included element kind, the generator emits a per-kind JSON Schema under `schema/v0.1/generated/`. Each schema includes:
   - `additionalProperties: false`
   - `description` on every field
   - `id`/`label`/`summary`/`introduced` (mapped from ArchiMate identifier/name/documentation)
   - All custom attributes from `subset.yaml`
   - Stereotype conditional rules (required stereotype-specific attributes when a stereotype is set; forbidden stereotype-specific attributes when no stereotype is set)
   - The ID regex for the kind (composite `<kind>:<hint>,<uuid4>` for instance kinds; bare kebab for curated / catalog kinds)
5. The generator parses the vendored `relationships.xml` and `relationships-keys.xml`, expands the key-letter dictionary into full relationship type names, restricts the resulting triple matrix to source/target kinds in our subset, and emits `relations.schema.yaml` encoding the allowed `(source-kind, relation-type, target-kind)` triples.
6. Generated files are committed. CI re-runs the generator and gates on a clean diff.

## Anti-patterns rejected at validation time

These are catchable at single-artifact JSON Schema time:

- Any document with a render-only field (`additionalProperties: false`).
- ID that fails its kind's regex (composite form mandatory at instance-kind declarations).
- A stereotype-bearing element missing its stereotype-specific required attributes (e.g., a «Repository» Artifact without `url`/`role`/`owner`).
- An element carrying stereotype-specific attributes without setting the stereotype.
- A `relation` entry whose `type` is not a known ArchiMate relationship type.

Caught only at collector time, listed for completeness:

- Reference to an element id that doesn't exist in the merged dataset (any of the three forms; cross-producer hint-only refs fail here too).
- Reference to a `removed`-lifecycle element (fail) or `deprecated` (warning).
- Capability reference not in `enums/capabilities.yaml`.
- Two elements with the same id across producers (real ownership conflict).
- Relation `(source-kind, type, target-kind)` triple not permitted by ArchiMate 3.2 (the collector enforces the matrix for every relation, in-artifact and cross-artifact).
- Hint divergence on composite references (same UUID, differing hint portion — warning, not failure).
- A Grouping declared without any Aggregation member, or that aggregates an element owned by a different producer.

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

## Versioning policy

- **`v0.1`** is the initial version. Files at `schema/v0.1/...` are the canonical reference.
- **Patch (0.1 → 0.1.1):** clarifications, descriptions, non-breaking additions. Patches overwrite in place at the same URL; cache TTL on the published files is short (300s) to bound staleness.
- **Minor (0.1 → 0.2):** new optional fields, new enum entries that don't break old artifacts, additional ArchiMate element kinds brought into the subset, addition of the triple matrix. Cuts a new directory `schema/v0.2/`; the old `v0.1/` URLs remain live.
- **Major (0.x → 1.0):** field renames, removed fields, semantic changes. New directory, new URL space.

### Schema-version compatibility window

The validation service accepts artifacts whose `schemaVersion` matches a configured allowlist:

- **At v0.1:** the service accepts only `"0.1"`. No compatibility window yet because there's only one version.
- **When `v0.2` lands:** the service accepts `["0.1", "0.2"]`. Each compiles against its own schema files.
- **When `v1.0` lands:** the service accepts the current major's minors plus the previous major for **one release cycle** of the previous major. After that, the previous major returns `400 Unknown schema-version`.

Implementation: a small list in the service config, not a dynamic policy. When the list changes, that's the deployment that bumps the compatibility window.

## Work items

### 1. Vendor the ArchiMate 3.x XSDs

Done. See `schema/v0.1/archimate/` and `SOURCE` for retrieval details.

### 2. Author `schema/v0.1/subset.yaml`

A single document declaring:

- The list of included element kinds with their ArchiMate layer.
- The applicable stereotype set for each kind.
- The ID regex for each kind.
- The shared custom-attribute set (applied to every kind).
- Stereotype definitions (the attributes added when each stereotype applies).
- Inline JSON Schema for the subset document itself, at the top.

**Exit criteria:**

- [ ] `subset.yaml` parses and self-validates against its inline schema.
- [ ] Every element kind named matches an XSD element-type enumeration value.
- [ ] No custom attribute name collides with an XSD-reserved name (`identifier`, `name`, `documentation`, `properties`, `source`, `target`).

### 3. Build `tooling/generate.py`

Python (Poetry-managed). Reads the XSD via `xmlschema`. Loads `subset.yaml`. Validates the subset against XSD-derived metadata. Emits per-kind JSON Schemas + `relations.schema.yaml`.

**Exit criteria:**

- [ ] `poetry run python tooling/generate.py` is idempotent (CI re-run is a no-op).
- [ ] Each generated file compiles under `ajv --strict` with no warnings.
- [ ] `additionalProperties: false` confirmed on every generated object.

### 4. Author `schema/v0.1/architecture.schema.yaml`

The artifact-envelope wrapper. `$ref`s into the generated per-kind schemas via `items` constraints on each array. Required top-level fields: `schemaVersion`, `producer`. Optional: `generatedAt`, all twelve element-kind arrays, the `relations` array.

**Exit criteria:**

- [ ] Master compiles standalone via `ajv` after resolving all `$ref`s from the repo.
- [ ] An artifact with only `{schemaVersion, producer}` and empty arrays is valid.

### 5. Author the enum files

Under `schema/v0.1/enums/`:

- `capabilities.yaml` — coarse business-arch level: `cap:iam`, `cap:observability`, `cap:secrets-management`, `cap:messaging`, `cap:data-store`, `cap:ingress`, `cap:dns`, `cap:pki`, `cap:object-storage`, `cap:shared-filesystem`, `cap:block-storage`, `cap:metrics`, `cap:logging`. Each entry: `id`, `label`, `summary`, `lifecycle`, `introduced`.
- `lifecycle-states.yaml` — `active`, `deprecated`, `removed`.
- `environments.yaml` — `dev`, `tst`, `uat`, `prd`.
- `producer-profiles.yaml` — initial set: `ansible`, `helmcharts`, `dockerimages`, plus an `application` slot for individual app repos.

**Exit criteria:**

- [ ] All four files committed.
- [ ] Capability set is sufficient to express every existing node's role (verify by spot-check against the 145 nodes; full migration is `03`'s job).

### 6. Author golden example artifacts

Under `schema/v0.1/examples/`:

- `valid-minimal.yaml` — one Node, one SystemSoftware, one TechnologyService, one capability reference.
- `valid-full.yaml` — exercises every subset element kind and a representative relationship of each type.
- `invalid-additional-property.yaml` — element with a `position` field. Expected error: `additionalProperties` rejection.
- `invalid-malformed-id.yaml` — element with `id: node:Bad_ID`. Expected error: composite-id pattern mismatch.
- `invalid-unknown-relationship-type.yaml` — `relations` entry with `type: HypotheticalRelationship`. Expected error: not in XSD enumeration.

(Cross-cutting failure modes like dangling references, capability-enum
violations, duplicate ids, cross-producer Groupings, etc. are exercised
at merge time by the collector fixture set under
`tooling/tests/fixtures/`, not by per-artifact `arch-validate`.)

**Exit criteria:**

- [ ] All examples committed with a header comment naming the expected JSON pointer of the validation error.
- [ ] `valid-*` examples pass `ajv` against the master schema.
- [ ] `invalid-*` examples fail in the expected way.

### 7. Self-meta-validate

Every schema file is itself JSON Schema 2020-12. The repo's CI (later, via the validation service's test suite) loads each schema and meta-validates it against `https://json-schema.org/draft/2020-12/schema`. This catches structural mistakes.

**Exit criteria:**

- [ ] A test in the validation service's suite meta-validates every `schema/v0.1/*.yaml` at startup; service fails to boot if any schema is malformed.

## Exit criteria for the design phase

- [ ] All schema files committed under `schema/v0.1/` (work items 2, 3, 4, 5).
- [ ] All enum files have entries sufficient for the existing 145-node taxonomy.
- [ ] Golden examples committed and behave as specified (work item 6).
- [ ] Schema self-meta-validation wired into the service test suite (work item 7).
- [ ] Versioning policy and compatibility window documented (this doc).

Once these are met, the validation service work in [`validation-service.md`](./validation-service.md) becomes unblocked and the data migration in [`03-data-migration.md`](../architecture-rebuild/03-data-migration.md) has a stable target.
