# 04 — Producer protocol (v2 spec, v3 rollout)

How a repo becomes a producer of architecture data. Defines the artifact shape, the publication mechanism, the validation contract, and the per-producer profile constraints.

## Producer model

A **producer** is a Jenkins job that, on every successful build, emits one architecture artifact: a JSON file conforming to the schema for its declared profile, archived as a Jenkins build artifact at a stable path. The architecture repo's collector picks up the latest successful build's artifact from each producer, merges them with any remaining hand-authored data, and rebuilds the diagram.

Producers know nothing about each other. They emit only what they own. Cross-producer references go through stable component GUIDs.

## Artifact shape

Single JSON file per producer per build. Top-level shape:

```json
{
  "schema-version": "0.1",
  "producer": "cluster-services",
  "producer-repo": "pvginkel/HelmCharts",
  "producer-commit": "abc123...",
  "generated-at": "2026-05-26T14:32:00Z",
  "capabilities": [],
  "products": [],
  "components": [...],
  "edges": [...],
  "groups": [...]
}
```

- `schema-version` controls compatibility (see `02-metaschema.md`).
- `producer` declares the profile and constrains what fields are valid (see profile table below).
- `producer-repo` and `producer-commit` make the artifact traceable from the rendered diagram back to source.
- `capabilities` and `products` are usually empty in producer artifacts — those enums live in the architecture repo. Producers may *propose* additions in their artifact, but the collector treats unrecognized enum values as a validation failure (i.e., it doesn't auto-extend the enums). New enum entries are PR-driven.

## Publication

**Where the artifact lives**: a Jenkins build artifact at a stable path, e.g., `architecture.json` at the root of the archived artifacts.

**Why Jenkins artifacts** rather than committing to a branch or pushing to a registry:
- Jenkins is the source of build truth in this stack; if a build is green, its artifact is canonical.
- Producers don't need write access to a separate data store.
- Latest-successful-build is a built-in Jenkins concept.

**Collector access**: the architecture repo's pipeline pulls each producer's `architecture.json` from Jenkins via the API, scoped to the latest successful build. See `05-collector-and-pipeline.md`.

## Producer-side validation (the failing build)

**Requirement** (user, explicit): a producer that emits an invalid artifact must fail its own Jenkins build.

Implementation:

1. Producer's build script runs `architecture-validate architecture.json`.
2. Validator exit code is the build's exit code for that step.
3. Validator is distributed as a Docker image (`pvginkel/architecture-validator:0.1`) for use in Jenkins agents that don't have node/python.

The validator does **local** validation (schema conformance, profile constraints, internal consistency). It does **not** check cross-producer references — that's the collector's job because only the collector sees the full picture.

What the producer-side validator catches:

- Schema violations (missing required fields, wrong types).
- Profile violations (declaring a node type the profile forbids).
- Internal references (an edge whose endpoint isn't in the same artifact's `components` list — unless it's a stable GUID from another producer, in which case it's a cross-producer reference and skipped).
- Duplicate GUIDs within the artifact.
- Lifecycle field consistency (e.g., `deprecated` without `replaced-by` or `retirement-by`).

What it does **not** catch:

- Whether referenced GUIDs from other producers exist.
- Capability/product enum membership (those enums change in the architecture repo; producers don't have a current view). Treated as warnings locally, failures in the collector.

## Profile constraints (detailed)

### `infra-physical` — Ansible

Owns:
- Physical hosts: Proxmox hypervisor nodes, network appliances (UDM Pro), backup server, NAS.
- VMs managed via terraform-proxmox / cloud-init.
- Host-level installs: keepalived, haproxy at the OS layer, OpenBao on its dedicated VMs, MicroCeph if installed on hosts rather than via Helm.
- LAN-level networking: dnsmasq, VLAN structure if represented.

Edges typically declared:
- `runs-on` (VMs on Proxmox).
- `routes-to` between network components.
- `deploys` from Ansible itself (as a meta-component) to anything it manages.

May reference: products. Components in other producers' artifacts only via GUID (mostly not needed at this layer).

Forbidden: Helm releases, app pods, container images. Ansible installs the substrate; it doesn't deploy the cluster's workloads.

### `cluster-services` — HelmCharts

Owns:
- Helm releases in the cluster: ingress controller, cert-manager / step-ca, external-secrets, all shared databases (postgresql, opensearch, elasticsearch), brokers (rabbitmq, mosquitto), identity (keycloak), observability (prometheus, grafana, filebeat, kibana), storage drivers (ceph-csi, smb-csi), MetalLB, CoreDNS.
- The cluster-scoped stable IDs that app producers will reference.
- Groups for related releases (e.g., the observability stack).

Edges typically declared:
- `runs-on` to the cluster component (declared by Ansible — referenced by GUID).
- Inter-service edges (Kibana → Elasticsearch, Grafana → Prometheus).
- `gets-secrets-from` to external-secrets / OpenBao.

May reference: infra components (via GUID), products, capabilities.

Forbidden: physical hardware, app pods.

**Special status**: this is the SSOT for shared cluster-scoped GUIDs. App producers reference these GUIDs by hand-copying them from a published index. The architecture repo publishes that index (e.g., `https://architecture.webathome.org/index/cluster-services.json` listing every active component with GUID + label) for discoverability.

### `images` — DockerImages

Owns:
- Product entries for images built in this repo.
- `built-from` relations linking images to source repos (informational, not a runtime edge).

This profile is the smallest — the question (open in `00-roadmap.md`) is whether it deserves its own producer or whether image identity collapses into the app producer (the app declares "my pod uses this image" without DockerImages emitting anything).

**Recommendation**: keep `images` as a producer initially. It's the cleanest way to model the build → image → runtime chain end-to-end. If after v3 the profile feels redundant, fold it into apps.

Edges: `builds` (Jenkins → image), declared in `delivery` context (which is actually within `cluster-services` since Jenkins is Helm-deployed; the edge originates there).

### `application` — EI, IOT, and any future app repo

Owns:
- Application pods (one component per distinct pod, not per replica).
- APIs exposed by the app (each component declares its `routes-to`-able surface).
- Queues, exchanges, topics the app declares (with namespace-prefixed names so cross-app collisions don't happen).
- Storage paths the app uses (specific buckets, schemas, database names).

Edges typically declared:
- `routes-to` (between own pods, between own pods and shared services).
- `authenticates-via` (→ Keycloak component GUID).
- `gets-secrets-from` (→ external-secrets component GUID).
- `stores-in` (→ Postgres / S3 / etc. component GUIDs).
- `publishes-to` / `subscribes-to` (→ RabbitMQ / MQTT broker component GUIDs).

May reference: cluster-services components (by GUID), images, capabilities, products.

Forbidden: declaring shared infrastructure as its own. If app needs a new shared component, that gets added in `cluster-services`.

## How a producer integrates (the recipe)

For each producer repo, the integration is roughly:

1. **Author the artifact source.** Decide whether the data is hand-maintained in the repo (`architecture/*.yaml` checked in) or generated at build time from the repo's own state (e.g., Helm chart values → JSON via a small script). HelmCharts probably hand-maintains; apps probably generate from their existing deployment manifests.
2. **Mint GUIDs.** First integration: generate UUIDv7s for each component the producer owns; commit them. Subsequent: re-use, never re-mint.
3. **Add the validator step to Jenkinsfile.** Pull `pvginkel/architecture-validator:<schema-version>`, run against the artifact, fail the build on non-zero exit.
4. **Archive the artifact.** Jenkins `archiveArtifacts artifacts: 'architecture.json'`.
5. **Notify the architecture repo.** Webhook or Jenkins downstream trigger to `pvginkel/architecture`'s collector job. (Details in `05`.)

## Schema version negotiation

Producers pin a schema version at integration time. The collector accepts artifacts within a configured compatibility window (default: same major). When the architecture repo cuts a new schema major:

1. New schema version is published (e.g., `0.2`).
2. Validator image gets a new tag.
3. Each producer updates its pin individually, at its own pace, within a stated migration window.
4. Until all producers are on the new major, the collector accepts a mixed set (assuming minor-version compatibility is preserved).
5. After the window, the collector rejects artifacts on the old major.

Schema version bumps should be rare. Most evolution is additive (minor), not breaking (major).

## Per-repo integration order (v3 rollout)

Recommended sequence (after v2's HelmCharts pilot):

1. **DockerImages.** Small surface, mostly product entries. Good shakedown of the `images` profile.
2. **Ansible.** Substrate layer. Once done, every "runs-on" edge in the diagram is grounded.
3. **EI.** First real application producer. Will expose schema gaps that small profiles can't (queue declarations, multi-pod groups, internal `routes-to` graphs).
4. **IOT.** Second application; should be straightforward by this point.
5. **Any further apps.** Pattern is established; cost per app should be a few hours.

For each, the integration touches: that repo's `Jenkinsfile`, a new `architecture/` directory in that repo, and a small mention in the architecture repo's registered-producers list. No changes to other producers.

## What the producer does **not** decide

- Layout, position, color. Render-only fields are rejected.
- Which capabilities exist. Enum is centralized.
- Which products exist. Enum is centralized.
- Inclusion rules. The schema and the inclusion rule (`02-metaschema.md`) are authoritative; producer judgment doesn't override them.

## Open questions

- **Should producer-side validation also fetch the current published enums and validate against them?** Strictness vs producer-architecture coupling. Lean: optional `--strict-enums` flag that fetches; default off (warns); collector enforces.
- **Multiple artifacts per producer?** A repo that has multiple deliverables (e.g., separate Helm chart builds) might emit one artifact per chart. The protocol allows it (each is an independent artifact at a different Jenkins path). Collector treats them as a producer-group. Decide on naming convention if it comes up.
