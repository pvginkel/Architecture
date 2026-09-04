# Architecture — Viewer

The `viewer/` subproject is the React + ReactFlow + ELK viewer (Vite, TypeScript): it loads the
merged dataset `tooling` emits and renders it as an interactive ArchiMate graph (filters, derived
edges, ELK layout). It's served from the `service` container at `architecture.webathome.org/viewer/`
and iframe-embedded into webathome.org.

## Sandbox environment

- The monorepo is at `/work/Architecture`. Dev agents work scoped to `viewer/` but commit to the single shared repo.
- Node + **npm** (`viewer/package.json`, `package-lock.json`), Vite + Vitest. The Node toolchain lives in the `modern-app` tool sidecar; run commands from `viewer/` as `cexec modern-app npm run <script>`. `kc project setup --project viewer` does the `npm ci`.

## Design philosophy

The change-discipline rules — clean breaking changes, no tombstones, no defensive coding,
testability — are in [`../docs/change-discipline.md`](../docs/change-discipline.md), which states
what each of them means for this subproject specifically.

## Specs repo

Planning documents (change briefs, plans, reviews) live in `../ArchitectureSpecs`. For context on a slice or prior decision, look there.

## Documentation

This subproject's design + conventions live in **`docs/`**, indexed by **`docs/index.md`** — the entry point a plan's required-reading list is built from. Cross-cutting and system-level design lives in the **root** [`docs/`](../docs/index.md); the [documentation model](../docs/documentation-model.md) governs the whole set. A change that alters the design or a convention here is not done until its doc — and, for a decision, the thin `DNNN` index (`../ArchitectureSpecs/decisions.md`) — reflects it.

**Generated:** `src/generated/vocab.ts` is emitted by `tooling/generate.py` — never hand-edit it. A new `cap:` enum entry needs an icon hand-added to `CAPABILITY_ICON` in `src/theme.ts` (that map is *not* generated; a missing key fails only at the `tsc` step) — see [`../docs/capability-enum.md`](../docs/capability-enum.md).

## Testing expectations

- Vitest. Every change ships with coverage.

## Code quality

Before committing, verify:

```bash
kc project build --project viewer      # tsc --noEmit && vite build (type-check + build)
```

Individual tools:

```bash
kc project test --project viewer       # vitest
```

## Decision-making

Choose an approach and commit to it; don't revisit unless new information contradicts your reasoning. Read what you need for the task — don't over-explore the codebase.
