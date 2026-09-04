# Architecture — Tooling

The `tooling/` subproject is the Python (Poetry) merge pipeline: it collects producer
`architecture.yaml` files (`collect.py`), merges and generates the published dataset + JSON
Schemas + the viewer vocab from the v0.1 metaschema (`generate.py`), and validates the result
(`validate.py`). It is the leading subproject — `viewer` and `service` consume what it emits.

## Sandbox environment

- The monorepo is at `/work/Architecture`. Dev agents work scoped to `tooling/` but commit to the single shared repo.
- Python ≥3.11, **Poetry** (`tooling/pyproject.toml`, `package-mode = false`). Poetry lives in the `modern-app` tool sidecar; run commands from `tooling/` as `cexec modern-app poetry run <cmd>`. `kc project setup --project tooling` does the install.

## Design philosophy

- **Clean breaking changes.** Greenfield, no external consumers — fix callers instead of adding shims.
- **No tombstones.** Delete replaced code completely — no "moved to X" comments, no stubs, no deprecated aliases.
- **No defensive coding.** No try/except that swallows errors, no drop-the-bad-input-keep-going paths, no null-guards for conditions the metaschema/framework already prevents. Boundary validation (the metaschema, producer input) is the *point*; fail loudly. Prefer obvious-now failure over silent-corruption-later.
- **Testability is critical.** Every change ships with a test; a feature without one is incomplete.

## Specs repo

Planning documents (change briefs, plans, reviews) live in `../ArchitectureSpecs`. For context on a slice or prior decision, look there.

## Documentation

This subproject's design + conventions live in **`docs/`**, indexed by **`docs/index.md`** — the entry point a plan's required-reading list is built from. Cross-cutting and system-level design lives in the **root** [`docs/`](../docs/index.md); the [documentation model](../docs/documentation-model.md) governs the whole set. A change that alters the design or a convention here is not done until its doc — and, for a decision, the thin `DNNN` index (`../ArchitectureSpecs/decisions.md`) — reflects it.

**Cross-subproject:** schema/enum changes are regenerated via `generate.py` (CI runs `--check`); a new `cap:` enum entry also needs an icon in `viewer/src/theme.ts` — see [`../docs/capability-enum.md`](../docs/capability-enum.md).

## Testing expectations

- Tests live under `tooling/tests/`. Every change ships with coverage.

## Code quality

Before committing, verify:

```bash
kc project lint --project tooling
```

Individual tools:

```bash
cexec modern-app poetry run pytest          # tests
cexec modern-app poetry run ruff check .    # lint
cexec modern-app poetry run mypy .          # types (strict)
```

## Decision-making

Choose an approach and commit to it; don't revisit unless new information contradicts your reasoning. Read what you need for the task — don't over-explore the codebase.
