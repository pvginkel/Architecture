# 04 — Producer protocol

How a repo becomes a producer of architecture data. Defines the artifact shape, the publication mechanism (Jenkins artifacts), cross-producer reference rules (UUIDs canonical, alias hints optional), and the per-producer profile constraints.

The assembly-side counterpart is [`05-collector-and-pipeline.md`](./05-collector-and-pipeline.md). The schema this protocol produces against is [`../features/metaschema-design.md`](../features/metaschema-design.md). The validation service the producer's CI calls is [`../features/validation-service.md`](../features/validation-service.md).

## Producer model

A **producer** is a Jenkins job that, on every successful build, emits one architecture artifact: a YAML file conforming to `schema/v0.1/architecture.schema.yaml`, archived as a Jenkins build artifact at a stable path (`architecture.yaml` at the artifact root). The Architecture repo's pipeline picks up the latest successful build's artifact from each registered producer, merges them, and publishes the consolidated dataset.

Producers do not coordinate with each other. They emit only what they own. Cross-producer references go through UUIDs.

The producer-profile enum (`schema/v0.1/enums/producer-profiles.yaml`) currently lists four: `infra-physical` (Ansible), `cluster-services` (HelmCharts), `images` (DockerImages, mostly v0.2), `application` (per-app repos). Adding a profile requires a PR to the enum.

## Artifact shape

The artifact is a single YAML document conforming to the v0.1 master schema. The two required top-level fields are `schemaVersion` (`"0.1"`) and `producer` (the id of this producer's «Producer» Repository Artifact). Per-kind element arrays are optional.

The full envelope is documented in [`../features/metaschema-design.md`](../features/metaschema-design.md) under "Artifact envelope." See `schema/v0.1/examples/valid-full.yaml` for a worked-out example exercising every element kind.

## Publication

**Where the artifact lives**: a Jenkins build artifact at `architecture.yaml` (root of the archived artifacts).

**Why Jenkins artifacts** rather than committing to a branch or pushing to a registry:

- Jenkins is the source of build truth in this stack; if a build is green, its artifact is canonical.
- Producers don't need write access to a separate data store.
- "Latest successful build" is a built-in Jenkins concept; the Architecture pipeline relies on it.

**Collector access**: the Architecture repo's Jenkinsfile pulls each producer's `architecture.yaml` from Jenkins via the API, scoped to the latest successful build. Producer URLs are enumerated in the Architecture repo's pipeline config; new producers are added by PR. See `05`.

## Producer-side validation (the failing build)

**Requirement** (user, explicit): a producer that emits an invalid artifact must fail its own Jenkins build.

Implementation:

1. Producer's build script runs `arch-validate architecture.yaml`.
2. `arch-validate` POSTs to `https://architecture.webathome.org/api/validate`.
3. Exit code is the build step's exit code: `0` valid, `1` invalid, `2` transport / server error.

The hosted validator (the v2 service) does **per-artifact** validation: schema conformance, the lifecycle conditional rules, the ArchiMate relationship-type enumeration, the relationship triple matrix narrowed to the v0.1 subset. It does **not** check cross-producer references — that's the collector's job because only the collector sees the full merged dataset.

What the per-artifact validator catches (today, against `schema/v0.1/`):

- Schema violations (missing required fields, wrong types, render-only `position` keys).
- ID format violations (kind-specific regexes; UUID-only for instance kinds once the v0.1 schema tightens — see [`../features/metaschema-design.md`](../features/metaschema-design.md) "Pending v0.1 tightening").
- Lifecycle conditional rules (`deprecated` requires `replacedBy` or `retirementBy`; `removed` forbids both).
- Stereotype-specific required attributes (e.g., a «Repository» Artifact must declare `url`, `role`, `owner`).
- Relationship `type` not in the ArchiMate enumeration; relationship triples not permitted by ArchiMate 3.2.

What it does **not** catch (collector concerns, see `05`):

- Whether a referenced UUID exists in the merged dataset.
- Whether the producer is permitted to emit a given element kind under its profile.
- alias-hint divergence (two producers referencing the same UUID with different alias hints).
- Capability/product enum membership (today the per-artifact validator does enforce capability-id existence in `enums/capabilities.yaml` for in-artifact `Capability` documents; cross-referenced capability ids are checked at merge time).

## Cross-producer references — UUIDs and alias hints

**Canonical: UUIDs.** Every cross-producer reference target is a UUIDv4 minted once by the producer that owns the element. Stable. Never re-minted. Never renamed.

This applies to every instance kind: `Node`, `Device`, `SystemSoftware` (instance), `ApplicationComponent` (instance), `Artifact`, `ApplicationService`, `TechnologyService`, `ApplicationInterface`, `TechnologyInterface`, `Grouping`. Curated kinds (`Capability`, `BusinessService`) and `«SoftwareProduct»`-stereotyped product identities use kebab-case enumeration IDs, not UUIDs — those are catalog entries, not instance identities.

**Hint: a human-readable alias.** Producers may optionally provide an `aliasHint` on instance elements: a kebab-case name that says, "this is my preferred local nickname for this thing." The hint exists for diagnostics (so log lines and validation errors say `node:prd-cluster` rather than `node:7f3a2b1c-…`). It is **not** the load-bearing reference; relations always target the UUID.

The collector merges artifacts and runs two related checks:

- **Resolution.** Every `source` and `target` UUID in every `relations` entry must resolve to an element in the merged dataset. Dangling = build failure.
- **Alias-hint divergence.** When multiple producers describe the same element (e.g., Helm references Ansible's `node:7f3a…` cluster and tags its own `aliasHint: node:prd-cluster-helms-view`), the collector compares hints. Same UUID, different hints across artifacts = **warning** (not failure). The merged dataset retains the owner's hint (the one in the artifact whose `producer` field matches the element's `producer` back-pointer); other producers' hints surface in the validation report.

This is intentionally cheap. Naming-convention drift is detected without forcing it to fail every cross-producer reference.

### Bootstrap reference discovery

For the bootstrap cycle (Ansible → Helm → apps), each producer's CI fetches the **latest published merged artifact** from `https://architecture.webathome.org/data/v0.1/architecture.yaml` and reads the UUIDs it needs. The producer's own architecture source pins those UUIDs locally; they don't need to be re-resolved at every build.

Concretely:

- Ansible mints UUIDs for the things it owns and commits them in the Ansible repo (a UUID table next to the architecture source). First publication makes the IDs visible.
- Helm's developer reads the merged dataset (already published from Ansible), grabs the cluster UUIDs they need, and writes them into Helm's architecture source. Subsequent Helm builds re-emit the same UUIDs — they are committed in the Helm repo's architecture source.
- App repos do the same against Helm's emitted Service/Interface UUIDs.

This is "looking up UUIDs from the data plane" but the lookup is a one-time copy by a human; the producer's source is the canonical record after that. The system tolerates Ansible republishing — UUIDs are stable by construction, so the lookup doesn't drift.

## Profile constraints

The producer profile constrains which element kinds an artifact is allowed to declare. The collector enforces this at merge time (per-artifact JSON Schema doesn't, because the schema knows nothing about who's emitting). Violations are merge failures.

### `infra-physical` — Ansible

Owns:

- `Device` — physical hardware (UDM Pro, switches, APs, IoT hardware, the Proxmox servers themselves at the hardware level, the ZFS box).
- `Node` — execution hosts: Proxmox cluster as a hypervisor Node, individual VMs, k8s clusters (prd + dev).
- `SystemSoftware` — VM-installed daemons (OpenBao, keepalived, HAProxy at the OS layer, step-ca-VM, node_exporter).
- `TechnologyService` and `TechnologyInterface` — VM-level service surfaces (OpenBao API at `secrets.home`, the ZFS volume allocator's API, the Proxmox API).
- `Artifact` — the Ansible repo as a `«Repository»` `«Producer»` Artifact; possibly per-role Artifacts.

Edges typically declared: `Assignment` (a daemon assigned to a VM), `Composition` (cluster aggregates its VMs), `Realization` (Service realises a Capability), `Specialization` (instance specialises a «SoftwareProduct» entry).

Forbidden: Helm releases, app pods, container images. Ansible installs the substrate; it doesn't deploy the cluster's workloads.

### `cluster-services` — HelmCharts

Owns:

- `SystemSoftware` (instance) — Helm-deployed running services: Keycloak, shared Postgres, dnsmasq, registry, Jenkins, Gitblit, Grafana, Prometheus, Filebeat, ES/Kibana, RabbitMQ, Mosquitto, External Secrets, step-ca, ingress nginx, the CSI drivers, etc.
- `SystemSoftware` («SoftwareProduct») — software identity entries: `ss:keycloak`, `ss:postgresql`, `ss:nginx`, etc. These are curated kebab IDs (the catalog), distinct from the running instances.
- `ApplicationService`, `TechnologyService`, `ApplicationInterface`, `TechnologyInterface` — every consumption surface those services provide.
- `Artifact` — Helm charts as Artifacts; the HelmCharts repo as the `«Producer»` Artifact.
- `Grouping` — visual clusters (observability stack, media stack, etc.).

References (by UUID) elements owned by `infra-physical` — typically the cluster Node, occasionally specific VMs or VIPs.

Edges typically declared: `Assignment` (running service → cluster Node), `Composition` (chart → contained services), `Realization` (Service → Capability), `Aggregation` (Grouping → members), `Specialization` (instance → «SoftwareProduct»).

Forbidden: physical hardware, VMs, hypervisor, app pods.

### `application` — EI, IoT, Design Assistant, webathome-org, etc.

Owns:

- `ApplicationComponent` — application pods (frontend, backend, worker, job, cronjob — one per distinct runtime identity, not per replica).
- `ApplicationService`, `ApplicationInterface` — internal HTTP APIs, queue names, topic names, bucket names the app owns.
- `Artifact` — the app repo as a `«Producer»` Artifact; possibly per-environment chart Artifacts.

References (by UUID): cluster Services from `cluster-services` (shared Postgres, OIDC issuer, secrets store, queues, etc.), occasionally Nodes from `infra-physical`.

Edges typically declared: `Serving` (frontend served by backend), `Access` (backend → shared Postgres), `Triggering`/`Flow` (publishes/subscribes to a broker), `Specialization` (the app component specialises its `«SoftwareProduct»` catalog entry).

Forbidden: declaring shared infrastructure as its own. If the app needs a shared component (a new platform service), that gets added in `cluster-services` first, then the app references it.

### `images` — DockerImages

Mostly v0.2 work (image identity, build provenance, parent-image graph). For v0.1, the profile exists in the enum and the repo can emit a `«Repository»` `«Producer»` Artifact + perhaps `«SoftwareProduct»` SystemSoftware entries for in-house images, with `sourceRepository` back-pointers to repos in the DockerImages monorepo.

## How a producer integrates (the recipe)

1. **Decide where the source lives.** Hand-maintained YAML in the producer repo (`architecture/architecture.yaml` checked in) is the default. Generated-at-build-time from existing manifests (e.g., Helm `values.yaml` parsed into architecture YAML) is fine where it pays off.
2. **Mint UUIDs.** First integration: generate a UUIDv4 for each element the producer owns; commit them in a UUID table file (`architecture/ids.yaml` or similar). Subsequent: reuse existing IDs; never re-mint.
3. **Look up cross-producer UUIDs.** Pull the current merged artifact (`https://architecture.webathome.org/data/v0.1/architecture.yaml`) once; copy the UUIDs you need into your own source.
4. **Add the validator step to the Jenkinsfile.** `arch-validate architecture.yaml`, fail the build on non-zero exit.
5. **Archive the artifact.** Jenkins `archiveArtifacts artifacts: 'architecture.yaml', fingerprint: true`.
6. **Register with the Architecture pipeline.** PR against the Architecture repo's pipeline config (the list of registered producer Jenkins URLs).

Subsequent merges are automatic.

## Schema version negotiation

Producers pin a schema version at integration time (today: `"0.1"`). The collector accepts artifacts within the configured compatibility window (see [`../features/metaschema-design.md`](../features/metaschema-design.md) "Schema-version compatibility window"). At v0.1 the window contains only `"0.1"`.

When a new schema major lands, each producer updates its pin at its own pace within a stated migration window; the collector accepts the union during the window and rejects the older major afterward.

## What the producer does **not** decide

- Layout, position, colour. Render-only fields are rejected by the schema.
- Which capabilities exist. The capability enum is centralised in `schema/v0.1/enums/capabilities.yaml`; additions require a PR there.
- Which curated `«SoftwareProduct»` identities exist. Same — additions are PRs against the Architecture repo.
- Inclusion rules. The inclusion rule (`02-metaschema.md`) is authoritative; producer judgment doesn't override it.

## Open questions

- **Should `arch-validate` also fetch the current merged artifact and check cross-producer UUIDs locally?** Likely yes as an opt-in flag (`--check-cross-refs`); the per-artifact validator stays cheap. Implementation deferred until at least two producers are emitting.
- **Multiple artifacts per producer?** A repo with multiple deliverables (e.g., separate Helm chart builds) could emit one artifact per chart. The protocol allows it (each is an independent file at a different Jenkins path). The Architecture pipeline treats them as a producer-group. Decide on naming convention if it comes up.
