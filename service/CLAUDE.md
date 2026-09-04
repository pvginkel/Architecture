# Architecture — Service

The `service/` subproject is the Express + TypeScript service that serves the built `viewer`
bundle and the published dataset/API: static serving with a CSP, dataset/schema endpoints with
validation, an ELK layout proxy, and Prometheus metrics. It is the container artifact deployed to
the homelab.

## Sandbox environment

- The monorepo is at `/work/Architecture`. Dev agents work scoped to `service/` but commit to the single shared repo.
- Node + **npm** (`service/package.json`, `package-lock.json`), `tsc` + Vitest. The Node toolchain lives in the `modern-app` tool sidecar; run commands from `service/` as `cexec modern-app npm run <script>`. `kc project setup --project service` does the `npm ci`.

## Design philosophy

- **Clean breaking changes.** Greenfield, no external consumers — fix callers instead of adding shims.
- **No tombstones.** Delete replaced code completely — no commented-out code, no dead re-exports, no "see X instead" stubs.
- **No defensive coding.** No try/catch that swallows errors, no drop-the-request-keep-serving paths, no silent fallbacks for inputs the schema/validator already guards. Boundary validation (the dataset/schema, request input) is the *point*; fail loudly. Prefer obvious-now failure over silent-corruption-later.
- **Testability is critical.** Every change ships with a test; a feature without one is incomplete.

## Specs repo

Planning documents (change briefs, plans, reviews) live in `../ArchitectureSpecs`. For context on a slice or prior decision, look there.

## Documentation

This subproject's design + conventions live in **`docs/`**, indexed by **`docs/index.md`** — the entry point a plan's required-reading list is built from. Cross-cutting and system-level design lives in the **root** [`docs/`](../docs/index.md); the [documentation model](../docs/documentation-model.md) governs the whole set. A change that alters the design or a convention here is not done until its doc — and, for a decision, the thin `DNNN` index (`../ArchitectureSpecs/decisions.md`) — reflects it.

## Testing expectations

- Vitest + supertest. Every change ships with coverage.

## Code quality

Before committing, verify:

```bash
kc project build --project service     # tsc (type-check + build)
```

Individual tools:

```bash
kc project test --project service      # vitest + supertest
```

## Decision-making

Choose an approach and commit to it; don't revisit unless new information contradicts your reasoning. Read what you need for the task — don't over-explore the codebase.
