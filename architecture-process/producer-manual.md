# Architecture producer manual

This is the operator-side reference for becoming a producer in the
webathome.org federated architecture system. It lives at
`~/.claude/architecture/producer-manual.md`. The `/seed-architecture`
skill (first-version authoring) and the `update-architecture` /
`update-architecture-generated` agents read it from there on startup.
Producer repos copy `arch-validate.py` into `scripts/arch-validate.py`
for their Jenkinsfile to call; everything else is operator-side.

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
# no capabilities: array — producers never declare Capability elements
# (see the Capability enum appendix); reference cap: ids from relations only.
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
| `SystemSoftware` («SoftwareProduct») | `ss:` | composite | Software product identity (`ss:kubernetes`, `ss:openbao`); `stereotype: SoftwareProduct` marks it |
| `ApplicationComponent` instance | `app:` | composite | Running app workload (EI backend pod, DA worker, etc.) |
| `ApplicationComponent` («SoftwareProduct») | `app:` | composite | Application product identity (`app:electronics-inventory`); `stereotype: SoftwareProduct` marks it |
| `ApplicationService` | `svc:` | composite | App-layer consumption surface (internal HTTP API) |
| `ApplicationInterface` | `if:` | composite | Addressable point on an ApplicationService (specific endpoint path) |
| `TechnologyService` | `svc:` | composite | Infra consumption surface (Postgres-on-5432, OIDC issuer, Proxmox API) |
| `TechnologyInterface` | `if:` | composite | Addressable point on a TechnologyService (queue, topic, vault path, db name) |
| `Capability` | `cap:` | reference only | Business-architecture role. Declared only in the Architecture repo's enum, never in a producer artifact — reference `cap:` ids from relations and the collector backfills the node (see appendix) |
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
`cap:iam`. Used **only** by the curated-vocabulary kinds (Capability,
BusinessService): their stability comes from central curation / enum
membership, not a UUID. Every other kind — including «SoftwareProduct»
catalog entries — is composite and carries a UUID.

**References** in `relations.source` / `relations.target` accept three
forms:

- **composite** — `node:prd-cluster,7f3a…` (canonical, readable)
- **uuid-only** — `node:7f3a…` (terse; the form for cross-producer refs)
- **hint-only** — `node:prd-cluster` (OK **only when referencing an
  element this same producer declared**; cross-producer hint-only refs
  fail at merge time with a message pointing you at the UUID)

**A cross-producer reference is the UUID — period.** The hint is
informational; the UUID is the stable, normative identity. This holds
for «SoftwareProduct» catalog entries too: referencing another
producer's `ss:keycloak` by bare name resolves only inside the
declaring producer, so cross-producer it dangles — use the UUID
(`ss:<uuid>`), resolved from the published dataset. Only `cap:`/`bsvc:`
are referenced by their bare name, because they're a curated vocabulary.

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
| `logo` | enum | optional | Bare logo name from the bundled library, on any element kind |

`logo` is validated against the bundled logo library: reference a file
in `viewer/public/logos/` by its name **without the extension** (e.g.
`ubiquiti` for `ubiquiti.svg`, `keycloak` for `keycloak.svg`). A typo, a
name that isn't in the library, or a name *with* an extension fails
validation. **To add a new logo:** drop the SVG/PNG into
`viewer/public/logos/` and regenerate
(`poetry run python tooling/generate.py`) so the enum picks it up; until
then, referencing it fails validation.

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
ArchiMate's `Specialization` relation. Product and instance are both
composite (UUID-bearing); the `stereotype: SoftwareProduct` field is
what distinguishes the product. Convention: the product's hint is the
bare product name (`ss:keycloak,<uuid>`), an instance's hint adds a
distinguishing axis (`ss:keycloak-prd,<uuid>`).

Added attributes:

- `homepage` — URI, optional
- `sourceRepository` — free-form string for in-house products, optional
  (convention: `git:<owner>/<repo>`, e.g. `git:pvginkel/Ansible`).
  Informational only — no graph edge is derived from this.

Example:

```yaml
systemSoftware:
  - id: ss:openbao,3f1d9c2a-7b4e-4a1f-9c2d-5e6f7a8b9c0d   # composite — catalog identity
    label: OpenBao
    summary: Open-source fork of HashiCorp Vault for secret management.
    introduced: 2024-07-12
    lifecycle: active
    stereotype: SoftwareProduct
    homepage: https://openbao.org/
```

The producer that **publishes** a product emits the catalog entry, and
it's emitted **once** by a single owner (see Ownership conventions for
who). Other producers reference it by **UUID** — resolved from the
published dataset — and never redeclare it. A bare-name reference would
dangle cross-producer.

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

### Relation attribute: `boundBy`

Relations are otherwise attribute-free. The one profile attribute they
may carry is `boundBy` — a **binding recipe** for a runtime dependency
whose concrete provider is only known at deploy time. Its value is
`env:<VAR_NAME>`: the named container environment variable in the
rendered deployment holds the provider's address. (The `env:` prefix
leaves room for other value sources later; only `env:` exists in v0.1.)

```yaml
relations:
  # substitutable infra — target is a capability; boundBy REQUIRED
  - id: rel:design-assistant-consumes-iam
    source: app:design-assistant      # the consumer
    target: cap:iam                   # the capability it consumes
    type: Association
    boundBy: "env:OIDC_ISSUER_URL"
  # known in-house provider — target is its service; boundBy OPTIONAL
  - id: rel:nginx-configurator-consumes-certbot
    source: app:nginx-configurator    # the consumer
    target: svc:certbot,<uuid>        # the specific provider service
    type: Association
    boundBy: "env:NGINX_CERTBOT_ENDPOINT"
```

For a provider-agnostic recipe the consumption edge's **`source` is always
the consumer** and `type` is `Association` — the external-service case below
flips this to `Serving`. The recipe lives with the consumer (its own
producer authors it), never in whatever packages or deploys it. The edge's
**target** says how specific the dependency is:

- **`target: cap:<x>`** — a *substitutable* capability the consumer's
  producer does not pin to a concrete provider (any OIDC IdP, any
  Postgres). `boundBy` is **required** — it is the only thing that lets a
  deployer find the provider. The deployer resolves the env host to an
  element that **`Realize`s that capability**: a checked invariant; if the
  resolved provider doesn't realize it, generation fails loudly.
- **`target: svc:<id>`** — a *specific* service of a known provider
  (typically another in-house app modelled by the same federation, e.g.
  `nginx-configurator → svc:certbot`). The target already names the
  provider, so `boundBy` is **optional**: include it to record which env
  var carries the wire (and to let the deployer project the edge onto the
  right instance/container); omit it when the logical edge suffices.

**External services — author the `Serving` edge, not an `Association`.** A
third-party SaaS or any provider reached at a fixed, hardcoded host that no
producer deploys (OpenAI, the Telegram Bot API, a public RSS feed, Firebase)
carries no `boundBy` and is *never* resolved into a concrete edge by a
deployer — there is none in the loop. Left as an `Association` it strands in
the provider-agnostic recipe layer, reading as a generic, un-actioned
dependency (and is hidden wherever Associations are filtered). Instead author
the concrete form a resolved `boundBy` would have produced:
`external-svc —Serving→ consumer` (source the service, target the consumer).
It is the same `provider —Serving→ consumer` shape deployers hand-author
where auto-resolution can't reach (e.g. `svc:openbao-api-prd —Serving→` the
ESO controller), and it renders as the real dependency it is. Use `Serving`
for every external-service consumption; reserve the unresolved `Association`
for in-house recipes a deployer will resolve into that `Serving` for you.

A dependency on an *in-house* provider located by a config file or service
account (no `env:` recipe) may still be a plain `Association` with no
`boundBy`; it just never resolves to a concrete `Serving`. Model it when it
documents a real dependency.

**`boundByDefaultValue` — the recipe's fallback value.** When the edge is
real but no deployed container sets the env var, because the consumer's
application code defaults the connection target (a colocated sidecar
reached on `localhost`, e.g. `SSE_GATEWAY_URL=http://localhost:3402` or
`RABBITMQ_URL=amqp://guest:guest@localhost:5672/`), the deployer has
nothing to read and the edge would fail to resolve. Carry the code default
on the recipe as `boundByDefaultValue` and the resolver treats it as though
it had been read off the container — loopback hosts still resolve to the
same-pod provider:

```yaml
  - id: rel:design-assistant-consumes-sse-gateway
    source: app:design-assistant
    target: svc:ssegateway
    type: Association
    boundBy: "env:SSE_GATEWAY_URL"
    boundByDefaultValue: "http://localhost:3402"
```

It is a **fallback, never an override**: a rendered env value always wins;
`boundByDefaultValue` only fills in when no container sets the var. It
belongs **on the recipe, not in the chart** — the default is a property of
the application, not of any deployment, and restating it across every chart
and stage duplicates it and inverts ownership. Author it on the consumer's
own product edge (the same producer that owns the `boundBy`), mirroring the
app's own `config.py` default. Omit it when a chart genuinely sets the var,
or when the edge legitimately has no concrete connection target. Without
either a setter or a `boundByDefaultValue`, an unresolved `boundBy` still
fails loudly — that genuinely is a stale recipe or a chart that must surface
the var, and the breakage remains the signal.

**Who resolves it.** The producer that *renders the deployment* (it is
the only one that sees the env value, which is runtime state and stays
unpublished). For each deployed instance that specialises the consumer
product, that producer reads the env var's rendered value, parses out the
host, maps the host to a provider element (its own services, an exposed
host, or a hand-mapped cross-producer host), checks the invariant above,
and emits the concrete `provider —Serving→ instance` edge. An
unresolvable host fails loudly; nothing is silently skipped.

Until such a producer resolves it, a `boundBy` edge is just the recipe —
no concrete `Serving` edge exists. The recipe can be authored before any
deployer consumes it; resolution appears when a deploying producer does.

**Resolving it (deployer-side mechanics).** Lessons from the first
resolver — the details bite:

- **Resolve cross-producer ids from the published dataset; don't
  hand-copy.** The resolver fetches the merged dataset as its base and
  overlays any not-yet-published sibling producer (a local checkout) so
  authored-but-unpublished recipes resolve while testing. `hint`+kind →
  uuid is a read-only lookup; hand-copied constants are the last resort,
  not the norm. (There is no "can't link cross-producer" blocker — the
  UUID is in the dataset; fetch and resolve it.)
- **Parse the host, preserve identity.** Strip scheme / `user:pass@` /
  path from the env value, but keep the host *and* port — same-pod and
  `localhost` providers differ only by port, so trimming it collapses
  distinct wires. Normalize Kubernetes Service DNS to `(ns, svc)` only by
  stripping a recognized `.svc[.cluster.local]` suffix, and trust the
  result only if that `(ns, svc)` actually exists — never strip arbitrary
  domains (`ca.home` is an external host, not `svc=ca, ns=home`).
- **A provider is a long-running container.** Exclude init containers: one
  sharing the product image "realizes" the capability per annotation but
  doesn't serve the wire. For `cap:` targets keep only providers that both
  Realize the capability and aren't init.
- **A provider may be SystemSoftware.** Keycloak/Jenkins back their
  exposed host as `ss:`; match the Service selector over *all* workload
  containers, not just ApplicationComponents.
- **`svc:` targets locate, not just name.** When the named app runs in
  several workloads the env value's host picks which instance — a loopback
  host means the same pod; otherwise the workload whose name the host
  carries (`dns-0.dns-headless` → the `dns` workload).
- **Two real consumers, two edges.** A recipe set on the same container in
  two workloads (a Deployment and its renewal CronJob) resolves to two
  genuine `Serving` edges — not a duplicate to suppress.
- **Draw at the coarsest granularity the signal honestly supports.** The
  env-var-presence test already discriminates per-role workloads for free
  — a migration job that doesn't set `OIDC_ISSUER_URL` gets no IAM edge,
  so least-privilege env scoping *is* the model's precision, no hardcoding.
  For a deployer-owned wire with *no* env signal (a secret store, below),
  don't manufacture pod-level precision — attach to the primary controller,
  not every pod that shares the capability.

### An application's exposed surface

An app that offers a network API is modelled as one `ApplicationService`
realized by the app (`app —Realization→ svc`), with one
`ApplicationInterface` **per distinct consumer** of that service
(`if —Assignment→ svc`). Most apps have a single consumer class and so a
single interface; model several only when the API genuinely serves
different client types (a public read surface vs an admin/IaC surface, a
frontend vs a separate portal). Group by consumer, not by route — an
interface per HTTP path is an endpoint inventory, not an architecture.

The **logical** ApplicationService belongs to the app's own producer; the
**deployer** that exposes it publicly references that service's UUID and
attaches the public host as an `ApplicationInterface` on it, rather than
minting a second service for the same app. The deployer detects this case
from the published dataset — the backing product carries an
`app —Realization→ svc` edge — and references that `svc` UUID; for an
upstream app with no such product it mints its own service as before. It
does **not** re-emit the `instance —Realization→ svc` edge: that
realization is the app producer's, and the instance reaches the service
transitively through its `Specialization`.

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

## Generated producers

Two sanctioned authoring modes — pick by how structured the repo is:

- **Hand-authored** — a human writes the YAML; it *is* the source of
  truth. Everything above assumes this.
- **Generated** — a generator walks the repo, fuses mechanically-derived
  structure with a thin committed **annotation layer** for judgment, and
  emits the YAML in CI. The repo + annotations are the source of truth;
  the YAML is a build artifact you **don't commit** (regenerate it — see
  Jenkins integration). Ids are uuid5-from-natural-key (see ID grammar);
  the `update-architecture-generated` agent maintains it.

**As-deployed granularity.** A generated producer may model running
containers — an operational, more-than-textbook deployment view. This is
legitimate *because* the model is derived from the source of truth (it
can't drift) and the «SoftwareProduct» spine + `Specialization` keeps a
clean logical type layer under the instance detail. Hand-authored
producers stay at the coarser logical grain. The identity fence above
still binds: named surfaces and edges, never runtime state.

**Deterministic natural keys.** The uuid5 natural key must be stable
across renders, or every build re-mints the id and dangles any
cross-producer ref to it. Strip deploy-time randomness out of the key —
a Helm `randAlphaNum` suffix on a one-shot Job name (`...-setup-x7f2a`)
churns the id every render; normalize it to the stable base. Likewise a
random value the render bakes into a manifest (a generated secret) must
not reach any id or emitted field. Verify by regenerating twice and
diffing — a clean producer is byte-identical.

**Legibility.** One app × {dev,tst,uat,prd} × N containers explodes into
near-identical instances. Use a `Grouping` per release and set
`environment`/`cluster` consistently so instances collapse under their
product/release. (The viewer-side collapse is pending viewer work; the
convention is cheap and correct now.) That discipline is what keeps an
as-deployed model an architecture, not an inventory.

**Provenance.** A generator may want to record source template, generator
version, render timestamp per element. There's no schema home today
(`additionalProperties: false`); stash it in `stats` if you need it. A
dedicated `provenance` slot is a v0.2 question.

## Capability enum (read-only reference)

You may **reference** any of these but cannot mint new ones without
a PR against `schema/v0.1/enums/capabilities.yaml` in the
Architecture repo.

**Capabilities are declared only in the Architecture repo — never in a
downstream/app producer.** A `cap:` is reference-only: name it as a
`Realization` target (something you own realizes it) or an `Association`
target (something you own consumes it). Do **not** put a `capabilities:`
array in your artifact — the enum is the single source of truth for each
capability's id, label, summary, and lifecycle, and the collector
materializes one shared node per *referenced* capability straight from it.
Declaring your own copy duplicates the enum and is rejected at review.

**In-house firmware Realizes `cap:iot-device`.** If your repo is one of the
in-house ESP32 firmware devices (managed by IoTSupport, integrated via MQTT
discovery), add a `Realization` from your firmware `ss:` element to
`cap:iot-device`. That single edge is the selection axis for the IoT view —
it is how your device shows up in it.

**Browser UIs Realize `cap:web-ui`.** If a service or interface offers a
browser-facing UI a human opens, add a `Realization` to `cap:web-ui` — the
homeapps launcher surfaces every `cap:web-ui` interface (prd) as a tile. It is a
positive opt-in: mark only human UIs. An HTTP server is not a web UI — machine
endpoints never get it (REST/gRPC APIs, `/metrics`, MQTT/pub-sub, S3/object
storage, MCP servers, image registries, ACME/CA). Prefer marking the
**interface** when one service backs both a UI and a non-UI surface (e.g.
OpenBao's 443 console vs its 8200 admin API) so only the UI becomes a tile.

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
cap:iot-device                IoT device (in-house ESP32 firmware; MQTT-discovery, managed by IoTSupport)
cap:mcp                       Model Context Protocol server (tools/resources for LLM agents)
cap:web-ui                    Browser-facing web UI a human opens (homeapps launcher tiles; opt-in, never for APIs)
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

**Generated producers** add a **generate** step first and do **not**
commit the YAML — regenerate, validate, archive:

```groovy
stage('Generate') { sh 'python tools/gen-architecture.py' }   // may need helm/etc. on the agent
stage('Validate') { sh './scripts/arch-validate.py docs/architecture/*.yaml' }
stage('Archive')  { archiveArtifacts artifacts: 'docs/architecture/*.yaml', fingerprint: true }
```

No first-build bootstrap deadlock: `arch-validate` doesn't resolve
cross-producer refs (that's merge-time), so build order only affects
dangling refs in `validation-report.json` until the referenced producer
has an archived build — reported, not build-breaking. Don't skip
validation on the first build.

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
| DockerImages | Each in-house app's **full logical architecture** — the «SoftwareProduct» identity (`app:<name>,<uuid>`, via `sourceRepository`), the ApplicationServices/Interfaces it exposes, any capability it realizes, and its consumption edges. Source for many apps lives here, so it plays the per-app-repo role for each. Image identity / build provenance is a *separate* concern, still v0.2 (no v0.1 element kind for container images). |
| Architecture (self-producer) | Homeless elements: physical network/rack hardware, IoT/RF devices, Home Assistant. Files live under `docs/architecture/` in the Architecture repo itself. |

### Product vs instance, across producers

The dividing line that decides who emits what — the most common
merge-conflict point:

- The repo where an in-house app's **source** lives owns the
  «SoftwareProduct» catalog entry (DockerImages owns
  `app:git-sync,<uuid>`).
- The repo that **deploys** it owns the running **instance** and the
  `Specialization` instance→product edge — referencing the product by
  its UUID.
- A **repackaged upstream** image emits no product of its own; the
  **deployer** owns the upstream product entry (`ss:dnsmasq,<uuid>`,
  `ss:keycloak,<uuid>`). When more than one producer deploys the same
  upstream, one owns the single catalog entry and the others reference
  its UUID.
- A product is declared **once**; everyone else references the UUID,
  resolved from the published dataset.
- **Model what a thing is, not how it's packaged.** A custom-built image
  that is really an upstream product plus baked config — a Postgres image
  with an init script — is modelled as the upstream product
  (`ss:postgresql`, realizing what it provides), not as a bespoke in-house
  product. The packaging is a build artifact; the element is the database
  it runs. The source repo owns no product for it.

### Consuming another producer's platform

When your element "runs on" / "uses" another producer's platform,
attach to its **running instance** — not the `Node` (that skips the
platform layer; pods don't run on bare metal) and not the
«SoftwareProduct» catalog entry (that's the type, not a running thing).
The other producer owns
node→instance and instance→product; you own only the consumption edge.
Two shapes:

- **Consume directly** — attach your workload straight to their running
  service: a pod `Serving`-consumes `ss:microk8s-prd,<uuid>`.
- **Re-provide via your own service layer** — deploy a driver that
  consumes their backend and `Realization`-s a new cluster-local
  `TechnologyService` **you** own, which your workloads then consume.
  Ceph storage: `ceph-csi-rbd` realises `svc:cluster-ceph-rbd,<uuid>`
  (yours), served by Ansible's `svc:ceph-vip-prd,<uuid>`.
- **Operator-mediated** — a deploy-time operator reads a backend on behalf
  of many workloads and hands them a *derived* local resource. The real
  runtime edge is `backend —Serving→ the operator`, drawn once from the
  deployer-owned config that wires them; the workloads depend on the
  derived resource (a Kubernetes Secret, read through the platform), not on
  the backend, so they get **no** edge to it. External Secrets Operator
  reading OpenBao: `svc:openbao-api-prd —Serving→ the ESO controller`,
  derived from the deployer-owned ClusterSecretStore — not one edge per
  consuming app, and not OpenBao→app (the apps can't even address it).
  Attach to the controller instance (the primary workload realizing the
  capability), not the whole operator deployment set.

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
  - id: ss:openbao-prd,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    label: OpenBao (prd)
    summary: Production OpenBao instance providing secrets management.
    introduced: 2026-05-27
    lifecycle: active
    environment: prd

  - id: ss:openbao,9b2e7c4d-1a6f-4b3e-8d5c-2f7a9c0e1b3d
    label: OpenBao
    summary: Open-source HashiCorp Vault fork for secrets management.
    introduced: 2026-05-27
    lifecycle: active
    stereotype: SoftwareProduct
    homepage: https://openbao.org/

relations:
  - id: rel:openbao-realises-secrets
    source: ss:openbao-prd,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    target: cap:secrets-management
    type: Realization

  - id: rel:openbao-specialises-product
    source: ss:openbao-prd,8a4b3c2d-9e5f-4a6b-b7c8-2d3e4f5a6b7c
    target: ss:openbao,9b2e7c4d-1a6f-4b3e-8d5c-2f7a9c0e1b3d
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

A **generated** producer inverts steps 2–3: instead of minting ids and
hand-authoring, design the annotation layer + generator (ids derive from
natural keys) and run the generator to produce the YAML. See Generated
producers.
