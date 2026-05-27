# 03 — Data migration (superseded; no migration)

**Status: superseded 2026-05-27.** This plan is intentionally a no-op. The original draft proposed a hand-migration of the legacy 145-node dataset in `viewer/src/data/architecture.ts` into the new ArchiMate-based schema. After the v0.1 schema landed and we walked through the inventory, that approach was scrapped: a one-shot rewrite of the legacy data produces an artifact with no further use, and the underlying taxonomy was wrong enough that "migration" would have been "re-derivation" in disguise.

## What replaces this plan

- **Legacy data stays in place.** `viewer/src/data/architecture.ts` is not touched. The current diagram keeps rendering it.
- **Federated data is built fresh.** Each producer (Ansible first, then Helm, then app repos) emits its own architecture artifact against the v0.1 schema. The Architecture pipeline merges them; the viewer eventually consumes the merged dataset.
- **The legacy file is deleted, not migrated.** When the federated dataset is rich enough that the swap is a net improvement, `viewer/src/data/architecture.ts` is removed and the viewer is repointed. That is v5 work, planned at the time, not now.

See [`00-roadmap.md`](./00-roadmap.md) for the revised phase ordering, [`04-producer-protocol.md`](./04-producer-protocol.md) for how producers emit, and [`05-collector-and-pipeline.md`](./05-collector-and-pipeline.md) for how the Architecture pipeline assembles the merged artifact.

## Why this matters when you read the rest

Anything in this directory or in `docs/features/` that still refers to "migrating the 145 nodes" or "audit table" is stale. The intent is to abandon the legacy data, not transform it.

If you're looking for the original (pre-2026-05-27) migration plan, it is preserved in git history; commit `fa016d4` and earlier carry the full draft.
