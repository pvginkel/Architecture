# Architecture producer manual

This is the standalone reference for becoming a producer in the
webathome.org federated architecture system. Drop this file and the
two siblings (`arch-validate`, `architecture.yaml`) into the producer
repo. Nothing else from the Architecture repo is needed.

## What you're producing and why

Your repo emits **one architecture artifact per build**: a YAML file
named `architecture.yaml` (or a clearly-named per-environment variant)
describing the elements this repo owns — VMs, clusters, daemons,
services, repos, etc. — and the relationships between them.

The federation pipeline picks up your last-successful build's archived
`architecture.yaml`, merges it with every other registered producer's
artifact, cross-checks references, and publishes the consolidated
dataset at:

  https://architecture.webathome.org/data/v0.1/architecture.yaml
  https://architecture.webathome.org/data/v0.1/architecture.json
  https://architecture.webathome.org/data/v0.1/validation-report.json

Other producers reference your elements by UUID. Ansible publishes
nodes/VMs/clusters → HelmCharts references those when declaring
cluster services → app repos reference HelmCharts's service UUIDs.
The merged dataset eventually drives the rendered architecture
diagram (viewer migration is later).

You are **not** consuming any other producer's artifact directly.
Cross-producer UUIDs you need are copied once, by hand, from the
published merged dataset into your repo's source.

## Working style

- **Pieter drives, you assist.** Do not propose what to model, what
  to name, what to include, or what stereotype to apply unless asked.
  Ask when in doubt.
- **No defensive coding.** No try/except that swallows errors. No
  "drop the bad input, keep going" patterns. No null-guards for
  conditions the framework already prevents.
- **No "just in case" infrastructure.** No scheduled rebuilds without
  a known failure to catch. No retries on operations expected to
  succeed once. No fallback caches. No belt-and-suspenders checks at
  adjacent layers. No fall-back-to-old-code paths. Before adding any
  hedge, ask: *what concrete failure does this catch?* "Just in case"
  isn't an answer.
- **Commit each meaningful unit** without being asked. Even a one-line
  edit is its own commit. Don't push (no push rights). Don't flag
  "ahead of origin."
- **The user is Pieter van Ginkel**, Domain Architect at IVO
  Rechtspraak, developer since 2001. Skip beginner framing. Discuss
  tradeoffs directly.

## Artifact envelope

```yaml
schemaVersion: "0.1"
producer: art:<this-producer-id>       # bare kebab; matches a declared «Producer» Artifact entry below
generatedAt: 2026-05-27T12:00:00Z      # optional, informational

artifacts:                              # required: at least the «Producer» Artifact for this repo
  - id: art:<this-producer-id>
    label: ...
    summary: ...
    introduced: 2024-07-12
    lifecycle: active
    stereotype: Producer
    url: https://github.com/owner/repo
    role: source
    owner: <human or team>

# all of the following arrays are optional; emit what this repo owns:
nodes: [...]
devices: [...]
systemSoftware: [...]
applicationComponents: [...]
applicationServices: [...]
applicationInterfaces: [...]
technologyServices: [...]
technologyInterfaces: [...]
capabilities: [...]
businessServices: [...]
groupings: [...]
relations: [...]
```

`additionalProperties: false` applies everywhere — any extra field
that isn't in the schema fails validation.

## Element kinds

Twelve kinds. Each has a fixed id prefix and a declaration form.
References between elements (in `relations`) use the same ids.

| Kind | Prefix | Declaration form | Use for |
|---|---|---|---|
| `Node` | `node:` | composite | Execution hosts: clusters, VMs, hypervisor clusters, physical compute |
| `Device` | `device:` | composite | Physical hardware: switches, APs, server boxes, IoT |
| `SystemSoftware` instance | `ss:` | composite | Running OS-level daemons (OpenBao on `bao-vm`, HAProxy on `haproxy-vm`, etc.) |
| `SystemSoftware` («SoftwareProduct») | `ss:` | bare kebab | Software product identity (`ss:kubernetes`, `ss:openbao`, `ss:postgresql`) |
| `ApplicationComponent` instance | `app:` | composite | Running app workload (EI backend pod, DA worker, etc.) |
| `ApplicationComponent` («SoftwareProduct») | `app:` | bare kebab | Application product identity (`app:electronics-inventory`) |
| `ApplicationService` | `svc:` | composite | App-layer consumption surface (internal HTTP API) |
| `ApplicationInterface` | `if:` | composite | Addressable point on an ApplicationService (specific endpoint path) |
| `TechnologyService` | `svc:` | composite | Infra consumption surface (Postgres-on-5432, OIDC issuer, Proxmox API) |
| `TechnologyInterface` | `if:` | composite | Addressable point on a TechnologyService (queue, topic, vault path, db name) |
| `Artifact` («Repository», «Producer») | `art:` | bare kebab | Source/spec/config repository, including the «Producer» entry for this repo |
| `Artifact` (non-stereotyped) | `art:` | composite | Deployable bundle (Helm chart, Ansible role, TF module) |
| `Capability` | `cap:` | bare kebab | Business-architecture role (centrally curated; see appendix) |
| `BusinessService` | `bsvc:` | bare kebab | What the system delivers to humans (SSO, self-service tooling) |
| `Grouping` | `grp:` | composite | Cosmetic clustering of producer-local members |

## ID grammar

**Composite** is `<kind-prefix>:<hint>,<uuid4>` — for example
`node:prd-cluster,7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f`.
The hint is a kebab-case nickname; the UUID is the load-bearing
identity. Both required at the declaration site. The hint can drift
across edits; the UUID cannot — mint it once, commit it, never
re-mint.

**Bare kebab** is `<kind-prefix>:<kebab-name>` — for example
`cap:iam`, `ss:keycloak`, `art:helmcharts`. Used by curated kinds
(Capability, BusinessService) and stereotyped catalog identities
(SoftwareProduct on SystemSoftware/ApplicationComponent; Repository
or Producer on Artifact).

**References** in `relations.source` / `relations.target` accept three
forms:

- **composite** — `node:prd-cluster,7f3a…` (canonical, readable)
- **uuid-only** — `node:7f3a…` (terse; OK for cross-producer refs)
- **hint-only** — `node:prd-cluster` (OK **only when referencing an
  element this same producer declared**; cross-producer hint-only refs
  fail at merge time with a message pointing you at the UUID)

Mint UUIDs with `python -c 'import uuid; print(uuid.uuid4())'` or
`uuidgen`. Commit them next to the architecture source so they're
stable across builds. Never re-mint.

## Common attributes

Every element carries these. Most are required; the schema rejects
missing ones.

| Attribute | Type | Required? | Notes |
|---|---|---|---|
| `id` | string | yes | Per the kind's regex (composite or bare kebab) |
| `label` | string | yes | Display string; may change without ID change |
| `summary` | string | yes | One or two sentences |
| `introduced` | ISO date | yes | When first declared |
| `lifecycle` | enum | yes | `active` \| `deprecated` \| `removed` |
| `retirementBy` | ISO date | optional | Informational target retirement date. No rule attached. |
| `stats` | string→string map | optional | Non-load-bearing facts (versions, URLs, image tags) |

Per-kind additions:

- `environment` (optional, on Node/Artifact/ApplicationComponent/SystemSoftware): `dev` \| `tst` \| `uat` \| `prd`
- `cluster` (optional, on Node/SystemSoftware/ApplicationComponent): cluster identifier

**No `producer:` attribute on elements.** Provenance is synthesised
automatically by the collector — an Association relation per declared
element, from the top-level `producer:` («Producer» Artifact) to the
element. You do not emit those relations yourself.

## Stereotypes

Optional marker that adds extra required attributes. Three exist in
v0.1:

### «SoftwareProduct»

Applies to: `SystemSoftware`, `ApplicationComponent`.

Marks a product identity (the thing the upstream project is called)
distinct from a running instance. Instances reach the product via
ArchiMate's `Specialization` relation.

Added attributes:

- `homepage` — URI, optional
- `logo` — filename under `viewer/public/logos/`, optional
- `sourceRepository` — id of an Artifact, optional (for in-house products)

Example:

```yaml
systemSoftware:
  - id: ss:openbao                      # bare kebab — catalog identity
    label: OpenBao
    summary: Open-source fork of HashiCorp Vault for secret management.
    introduced: 2024-07-12
    lifecycle: active
    stereotype: SoftwareProduct
    homepage: https://openbao.org/
    logo: openbao.svg
```

The producer that **publishes** a product (the upstream lives in this
repo's domain) emits the catalog entry. Ansible owns
`ss:kubernetes`, the ZFS allocator's product entry, etc. Other
producers reference those entries by id; they don't redeclare them.

### «Repository»

Applies to: `Artifact`.

Marks the Artifact as a source/spec/config repository.

Added attributes:

- `url` — URI, required
- `role` — `source` \| `spec` \| `config`, required
- `owner` — string, required (human or team)
- `languageMix` — string→string map (e.g. `{Python: "85", YAML: "15"}`), optional

### «Producer»

Applies to: `Artifact`. Additionally requires the `Repository` stereotype.

Marker only — no added attributes of its own beyond what Repository
brings. Identifies a Repository as a producer of architecture data,
so the federation pipeline knows it's an authoritative emitter.

This is what your repo's own Artifact entry uses. The top-level
`producer:` envelope key must point at exactly this Artifact's id.

Example (the entry your producer.yaml should always contain):

```yaml
artifacts:
  - id: art:ansible                     # whatever this repo's producer id is
    label: Ansible repo
    summary: Owns Proxmox/k8s/OpenBao/HAProxy/step-ca infrastructure architecture.
    introduced: 2024-07-12
    lifecycle: active
    stereotype: Producer
    url: https://github.com/pvginkel/Ansible
    role: source
    owner: Pieter van Ginkel
```

## Relations

Every relationship is a first-class entry in the `relations` array.
ArchiMate-pure: no attribute-style refs (no `runsOn: <id>` on a
SystemSoftware, etc.). All edges go through relations.

```yaml
relations:
  - id: rel:<kebab-or-uuid>
    source: <element-id>
    target: <element-id>
    type: <ArchiMate relationship type>
```

Allowed `type` values (the ArchiMate 3.2 enumeration):

```
Access, Aggregation, AndJunction, Assignment, Association, Composition,
Flow, Influence, OrJunction, Realization, Serving, Specialization, Triggering
```

The collector enforces the ArchiMate 3.2 triple matrix — every
`(source-kind, type, target-kind)` triple must be permitted. If you
pick an invalid combination the validator returns a clear error
naming the triple; iterate. The matrix is large (~700 triples), so
the manual doesn't enumerate it; common mappings:

| Architectural fact | Relation | Source-kind → Target-kind |
|---|---|---|
| A node runs a daemon (cluster runs Keycloak) | `Assignment` | Node → SystemSoftware / ApplicationComponent |
| A daemon realises a capability | `Realization` | SystemSoftware → Capability |
| A service realises a capability | `Realization` | TechnologyService → Capability |
| A daemon exposes a service | `Composition` or `Realization` | SystemSoftware → TechnologyService |
| A service exposes an interface | `Composition` | TechnologyService → TechnologyInterface |
| An instance is a particular SoftwareProduct | `Specialization` | instance → SoftwareProduct |
| A producing repo is composed of charts/roles | `Composition` | Artifact (Producer) → Artifact |
| A grouping aggregates its members | `Aggregation` | Grouping → any |

**Do not emit producer-Association relations from your «Producer»
Artifact to each declared element.** The collector synthesises those
automatically. If you emit them by hand, the merge will fail on
duplicate ids.

`Specialization` from an instance to its product catalog entry is
expected on every stereotyped instance — e.g. a running Keycloak
SystemSoftware specialises `ss:keycloak`. Ansible's running OpenBao
specialises `ss:openbao`.

## Inclusion rule

A thing belongs in the architecture data **if and only if it has a
stable external identity that another component can reach by name** —
a DNS name, pod name, queue name, bucket name, domain name, API path,
hardware identifier. Classes, screens, internal functions, individual
files are out. Borderline cases default to **out**.

When unsure whether a particular thing belongs, ask Pieter rather
than guessing.

## Capability enum (read-only reference)

You may **reference** any of these but cannot mint new ones without
a PR against `schema/v0.1/enums/capabilities.yaml` in the
Architecture repo.

```
cap:iam                       Identity & Access Management
cap:secrets-management        Secrets storage / rotation / lease management
cap:pki                       Certificate issuance / renewal / trust chain
cap:ingress                   External-facing HTTP/TCP entry into the cluster
cap:load-balancing            L2/L4 traffic distribution
cap:dns                       Authoritative or recursive DNS resolution
cap:dhcp                      IP address allocation for a LAN segment
cap:relational-database       SQL-tabular persistence
cap:document-store            Schemaless / semi-structured document persistence
cap:vector-store              Embedding storage with similarity search
cap:full-text-search          Inverted-index search over textual corpora
cap:cache                     In-memory key-value store with eviction
cap:message-queue             Point-to-point durable messaging
cap:pub-sub-broker            Topic-based publish/subscribe
cap:object-storage            S3-style bucket persistence
cap:shared-filesystem         Network-mountable POSIX-ish filesystem
cap:block-storage             Raw block devices
cap:metrics                   Time-series numeric telemetry
cap:logging                   Log shipping / aggregation / search
cap:observability             Cross-cutting metrics + logging + tracing
cap:container-orchestration   Container scheduling and lifecycle
cap:hypervisor                VM scheduling and lifecycle
cap:image-registry            OCI image storage and distribution
cap:source-control            Git repository hosting and access control
cap:continuous-integration    Build and pipeline orchestration
cap:configuration-management  Declarative or imperative system-state convergence
cap:remote-access             Browser/RDP/SSH gateway into managed environments
cap:vpn                       Encrypted network tunnel
cap:media-streaming           Audio/video catalogue, transcoding, client delivery
cap:home-automation           Sensor/actuator orchestration over Zigbee/MQTT
```

If a needed capability isn't listed, raise it with Pieter — adding
one is a small PR against the Architecture repo's enum, separate from
producer onboarding.

## Lifecycle states

- `active` — live, referenceable.
- `deprecated` — being phased out. `retirementBy: <date>` is optional informational metadata.
- `removed` — no longer deployed. Producer still emits the entry until references are gone.

No conditional rules between lifecycle and other fields. No
`replacedBy` attribute exists in v0.1.

## Validation

Use the `arch-validate` script shipped alongside this manual. Copy it
to `scripts/arch-validate` in this repo and `chmod +x` it.

```bash
./scripts/arch-validate architecture.yaml
./scripts/arch-validate architecture/prd.yaml architecture/dev.yaml
cat architecture.yaml | ./scripts/arch-validate -
./scripts/arch-validate --json architecture.yaml      # raw response on stdout
./scripts/arch-validate --quiet architecture.yaml     # suppress OK lines
```

The script POSTs to `https://architecture.webathome.org/api/validate`
and exits `0` valid, `1` invalid, `2` transport/server error.
Dependencies: `bash`, `curl`, `jq` — no language runtime needed.

Override the endpoint for local testing:

```bash
ARCHITECTURE_VALIDATE_URL=http://localhost:8080/api/validate \
  ./scripts/arch-validate architecture.yaml
```

The validation service checks: schema conformance, id format,
stereotype-specific required attributes, ArchiMate relationship-type
enum, ArchiMate 3.2 triple matrix narrowed to the v0.1 subset. It
does **not** check cross-producer references — those are caught at
merge time in the Architecture pipeline.

## Jenkins integration

Two steps in this repo's `Jenkinsfile`:

1. **Validate** as a build step. Fail the build on non-zero exit:

   ```groovy
   stage('Validate architecture artifact') {
       sh './scripts/arch-validate architecture.yaml'
   }
   ```

2. **Archive** the artifact so the Architecture pipeline can pull it
   via `copyArtifacts`:

   ```groovy
   stage('Archive architecture artifact') {
       archiveArtifacts artifacts: 'architecture.yaml', fingerprint: true
   }
   ```

The Jenkins agent must have outbound HTTPS to
`architecture.webathome.org` so the validator can reach the service.

## Registration in the federation pipeline

One PR against `pipeline-producers.yaml` in pvginkel/Architecture
adds this repo as a registered producer:

```yaml
producers:
  # … other entries …
  - id: <kebab-id>                  # matches the bare kebab in your art: Producer id
    profile: <profile-id>           # infra-physical | cluster-services | application | images
    jenkinsJob: <Jenkins job path>  # e.g. ansible/master, HelmCharts/master
```

The next Architecture pipeline run picks the new entry up and wires
the upstream-success trigger automatically. From then on, every
successful build of this repo dispatches the Architecture pipeline
downstream.

## Profiles

| Profile | Used by | Typically owns |
|---|---|---|
| `infra-physical` | Ansible | Devices, Nodes (hypervisors/VMs/clusters), VM-level daemons, OS-layer services |
| `cluster-services` | HelmCharts | Cluster-deployed SystemSoftware, ApplicationServices/Interfaces, Helm chart Artifacts, SoftwareProduct entries for cluster-published software |
| `application` | per-app repos | ApplicationComponents (pods), ApplicationServices/Interfaces, app-specific SoftwareProduct entries |
| `images` | DockerImages | Image identity, build provenance (mostly v0.2 territory) |

The profile is **descriptive metadata only** — the collector does not
enforce a per-kind allow-list. Conventions above are guidance for
review-time judgment.

## Worked example

A minimal valid two-element artifact, for shape reference:

```yaml
schemaVersion: "0.1"
producer: art:example

artifacts:
  - id: art:example
    label: Example repo
    summary: Demonstrates the minimal envelope.
    introduced: 2026-05-27
    lifecycle: active
    stereotype: Producer
    url: https://github.com/example/repo
    role: source
    owner: Example Owner

nodes:
  - id: node:prd-cluster,7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f
    label: Production cluster
    summary: Production Kubernetes cluster.
    introduced: 2026-05-27
    lifecycle: active
    cluster: prd

systemSoftware:
  - id: ss:openbao,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    label: OpenBao (prd)
    summary: Production OpenBao instance providing secrets management.
    introduced: 2026-05-27
    lifecycle: active
    environment: prd

  - id: ss:openbao
    label: OpenBao
    summary: Open-source HashiCorp Vault fork for secrets management.
    introduced: 2026-05-27
    lifecycle: active
    stereotype: SoftwareProduct
    homepage: https://openbao.org/

relations:
  - id: rel:openbao-realises-secrets
    source: ss:openbao,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    target: cap:secrets-management
    type: Realization

  - id: rel:openbao-specialises-product
    source: ss:openbao,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    target: ss:openbao
    type: Specialization
```

The starter file `architecture.yaml` shipped alongside this manual is
a skeleton with placeholders and comments — start from it.

## Onboarding sequence (high-level)

1. **Survey**: walk this repo, understand what it deploys/owns, and
   propose a thin first slice to Pieter. The first artifact does not
   have to be exhaustive — the goal is to prove the pipeline end-to-end
   on real data and expand incrementally.
2. **Mint ids**: for each instance in scope, pick a kebab hint and
   generate a UUID. Commit the id table next to the architecture
   source.
3. **Author** `architecture.yaml`. Iterate against
   `./scripts/arch-validate architecture.yaml` until clean.
4. **Wire CI**: add the validate + archive steps to this repo's
   Jenkinsfile.
5. **Verify**: trigger one build. Confirm the artifact archives and
   the validation step passes.
6. **Register**: PR `pipeline-producers.yaml` in pvginkel/Architecture
   adding this producer. After it lands, the next Architecture
   pipeline run picks the artifact up and emits the merged dataset
   with this repo's elements included.
