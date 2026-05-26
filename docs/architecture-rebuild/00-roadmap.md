# Architecture diagram rebuild — roadmap

The architecture diagram in this repo is being rebuilt from a hand-authored, 145-node static SVG-ish thing into a federated, schema-driven system that pulls metadata from every producing repo (Ansible, HelmCharts, DockerImages, EI, IOT, …) and renders a single filterable diagram of the entire homelab + apps estate at pod / API / storage granularity.

This document is the index. Each phase has a dedicated plan.

## Why

- The current taxonomy is broken: `label`, `kind`, `capability`, `layer` overlap and confuse capability (SSO) with implementation (Keycloak).
- Hand-maintenance does not scale past ~150 nodes, and the diagram is meant to be the portfolio surface (CLAUDE.md: feature 25, "load-bearing").
- Different repos own fundamentally different node types (VMs, Helm releases, images, app pods). The architecture data should be sourced from the repo that owns it.

## Phases

### v0 — Extract as-is

Move the current diagram (component, data, styles, assets) into a new dedicated repo. Build it as a static container, iframe-embed it back into webathome.org. No data changes — even the dead `position` fields move with it, removed in v1.

Exit criteria:
- New repo exists, container builds, deploys to the homelab via existing Jenkins/Ansible path.
- webathome.org renders the diagram via iframe; content is byte-identical to today.
- This repo's `src/components/architecture/`, `src/data/architecture.ts`, `src/styles/architecture.css`, `src/pages/architecture.astro`, and the relevant `public/logos/` assets are deleted.

Plan: [`01-repo-extraction.md`](./01-repo-extraction.md).

Public risk: none. The diagram looks identical from the user's perspective.

### v1 — Schema + in-place migration (in the new repo)

Lock the metaschema v0.1 (capability / component / product split, edge types, enumerations, stable-ID strategy, lifecycle, producer profiles). Migrate the existing 145 nodes against it: fix taxonomy (Keycloak → realizes `cap:sso`, etc.), delete render-only fields from data, retire the conflated `kind` field. Data is still 100% hand-authored.

Exit criteria:
- JSON Schema published from the new repo, versioned `0.1`.
- Validator CLI exists; current data passes.
- Every component has a stable GUID and a lifecycle state.
- Taxonomy is correct: no capability/implementation conflation remains in the data.
- Render-only fields (`position`, hardcoded sizes) are gone from data; layout is fully derived.

Plans: [`02-metaschema.md`](./02-metaschema.md), [`03-data-migration.md`](./03-data-migration.md).

Public risk: small. The diagram is visible from the new repo while taxonomy is being fixed. Acceptable; bounded duration.

### v2 — First federated producer end-to-end

Pick HelmCharts as the first producer. It owns the most reusable infra IDs (Postgres, Keycloak, RabbitMQ, OpenSearch, etc.) and replacing the hand-authored entries for those nodes delivers the biggest reduction in drift surface. Wire: producer-side validator in CI → Jenkins artifact publish → collector trigger on the architecture repo → merge + render.

Exit criteria:
- HelmCharts produces a schema-valid artifact on every build.
- Architecture repo's collector pulls it, merges with remaining hand-authored data, fails the build on dangling references.
- Hand-authored entries for HelmCharts-owned components are removed.
- One named view exists; pipeline runs end-to-end without manual steps.

Plans: [`04-producer-protocol.md`](./04-producer-protocol.md), [`05-collector-and-pipeline.md`](./05-collector-and-pipeline.md).

### v3 — Roll out remaining producers + enforcement

Onboard Ansible, DockerImages, EI, IOT. Each follows the protocol established in v2.

Exit criteria:
- Every in-scope node type is sourced from its owning repo.
- Hand-authored data is reduced to what genuinely cannot be sourced (capability definitions, cross-cutting documentation).
- Dangling references fail the Jenkins build on the architecture repo.
- Deprecated stable IDs are honored: warnings on use, build failure on referencing a `removed` ID.
- Group rollup works: zooming out collapses producer-declared groups into single nodes.
- Named views are committed and shareable by URL.

## Inclusion rule

A thing belongs in the diagram if it has a **stable external identity that another component can reach by name** — a DNS name, a pod name, a queue name, a bucket name, a domain name, an API path. Classes, screens, internal functions are out. This rule is the answer to "non-trivial."

## Cross-cutting cleanups

These don't fit any single phase; track them here:

- **phpMyAdmin retirement.** The MySQL it served is gone. Remove the deployment, then remove the node from the diagram (in v1 if hand-authored, otherwise in v3 when HelmCharts stops emitting it).
- **Logo asset audit.** During v0 carry every referenced logo; during v1 confirm every component still has the logo it needs and delete orphans.
- **Stack ticker correlation.** The diagram's `prod:*` entries should align with `src/data/stack.ts` on webathome.org. Worth a one-time reconciliation pass in v1.

## Open questions deferred to their plans

- Iframe vs subdomain reverse-proxy: see `01`.
- Whether DockerImages is its own producer or folds into HelmCharts/app profiles: see `04`.
- Whether named views are committed YAML or rendered from URL state: see `05`.

## What is not in scope

- Business / data architecture (deferred, possibly forever).
- Class-level or screen-level detail.
- Historical (time-travel) views. The diagram shows current state only.
- Multi-environment rendering. One environment, the homelab prd cluster.
