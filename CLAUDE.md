# Architecture

Architecture is a federated **Architecture-as-Code** system for [webathome.org](https://webathome.org)
and the homelab behind it. Producer repos emit `architecture.yaml`; the `tooling/` pipeline merges
and validates them against the metaschema into a published dataset; the `viewer/` (React +
ReactFlow + ELK) renders it, served by the `service/` container at `architecture.webathome.org/viewer/`
and iframe-embedded into webathome.org. See `README.md` for the full picture.

**Public repo — assume world-readable.** No secrets, credentials, internal hostnames/IPs, or
non-public names, anywhere. This and the rest of the change-discipline rules are in
[`docs/change-discipline.md`](docs/change-discipline.md).

## Repo structure

The four components are what `kc project list` returns; each subproject has its own `CLAUDE.md`
and `docs/`.

- **Root** — project docs (`docs/`), the `schema/` v0.1 metaschema + enums (source of the generated
  JSON Schemas and viewer vocab), and this repo's own published architecture artifact
  (`docs/architecture/`).
- **`tooling/`** — the Python (Poetry) merge pipeline: `collect.py` → `generate.py` → `validate.py`,
  plus the metaschema codegen.
- **`viewer/`** — the React + ReactFlow + ELK viewer (Vite, TypeScript, npm) that renders the
  merged dataset.
- **`service/`** — the Express + TypeScript service (npm) serving the viewer bundle and the
  published dataset/API. Its image is the deliverable.
- **`arch/`** — the `arch` Claude Code plugin packaging the producer-onboarding tooling, installed
  into `~/.claude/` from here (see [`docs/arch-plugin.md`](docs/arch-plugin.md)).

Everything builds through `kc project`; the toolchain lives in the `modern-app` sidecar, so ad-hoc
poetry/npm commands need `cexec modern-app`.

## Working rules

**Commit early and often, each meaningful unit, without being asked** — in this repo and the specs
repo alike; never batch unrelated changes.

**Work directly on `main`; no topic branches, and push as you go.** Single-person homelab, no other
committers to coordinate with. Don't make "ahead of origin" remarks — just push. Note that a push
to `main` triggers CI and redeploys production.

**Design philosophy:** clean breaking changes, no tombstones, no defensive coding, testability is
non-negotiable — stated in full, with what each means per component, in
[`docs/change-discipline.md`](docs/change-discipline.md).

## The dev pipeline

Code changes go through the `dev` plugin's slice workflow — `/dev:triage` → `/dev:plan-slice` →
`/dev:run-slice` — which the operator drives; **never start a run yourself.** The project's half of
the contract is `.aiworkflowrc` and `.kubecoder/project.yaml`. The specs repo at
`../ArchitectureSpecs` holds slices and the decision index; it is a separate git repo, so commit
there separately.

This repo's own skills, beyond the plugin's: `/update-docs` (reconcile the doc set) and
`/ux-design`.

Issue tracking follows the host convention; this project's owner tag is **`Architecture`**.

## Documentation

Design and conventions live in `docs/` — one per scope (root for cross-cutting, plus one per
subproject), as small topic docs indexed for reading-list assembly. The rules and the maintenance
model are in [`docs/documentation-model.md`](docs/documentation-model.md); the short version is
that rationale is ordinary documentation rather than a decisions log, and doc upkeep follows
authorship.

## Key documentation

- [`docs/documentation-model.md`](docs/documentation-model.md) — how the docs are organized and kept current (read first).
- [`docs/index.md`](docs/index.md), plus `tooling/`/`viewer/`/`service/` `docs/index.md` — per-scope indexes; assemble a reading list from these.
- [`docs/change-discipline.md`](docs/change-discipline.md) — the change rules every code change obeys.
- [`docs/capability-enum.md`](docs/capability-enum.md) — the three places a `cap:` enum entry must touch. Easy to forget; it has bitten us.
- [`docs/deployment.md`](docs/deployment.md) — the self-hosted K8s/Jenkins context the container ships into.
- [`docs/arch-plugin.md`](docs/arch-plugin.md) — the `arch/` producer-onboarding plugin.
- `../ArchitectureSpecs/decisions.md` — the thin `DNNN` decision index.
