# 03 — Data migration (v1, execution)

Apply the schema from `02-metaschema.md` to the existing 145-node data file. All work happens in the new repo, against `viewer/src/data/architecture.ts` (the file that moved as-is in v0). Output: schema-valid, hand-authored data that the viewer renders correctly. Federation work is out of scope here.

## Strategy

The current `ArchitectureNode` shape is one row per "thing." The new model often splits one row into multiple. The migration is therefore a re-derivation, not a field rename.

For each current node, decide:

1. What **capability** does this thing realize? (Pick from the enum being defined in parallel; new capabilities require a schema PR.)
2. What **product** is it? (Same — enum.)
3. What is the **component**? (One per concrete instance. Most current nodes become exactly one component; a few become more — see "splits" below.)
4. What other nodes does it depend on, and what edge type expresses that?

The output is three lists (capabilities, products, components) plus an edge list plus an optional groups list — replacing the single `architectureNodes` array.

## Working format

Migrate from the current TypeScript-typed array to YAML or JSON, with the JSON Schema validating it. TypeScript types are derived for the viewer from the schema (via `json-schema-to-typescript` or equivalent).

Files in the new repo after v1:

```
viewer/src/data/
├── capabilities.yaml          # cap:* enum entries (or imported from schema enums)
├── products.yaml              # prod:* enum entries (or imported from schema enums)
├── components.yaml            # comp:* entries with GUIDs
├── edges.yaml                 # edge:* entries
└── groups.yaml                # group:* entries
```

If editing experience suffers with five files, one combined `architecture.yaml` is acceptable. Validator runs identically either way.

## Audit pass: catalog and assignments

Before writing any data, produce an **audit table** mapping every current node to its new representation. Format:

| Current ID | Current label | Current kind | Current capability | → Capability | → Product | → Component(s) | Notes |
|---|---|---|---|---|---|---|---|

This is grunt work but it surfaces every taxonomy bug. Likely outputs:

- **Keycloak**: `cap:sso` realized-by `comp:<guid>` "Keycloak (prd)" packaged-as `prod:keycloak`. (The original example.)
- **MetalLB**: probably `cap:load-balancer-ip` realized-by a single component, product `prod:metallb`.
- **CoreDNS**: `cap:dns` (cluster scope). Note this co-exists with `dnsmasq` which is also `cap:dns` (LAN scope) — two components realize the same capability, in different scopes. Worth a `scope` attribute or two distinct capabilities (`cap:dns-cluster`, `cap:dns-lan`); decide during the audit.
- **postgresql, elasticsearch, rabbitmq, mosquitto, opensearch**: each is one component (one deployed instance) with a clear product and capability.
- **Helm charts, dockerimages, helmcharts, ansible, terraform, kaniko, jenkins, github, gitblit**: these are the delivery layer. Many of these are *components* (running services) with edges to other components. A few (Ansible, Terraform) are agents that `deploys` infrastructure but aren't themselves runtime in the cluster — they still belong as components, deployed somewhere with a known location.
- **`design-assistant`, `iot-support`, `electronics-inventory`, `zigbee-stack`, `homeassistant-mcp`, `gitblit-mcp`**: app-layer. Each will eventually fragment into multiple components (pods, APIs, storage) in v3 when those repos start federating. In v1 they migrate as single components — the same shape as today — and federation replaces them later.

## Splits and merges

Cases where one current node becomes multiple new ones:

- **A "service" that is really a capability with multiple realizations**: e.g., if "DNS" exists as a single node but both CoreDNS and dnsmasq fill the role, split into one capability + two components.
- **Bundled deployments**: if a node represents what is actually a Helm chart deploying several distinct services (a stack), each service becomes its own component, joined by a group.

Cases where multiple current nodes become one:

- **Duplicated representations of the same thing**: unlikely in the current data but worth checking during the audit.

The audit table is the SSOT for these decisions. Do not migrate ad-hoc.

## Edge migration

The current `architectureEdges` list uses an older edge-type vocabulary. Map each existing edge to the new vocabulary (`02-metaschema.md` § Edges). Most map cleanly. The `strength: primary | secondary` field becomes `criticality`. Edges already point to nodes by ID — translating those IDs to the new component GUIDs is mechanical once the component table is built.

Edges between current nodes that the new schema doesn't allow (e.g., an edge whose endpoint is now a capability rather than a component) need fixing during the audit, not during migration. Examples to watch for:

- An app `authenticates-via Keycloak` edge is correct: endpoint is the Keycloak component.
- An app `authenticates-via SSO` edge is wrong: endpoint must be the realizing component, not the capability.

If a current edge is logically capability-level, lift it to all realizing components or drop it. Don't keep capability-level edges in the data; that's a view-time concern.

## Render-only field deletion

Remove from every node:

- `position` (the dead `x: number, y: number` — confirmed unused; the diagram is fully auto-layout).
- `layer` (replaced by capability-derived rendering — the renderer can group by capability or by an explicit layering view).

Audit any other fields on `ArchitectureNode` that exist only to influence rendering and remove them. The schema validator will reject them after v1, so the migration must produce a clean dataset.

If a field turns out to carry semantic information that's not just rendering — flag during the audit and add to the schema before deletion.

## GUID assignment

Mint UUIDv4 for every component during migration (one-time, batch). Record them in `components.yaml`. Once minted, never change. The current string IDs (`proxmox`, `udm-pro`, …) are *not* stable IDs; they were chosen for source readability and have already drifted in places. Drop them entirely.

To keep source diffs readable, the YAML entries can carry both the GUID (`id:`) and a human-friendly slug (`slug:`) — the slug is for grep'ability only, never referenced in edges or other entries. Validator should warn on slug collisions but not fail.

## Lifecycle state for the existing 145 nodes

Default everything to `active`. Exceptions to find during the audit:

- **phpMyAdmin**: `removed` (MySQL is gone). Producer keeps the entry for one cycle, then deletes.
- Anything tagged with the current `status: legacy` or `status: out-of-band`: review case-by-case. Probably `deprecated` with a `retirement-by` date.
- Anything `status: dev`: `active` is correct; "dev" was conflating environment with lifecycle. The schema does not model multi-environment; assume prd.
- Anything `status: unclear`: treat as a defect to resolve during the audit. Don't migrate unclear status into the new model.

## Capability and product enum population

The enums are populated **from** the migration, not before it. The audit determines the initial set. Pre-defining the enums risks missing categories; deriving them from real data is more reliable for a v0.1 schema. After v0.1 is locked, additions go through schema PR.

Initial enum size estimates from a quick read of current data:

- ~12–15 capabilities (sso, secrets, dns-cluster, dns-lan, load-balancer-ip, ingress, object-storage, block-storage, file-storage, message-broker-amqp, message-broker-mqtt, logs, metrics, observability-traces, builds, registry, config-management, vpn, etc.).
- ~40–60 products (one per piece of software).

## Stack ticker reconciliation

The site's `src/data/stack.ts` (still in this repo, not moving) is a curated tech-stack ticker. Many entries overlap with what becomes `prod:*` in the new schema. Reconcile in v1:

- Every `prod:*` should ideally correspond to a stack ticker entry (or be a candidate for adding).
- Every stack ticker entry that represents a deployed thing should have a matching `prod:*`.

This is a portfolio coherence issue (CLAUDE.md: portfolio surface). One-time pass.

## Group migration

The current data has no groups. During the audit, identify the obvious groups in the existing 145 nodes that should collapse at capability-view zoom. Likely candidates:

- Observability stack: Prometheus + Grafana + Filebeat + Kibana + (OpenSearch or Elasticsearch).
- Delivery stack: Jenkins + Kaniko + DockerImages + registry.
- HA control: keepalived + haproxy.
- CSI drivers: ceph-csi + smb-csi.

Five to eight groups is plenty for v1.

## Validation as the gate

The migration is **done** when:

- [ ] `architecture-validate viewer/src/data/` exits 0.
- [ ] Every current edge has been migrated or explicitly dropped (with a note in the audit).
- [ ] Every capability and product in the enums is referenced by at least one component.
- [ ] The viewer renders the migrated data without runtime errors.
- [ ] Visual review: the diagram is recognizably the same homelab, with corrected taxonomy.
- [ ] Audit table is committed alongside the data as `docs/v0.1-migration-audit.md` for future reference.

Visual diff against the v0 baseline is *not* an exit criterion — the migration deliberately changes the rendering (some nodes split, layout differs because capability-derived grouping replaces hand-positioned coordinates).

## Out of scope here

- Federation. All data is hand-authored.
- Removing components in favor of producer-emitted data. That's v2/v3.
- Multi-environment, time-travel, business architecture — see roadmap "not in scope."
