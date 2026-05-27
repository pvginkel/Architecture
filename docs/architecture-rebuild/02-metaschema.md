# 02 — Metaschema (v1, brainstorm — superseded)

> **Status: original brainstorm, superseded 2026-05-26.**
>
> The metaschema discussion converged on adopting **ArchiMate 3.x** as the reference model, with a small custom profile (three stereotypes, one set of custom attributes) layered on top. The kinds, IDs, edge vocabulary, validator-CLI shape, and several decisions in this doc are **not** what landed.
>
> The executed spec is [`../features/metaschema-design.md`](../features/metaschema-design.md). The schema package, generated per-kind JSON Schemas, enums, examples, and tooling all live under `schema/v0.1/` and `tooling/`. The validator is a hosted service, not a standalone binary — see [`../features/validation-service.md`](../features/validation-service.md).
>
> What in this doc *is* still load-bearing (carried verbatim into the executed spec): the lifecycle three-state model (`active`/`deprecated`/`removed`), the inclusion rule, the rationale for splitting capability / implementation / product, and the producer-profile distinction.
>
> Read this doc as historical context for *why* the decisions in the executed spec are what they are. Where this doc conflicts with `metaschema-design.md`, the latter wins.

---

Lock the schema before any data migration or federation work. This document defines the model; `03-data-migration.md` applies it to the current 145 nodes; `04-producer-protocol.md` defines what each producer is allowed to emit against it.

## Core model: three node kinds

The current single-`node` model conflates capability, implementation, and product. Split into three:

| Kind | Purpose | ID space | Example |
|---|---|---|---|
| **Capability** | Logical role; what the system needs done. | `cap:<kebab>` enumeration. | `cap:sso`, `cap:message-broker`, `cap:object-storage`, `cap:secrets`, `cap:dns`. |
| **Component** | Concrete runtime instance; what is actually deployed. | `comp:<guid>`. | A specific Keycloak release running in the cluster; one specific Postgres database; one specific RabbitMQ broker. |
| **Product** | The software identity. Joins the diagram to the stack ticker. | `prod:<kebab>` enumeration. | `prod:keycloak`, `prod:postgresql`, `prod:rabbitmq`. |

A component **realizes** one or more capabilities and is **packaged-as** one product. These are structural relations, not graph edges (see Edges below).

This split is what unblocks the Keycloak/SSO confusion: `comp:7f3a...` is labeled "Keycloak (prd)", realizes `cap:sso`, packaged-as `prod:keycloak`. The diagram filter chooses which kind to display.

## Stable IDs and lifecycle

### Components

Components carry **GUIDs**, minted once by the producer that first declares them. The label can change freely; the ID never does.

- Producers mint a GUID locally (UUIDv4) when they declare a new component, and store it next to the component definition in their own repo.
- The architecture repo never mints component GUIDs.
- A GUID is the only stable handle for cross-repo references.

### Capabilities and products

Capabilities and products use **human-readable kebab-case** enumeration IDs, defined in the schema repo. New entries require a PR to the architecture repo. This is the bottleneck the user wanted: producers cannot invent new capability names ad-hoc.

### Lifecycle states

Every component declaration carries a lifecycle state:

| State | Meaning | Collector behavior |
|---|---|---|
| `active` | Live, referenceable. | Renders normally. |
| `deprecated` | Still live but being phased out. Requires `replaced-by: <comp-guid>` if a replacement exists, otherwise `retirement-by: <iso-date>`. | Renders with deprecated styling. References to it produce a **warning** in the collector report. |
| `removed` | No longer deployed. Producer still emits the entry so cross-references resolve gracefully during transition. After one collector cycle with zero references, the producer may delete the entry. | Does not render. References to it produce a **build failure**. |

This three-state model is the answer to "renames will break everything." It also covers the phpMyAdmin case (set to `removed`, let dangling references surface, then delete).

Capability and product enums use the same lifecycle states, applied at the enum-entry level.

## Edges

Edges connect components to components. (Capability/product nodes appear in the graph only via aggregation/rollup at view time, never as edge endpoints in the source data.)

### Edge types

Replace the current ad-hoc list with a structured set:

| Type | Direction | Use |
|---|---|---|
| `depends-on` | A → B | Generic dependency, when no more specific edge applies. Discouraged; specify when possible. |
| `routes-to` | A → B | HTTP, gRPC, TCP traffic. Ingress to service, service to service. |
| `authenticates-via` | A → B | A trusts B for identity (e.g., app → Keycloak component). |
| `gets-secrets-from` | A → B | A retrieves secrets from B (e.g., pod → OpenBao via external-secrets). |
| `stores-in` | A → B | A persists data in B (pod → Postgres, pod → bucket). |
| `publishes-to` | A → B | A writes messages to a queue/topic/exchange B. |
| `subscribes-to` | A → B | A reads from a queue/topic B. |
| `runs-on` | A → B | Placement / hosting (pod runs on cluster, cluster runs on VMs, VMs run on Proxmox). |
| `builds` | A → B | A produces B as a build artifact (Jenkins → image, Kaniko → image). |
| `deploys` | A → B | A is the agent that deploys B (Ansible → VM config, ArgoCD/Helm → release). |
| `pulls-image` | A → B | A consumes image B at runtime. |
| `observes` | A → B | A scrapes/collects telemetry from B (Prometheus → pod). |

Producers may not invent new edge types. Adding one requires a schema PR.

### Edge attributes

Edges carry optional attributes the renderer can use for filtering and styling:

- `protocol`: free-text (`http`, `grpc`, `amqp`, `nfs`, `s3`, …). Searchable.
- `criticality`: `primary` / `secondary`. Replaces current `strength`. Primary edges render solid, secondary dashed.
- `direction`: implicit in source/target; no separate field.

### Cardinality

Many edges from one source to many targets is normal (a Postgres has many consumers). Multi-edges between the same pair (same type) are not allowed and the validator rejects them. Multi-edges of different types between the same pair are allowed (e.g., a pod both `gets-secrets-from` and `authenticates-via` Keycloak — wait, those go to different components; the rule still holds).

## Producer profiles

Each producer repo declares a **profile**. The profile constrains which node types it can emit. The collector enforces this.

| Profile | Owns | May reference | Forbidden to declare |
|---|---|---|---|
| `infra-physical` (Ansible) | VMs, hypervisor hosts, physical network devices, OS-level installs. | Products. | Helm releases, app pods, images. |
| `cluster-services` (HelmCharts) | Helm releases deployed to the cluster: shared databases, brokers, identity, observability, ingress. The SSOT for cluster-scoped stable IDs. | Products, capabilities, infra components. | Physical hardware, app pods. |
| `images` (DockerImages) | Image identity, build provenance, source-repo linkage. | Products. | Runtime components. |
| `application` (EI, IOT, other app repos) | Their own pods, APIs, ingress routes, declared queues, declared storage paths. | Cluster-services components, images, capabilities, products. | Anything outside their own deployment. |

A producer that needs to emit something its profile forbids is a sign the profile is wrong or the schema needs a new profile. PR territory, not workaround territory.

## Groups

Producers may declare **groups**: logical clusters of components they own. The viewer collapses groups into a single node at higher zoom levels or under capability-only filters.

- Group ID: `group:<guid>` minted by the producer.
- A component declares zero or one group memberships.
- Groups have a label and a brief summary.
- Groups cannot span producers. (Cross-producer grouping is a view-time concern, not a data-time concern.)

Example: HelmCharts emits one group for the observability stack containing Prometheus, Grafana, Filebeat, Kibana components. At capability-view zoom, this collapses to one "Observability" node.

## Inclusion rule (the "non-trivial" definition)

A component, edge, queue, storage location, or API belongs in the data **if and only if it has a stable external identity that another component can reach by name**.

Concretely:

- **In:** DNS names, pod names, queue names, exchange names, topic names, bucket names, schema/database names, domain names, ingress routes, exposed API paths.
- **Out:** Classes, functions, internal methods, screens, in-process modules, environment variables that are not service-reachable identities.

Borderline cases default to **out**. The diagram's value comes from being intelligible; granularity does not.

## Fields per node kind

### Capability

```yaml
id: cap:sso
label: Single Sign-On
summary: Centralized identity for browser-based and CLI clients.
lifecycle: active
introduced: 2024-07-12
```

### Component

```yaml
id: comp:7f3a2b1c-...
label: Keycloak (prd)
summary: Production Keycloak instance backing all internal apps.
realizes: [cap:sso]
packaged-as: prod:keycloak
group: group:9c1d...           # optional
lifecycle: active
producer: cluster-services
introduced: 2024-09-04
stats:
  source-repo: pvginkel/HelmCharts
  version: "24.0.4"
  url: https://auth.webathome.org
```

### Product

```yaml
id: prod:keycloak
label: Keycloak
summary: Open-source IAM.
lifecycle: active
homepage: https://www.keycloak.org/
logo: keycloak.svg
```

### Edge

```yaml
id: edge:<guid>
source: comp:<guid>
target: comp:<guid>
type: authenticates-via
protocol: oidc
criticality: primary
summary: optional free text
```

### Group

```yaml
id: group:9c1d...
label: Observability
summary: Logs, metrics, traces.
producer: cluster-services
```

## Render-only fields are forbidden in data

The schema describes the system, not the diagram. The following are removed from data and not accepted by the validator:

- `position` (the dead `x, y` in the current data).
- Hardcoded sizes, colors, z-order.
- Layer assignments (replaced by capability-derived rendering decisions).
- Any field that affects only the picture and not the system being described.

Render concerns live in the viewer (auto-layout, filter rules, named views).

## JSON Schema publication

The schema is published as JSON Schema from the new repo:

- Versioned: `schema/v0.1/architecture.schema.json`, `schema/v0.1/enums/*.json`.
- Served from the architecture container at `https://architecture.webathome.org/schema/v0.1/architecture.schema.json` (and the container hosts schemas at stable URLs for every published version).
- The schema repo itself is the SSOT; the container is the CDN.

Schema version bumps:
- **Patch (0.1 → 0.1.1):** clarifications, descriptions, non-breaking additions.
- **Minor (0.1 → 0.2):** new optional fields, new enum values, new edge types.
- **Major (0.x → 1.0, 1.x → 2.0):** field renames, removed fields, semantic changes.

Producers declare the schema version they emit against in the artifact's top-level `schema-version` field. The collector accepts artifacts within a configured compatibility window (probably "latest minor of the current major").

## Validator CLI

Distribute a single-binary validator:

- `architecture-validate <path-to-artifact.json>` — validates against the published schema.
- Exit codes: `0` valid, `1` invalid, `2` infrastructure error.
- Output: machine-readable JSON to stdout, human-readable to stderr.
- Available as a published binary release for Linux/macOS and as a Docker image for CI.

Implementation: thin wrapper around a mature JSON Schema validator. No bespoke schema engine.

Producer CI uses this; failure fails the producer's Jenkins build (the user's stated requirement). See `04-producer-protocol.md`.

## Anti-patterns the schema explicitly rejects

- A component without a `realizes` capability. (Forces explicit thinking about what role the thing plays.)
- A component declaring its own capabilities ad-hoc. (Must reference an enumerated `cap:*`.)
- An edge whose endpoints aren't both components.
- A component declared by a producer outside its profile.
- A reference to a component GUID that doesn't exist in the merged dataset. (Dangling; v3-enforced as build failure.)
- Two components with the same GUID. (Collector rejects the merge.)

## Decisions locked

- **GUID format:** UUIDv4.
- **Schema language:** raw JSON Schema. Revisit a DSL (TypeSpec, CUE) only if hand-maintenance becomes painful.

## Open questions for v1 finalization

- **Where does the capability/product enum live in the repo?** Probably `schema/v0.1/enums/capabilities.yaml` and `products.yaml`, with the JSON Schema referencing them. Concrete during v1 execution.
- **Component `producer` field — derived or declared?** If artifacts arrive in profile-named paths in Jenkins (e.g., `architecture/cluster-services/*.json`), `producer` is derivable. Declaring it explicitly is more robust to repo reorganization. Lean declared.
