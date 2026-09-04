# Adding a capability to the enum

A new `cap:` entry in `schema/v0.1/enums/capabilities.yaml` touches **three** places — only two
are wired together, so the third is easy to forget, and it has bitten us. Do all three in the
same commit.

1. **Add the entry** to `schema/v0.1/enums/capabilities.yaml`.
2. **Regenerate** `viewer/src/generated/vocab.ts` (and the JSON Schemas under
   `schema/v0.1/generated/`) via the generator:
   ```bash
   cd tooling && cexec modern-app poetry run python generate.py          # writes generated/ + viewer vocab
   cd tooling && cexec modern-app poetry run python generate.py --check   # CI guard: fails if anything is stale
   ```
3. **Hand-add an icon** to `CAPABILITY_ICON` in `viewer/src/theme.ts`. This map is *not*
   generated; it's typed `Record<CapabilityId, LucideIcon>`, so a missing key fails only at the
   viewer's `tsc` step — a separate Jenkins job from the enum change. Easy to miss; do it in the
   same commit as the enum entry.
