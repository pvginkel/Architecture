# Architecture diagram rebuild — roadmap

The architecture diagram in this repo is being rebuilt from a hand-authored 145-node static thing into a federated, schema-driven system that pulls metadata from every producing repo (Ansible, HelmCharts, DockerImages, EI, IOT, …) and renders a single filterable diagram of the entire homelab + apps estate at pod / API / storage granularity.

This document is the index. Each phase has a dedicated plan.

## Why

- The current taxonomy is broken: `label`, `kind`, `capability`, `layer` overlap and confuse capability (SSO) with implementation (Keycloak).
- Hand-maintenance does not scale past ~150 nodes, and the diagram is meant to be the portfolio surface (CLAUDE.md: feature 25, "load-bearing").
- Different repos own fundamentally different node types (VMs, Helm releases, images, app pods). The architecture data should be sourced from the repo that owns it.

## Direction shift (2026-05-27)

After the v0.1 schema landed and we walked through the real inventory, two macro decisions changed:

1. **No data migration of the 145 legacy nodes.** Hand-rewriting the existing data into the new schema would produce a one-shot artifact with no further use. Instead, the federated dataset is built fresh from real producer emissions. The legacy `viewer/src/data/architecture.ts` stays untouched and continues to drive the rendered diagram until the federated dataset is substantive enough to replace it wholesale.

2. **Bootstrap from the platform layer upward.** Ansible produces architecture data first (because it owns Kubernetes, the VMs, OpenBao, the ZFS allocator, etc.). Helm references those IDs. Apps reference Helm's IDs. DockerImages adds image identity (v0.2 schema territory). The viewer is migrated **last**, only when the federated dataset is rich enough that the swap is a net improvement.

Both decisions are reflected in the phase plan below.

## Phases

### v0 — Extract as-is

Move the current diagram (component, data, styles, assets) into a new dedicated repo. Build it as a static container, iframe-embed it back into webathome.org. No data changes — even the dead `position` fields move with it, removed later (now: never; the legacy file stays as is).

Status: **done.** Repo `pvginkel/Architecture` exists, container builds, iframe-embedded.

Plan: [`01-repo-extraction.md`](./01-repo-extraction.md).

### v1 — Metaschema

Lock the metaschema v0.1: adopt ArchiMate 3.x as the reference model, vendor the XSDs + Archi relationship matrix, generate per-kind JSON Schemas from a subset declaration, author golden examples.

Status: **done.** See [`../features/metaschema-design.md`](../features/metaschema-design.md). Outputs at `schema/v0.1/`, tooling at `tooling/`.

There is **no v1 data migration** (the original `03-data-migration.md` plan is superseded — kept as a thin redirect doc).

### v2 — Validation service

Build the runtime container that hosts the schemas, validates artifacts via `POST /api/validate`, serves the rendered USAGE.md at the container root, and ships the `arch-validate` dev CLI. Replaces the current nginx-only container.

The service is **publish-only** for architecture data. It does not collect, merge, or assemble producer artifacts — that happens in v3's Architecture pipeline.

Status: **done.** Service code under `service/`; container builds and serves `/`, `/viewer/`, `/schema/v0.1/*`, `/api/validate`, `/healthz`, `/metrics`. `USAGE.md` at the repo root is rendered at `/`. `arch-validate` CLI at `scripts/arch-validate`. Helm chart updated in `pvginkel/HelmCharts` (port/probes/scrape annotations). Homelab deploy is the operator step left to verify.

Plan: [`../features/validation-service.md`](../features/validation-service.md).

### v3 — Producer protocol + Architecture-build collector

Define how a repo becomes a producer of architecture data; build the Architecture pipeline that pulls each producer's artifact and assembles the merged dataset.

Two pieces, one phase:

- **Producer protocol** (this repo's contract with producer repos): Jenkins archives `architecture.yaml` as a build artifact per build; producers reference cross-producer elements by UUID (alias hints optional, divergence warned); each producer's CI runs `arch-validate` and fails the build on non-zero exit; `«SoftwareProduct»` catalog entries are owner-emitted, not centrally curated.
- **Collector** (this repo's Jenkinsfile + `tooling/collect.py` running as a Docker build stage): the Jenkinsfile uses native `copyArtifacts` to pull each registered producer's last-successful `architecture.yaml` into the build context; the collector validates, merges, cross-checks, and emits `dist/data/v0.1/*` which the final image stage copies in. Fail-fast at every step — no drop-and-continue, no machine-enforced profile constraints.

Design docs: [`04-producer-protocol.md`](./04-producer-protocol.md), [`05-collector-and-pipeline.md`](./05-collector-and-pipeline.md). Work-item plan: [`../features/collector-and-pipeline.md`](../features/collector-and-pipeline.md).

### v4 — Bootstrap producer cycle

Bring producers online in dependency order. Each iteration: producer emits a richer artifact; Architecture pipeline picks it up automatically next build; merged dataset grows.

1. **Ansible** (first, platform layer). Architecture artifacts for Proxmox cluster, VMs, k8s clusters (prd + dev), OpenBao, step-ca-VM, HAProxy/keepalived, the ZFS volume allocator service. Mints UUIDs for every Node, SystemSoftware, and Service it owns; commits them in the Ansible repo.
2. **Helm** (cluster services). References Ansible's UUIDs to declare what runs on what cluster. Mints UUIDs for cluster-service SystemSoftware (Keycloak, shared Postgres, dnsmasq, registry, etc.) and their Services/Interfaces.
3. **Application repos** (EI, IoT, Design Assistant, webathome-org, others). Each emits its own ApplicationComponents + ApplicationServices/Interfaces; references Helm's UUIDs for shared Postgres, OIDC issuer, etc.
4. **DockerImages**. Image identity, build provenance. Likely a v0.2 schema bump (image kind + Specialization edges to «SoftwareProduct» entries).

Each step is independent. The pipeline-merge is the integration point; producers don't coordinate publishing.

### v5 — Viewer migration

The last step. By this point the merged dataset has enough breadth (platform + cluster services + a few apps) to be visually useful. Drop `viewer/src/data/architecture.ts`. Point the viewer at `data/v0.1/architecture.yaml`. Refactor the ReactFlow rendering to ArchiMate-layered styling (technology/application/strategy/business colours). The legacy file is deleted as part of this work.

Plan: TBD when v4 is far enough along to specify it.

## Inclusion rule (carried through)

A thing belongs in the diagram if it has a **stable external identity that another component can reach by name** — a DNS name, a pod name, a queue name, a bucket name, a domain name, an API path. Classes, screens, internal functions are out. Borderline cases default to **out**.

## Cross-cutting cleanups

- **phpMyAdmin retirement.** Will surface naturally when the legacy file is dropped in v5; no proactive work needed.
- **Logo asset audit.** Carry every referenced logo forward; let v5 cull orphans when the legacy file is dropped.
- **Stack ticker correlation.** The diagram's `«SoftwareProduct»`-marked elements should align with `src/data/stack.ts` on webathome.org. A one-time reconciliation pass during v4 (when Helm starts emitting product identities).

## What is not in scope

- Business / data architecture beyond the minimal `BusinessService` element kind (used only when IAM→SSO style realisations matter).
- Class-level or screen-level detail.
- Historical (time-travel) views. The diagram shows current state only.
- Multi-environment rendering. Producers may emit dev/tst/uat; the renderer filters to prd.
