# Architecture producer manual

This is the operator-side reference for becoming a producer in the
webathome.org federated architecture system. It lives at
`~/.claude/architecture/producer-manual.md` and the
`inventory-architecture` and `update-architecture` agents read it from
there on startup. Producer repos copy `arch-validate.py` into
`scripts/arch-validate.py` for their Jenkinsfile to call; everything else
is operator-side.

## What you're producing and why

Your repo emits **one or more architecture YAML files per build**.
A small repo may publish a single `architecture.yaml`; a larger repo
may split by scope — e.g. `infrastructure.yaml`, `home-automation.yaml`
— with each file describing one slice of what this repo owns. Every
file declares the same `producer:` (this repo's id); the collector
treats them as one logical producer at merge time. Within a single
producer, an id may be declared in only one file.

The federation pipeline picks up every `*.yaml` archived from your
last-successful build, validates each, merges them with every other
registered producer's files, cross-checks references, and publishes
the consolidated dataset at:

  https://architecture.webathome.org/data/v0.1/architecture.yaml
  https://architecture.webathome.org/data/v0.1/architecture.json
  https://architecture.webathome.org/data/v0.1/validation-report.json

Other producers reference your elements by UUID. Ansible publishes
nodes/VMs/clusters → HelmCharts references those when declaring
cluster services → app repos reference HelmCharts's service UUIDs.
The merged dataset eventually drives the rendered architecture
diagram (viewer migration is later).

You are **not** consuming any other producer's artifact directly.
Cross-producer UUIDs you need come from the published merged dataset
above — it's fetchable and greppable, so a generated producer can
resolve `hint`+kind → uuid at build time (read-only lookup) rather than
hand-copying. Hand-copy is the fallback, and the only option for a
producer that isn't published yet (chicken-and-egg): copy by hand until
its first build registers.

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
producer: <this-producer-id>           # bare kebab; matches this repo's entry in pipeline-producers.yaml

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
that isn't in the schema fails validation. In particular, do NOT add
a `producer:` field on individual elements; the collector stamps that
attribute onto every merged element from the envelope key above.

## Element kinds

Ten kinds. Each has a fixed id prefix and a declaration form.
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
| `Capability` | `cap:` | bare kebab | Business-architecture role (centrally curated; see appendix) |
| `BusinessService` | `bsvc:` | bare kebab | What the system delivers to humans (SSO, self-service tooling) |
| `Grouping` | `grp:` | composite | Cosmetic clustering of producer-local members |

Container images, repos, Helm charts, Ansible roles, and other build
artifacts are deliberately not modelled as architecture elements.
They're sources of statements about the architecture, not elements of
it — splitting or merging a repo doesn't change what runs where. The
repo identity lives on the envelope `producer:` key (which the
collector lifts onto each element) and, for in-house products, in the
optional `sourceRepository:` string attribute on `«SoftwareProduct»`.

## ID grammar

**Composite** is `<kind-prefix>:<hint>,<uuid>` — for example
`node:prd-cluster,7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f`.
The hint is a kebab-case nickname; the UUID is the load-bearing
identity. Both required at the declaration site. The hint can drift
across edits; the UUID cannot — mint it once, commit it, never
re-mint.

**Bare kebab** is `<kind-prefix>:<kebab-name>` — for example
`cap:iam`, `ss:keycloak`. Used by curated kinds (Capability,
BusinessService) and stereotyped catalog identities («SoftwareProduct»
on SystemSoftware / ApplicationComponent).

**References** in `relations.source` / `relations.target` accept three
forms:

- **composite** — `node:prd-cluster,7f3a…` (canonical, readable)
- **uuid-only** — `node:7f3a…` (terse; OK for cross-producer refs)
- **hint-only** — `node:prd-cluster` (OK **only when referencing an
  element this same producer declared**; cross-producer hint-only refs
  fail at merge time with a message pointing you at the UUID)

Mint UUIDs with `python -c 'import uuid; print(uuid.uuid4())'` or
`uuidgen`. The composite IDs inside the architecture YAML are the
single source of truth — once minted and committed there, an ID is
permanent. Don't maintain a parallel id table; it drifts and there's
nothing it tells you that grepping the YAML doesn't. Never re-mint.

That mint-once-uuid4 rule is for **hand-authored** producers. A
**generated** producer should derive **uuid5 from a documented natural
key** (e.g. `<namespace>.<workload>.<container>`) under a fixed
per-system namespace UUID: the id is then a pure function of stable repo
state, so "never re-mint" holds by construction — no stored ids, no id
table. Trade-off: renaming the natural key reads as remove-old +
add-new, dangling any cross-producer ref to the old id. The schema
accepts any UUID version.

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

- `environment` (optional, on Node, ApplicationComponent, SystemSoftware, ApplicationService, ApplicationInterface, TechnologyService, TechnologyInterface): `dev` \| `tst` \| `uat` \| `prd`
- `cluster` (optional, on Node, SystemSoftware, ApplicationComponent, ApplicationService, ApplicationInterface, TechnologyService, TechnologyInterface): cluster identifier

Set `environment` (and `cluster`, where applicable) on every element where the answer isn't "all of them" — externally-shared elements like `svc:github-api` legitimately span environments and stay unset.

**Do not emit a `producer:` attribute on elements.** The collector
stamps it onto every merged element from the envelope `producer:` key.
Per-kind schemas reject `producer:` via `additionalProperties: false`,
so producer CI catches this before submission.

## Stereotypes

Optional marker that adds extra attributes. Only one exists in v0.1:

### «SoftwareProduct»

Applies to: `SystemSoftware`, `ApplicationComponent`.

Marks a product identity (the thing the upstream project is called)
distinct from a running instance. Instances reach the product via
ArchiMate's `Specialization` relation.

Added attributes:

- `homepage` — URI, optional
- `logo` — filename under `viewer/public/logos/`, optional
- `sourceRepository` — free-form string for in-house products, optional
  (convention: `git:<owner>/<repo>`, e.g. `git:pvginkel/Ansible`).
  Informational only — no graph edge is derived from this.

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
| A node runs a daemon (cluster runs Keycloak) | `Assignment` | Node → SystemSoftware |
| Infra hosts / serves an application | `Serving` | Node / SystemSoftware / TechnologyService → ApplicationComponent |
| A daemon realises a capability | `Realization` | SystemSoftware → Capability |
| A service realises a capability | `Realization` | TechnologyService → Capability |
| A daemon exposes a service | `Realization` | SystemSoftware → TechnologyService |
| An interface exposes a service | `Assignment` | TechnologyInterface → TechnologyService |
| An instance is a particular SoftwareProduct | `Specialization` | instance → SoftwareProduct |
| A grouping aggregates its members | `Aggregation` | Grouping → any |

`Specialization` from an instance to its product catalog entry is
expected on every stereotyped instance — e.g. a running Keycloak
SystemSoftware specialises `ss:keycloak`. Ansible's running OpenBao
specialises `ss:openbao`.

**Generators: branch on the target kind.** A host→workload edge is not
one relation type — Node→SystemSoftware is `Assignment`,
Node→ApplicationComponent is `Serving`. The triple matrix differs by
target kind, so a generator can't emit one type blindly; pick per
target.

## Inclusion rule

A thing belongs in the architecture data **if and only if it has a
stable external identity that another component can reach by name** —
a DNS name, pod name, queue name, bucket name, domain name, API path,
hardware identifier. Classes, screens, internal functions, individual
files are out. Borderline cases default to **out**.

**Identity fence (esp. IaC / generated producers).** The rule admits a
thing by its *named surface or dependency edge*, never its runtime
state. A container has identity (`namespace.workload.container`) so it's
in; its replica count, env-var values, live config and current health
are out. If an annotation describes behaviour-at-runtime rather than a
named surface or a dependency edge, it's observability, not
architecture.

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
cap:high-availability         VIP failover / single-active-node redundancy for an addressable surface
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

Use the `arch-validate.py` script shipped alongside this manual. Copy it
to `scripts/arch-validate.py` in this repo and `chmod +x` it.

```bash
./scripts/arch-validate.py architecture.yaml
./scripts/arch-validate.py architecture/prd.yaml architecture/dev.yaml
cat architecture.yaml | ./scripts/arch-validate.py -
./scripts/arch-validate.py --json architecture.yaml      # raw response on stdout
./scripts/arch-validate.py --quiet architecture.yaml     # suppress OK lines
```

The script POSTs to `https://architecture.webathome.org/api/validate`
and exits `0` valid, `1` invalid, `2` transport/server error. It's a
single-file Python script that uses only the standard library, so any
`python:slim` (or system `python3`) is enough — no `pip install` step.

Override the endpoint for local testing:

```bash
ARCHITECTURE_VALIDATE_URL=http://localhost:8080/api/validate \
  ./scripts/arch-validate.py architecture.yaml
```

The validation service checks: schema conformance, id format,
stereotype-specific required attributes, ArchiMate relationship-type
enum, ArchiMate 3.2 triple matrix narrowed to the v0.1 subset. It
does **not** check cross-producer references — those are caught at
merge time in the Architecture pipeline.

## Jenkins integration

Two steps in this repo's `Jenkinsfile`. Both use a directory glob so
they work whether this repo emits one YAML or several:

1. **Validate** as a build step. Fail the build on non-zero exit:

   ```groovy
   stage('Validate architecture artifacts') {
       sh './scripts/arch-validate.py docs/architecture/*.yaml'
   }
   ```

2. **Archive** so the Architecture pipeline can pull every YAML via
   `copyArtifacts`:

   ```groovy
   stage('Archive architecture artifacts') {
       archiveArtifacts artifacts: 'docs/architecture/*.yaml', fingerprint: true
   }
   ```

The Architecture pipeline calls `copyArtifacts` with
`filter: '**/architecture/**/*.yaml'` and no `flatten`, so the YAMLs
land under `producer-artifacts/<producer-id>/` with their original
repo-relative paths preserved. The collector walks the producer
directory recursively, so subdirectory layout (and any same-basename
files in different subdirs) is fine.

The Jenkins agent must have outbound HTTPS to
`architecture.webathome.org` so the validator can reach the service.

## Registration in the federation pipeline

One PR against `pipeline-producers.yaml` in pvginkel/Architecture
adds this repo as a registered producer:

```yaml
producers:
  # … other entries …
  - id: <kebab-id>                  # matches the bare kebab in this repo's architecture YAML producer: key
    jenkinsJob: <Jenkins job path>  # e.g. ansible/master, HelmCharts/master
```

The next Architecture pipeline run picks the new entry up and wires
the upstream-success trigger automatically. From then on, every
successful build of this repo dispatches the Architecture pipeline
downstream.

## Ownership conventions

The conventions below describe the **expected** ownership patterns per producer — review-time judgment, not machine-enforced. The collector accepts any element kind from any producer.

| Producer | Typically owns |
|---|---|
| Ansible | Devices, Nodes (hypervisors/VMs/clusters), VM-level daemons, OS-layer services |
| HelmCharts | Cluster-deployed SystemSoftware, ApplicationServices/Interfaces, SoftwareProduct entries for cluster-published software |
| Per-app repos (EI, IoT, …) | ApplicationComponents (pods), ApplicationServices/Interfaces, app-specific SoftwareProduct entries |
| DockerImages | Image identity, build provenance (v0.2 territory — no v0.1 element kind for container images) |
| Architecture (self-producer) | Homeless elements: physical network/rack hardware, IoT/RF devices, Home Assistant. Files live under `docs/architecture/` in the Architecture repo itself. |

## Worked example

A minimal valid artifact, for shape reference:

```yaml
schemaVersion: "0.1"
producer: example

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
a skeleton with placeholders and comments — start from it. When the
repo grows, split into multiple files under `docs/architecture/` by
scope (e.g. `docs/architecture/infrastructure.yaml`,
`docs/architecture/home-automation.yaml`); the CI globs pick them all
up.

## Onboarding sequence (high-level)

1. **Survey**: walk this repo, understand what it deploys/owns, and
   propose a thin first slice to Pieter. The first artifact does not
   have to be exhaustive — the goal is to prove the pipeline end-to-end
   on real data and expand incrementally.
2. **Mint ids**: for each instance in scope, pick a kebab hint and
   generate a UUID. The composite IDs in the architecture YAML(s) are
   the single source of truth; no separate id table.
3. **Author** the architecture YAML(s) under `docs/architecture/`.
   Iterate against `./scripts/arch-validate.py docs/architecture/*.yaml`
   until clean.
4. **Wire CI**: add the validate + archive steps to this repo's
   Jenkinsfile.
5. **Verify**: trigger one build. Confirm every file archives and
   the validation step passes.
6. **Register**: PR `pipeline-producers.yaml` in pvginkel/Architecture
   adding this producer. After it lands, the next Architecture
   pipeline run picks the files up and emits the merged dataset with
   this repo's elements included.
