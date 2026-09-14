# The capability enum

What belongs in `schema/v0.1/enums/capabilities.yaml`, when an entry can leave it, and the three
places a new entry touches.

## What belongs in the enum

A `Capability` is a strategy-layer role (`layer: strategy` in `schema/v0.1/subset.yaml`), such as
identity and access management or secrets management. Producers never declare one. They name its
`cap:` id as the target of a `Realization` (something they own realizes the role) or of an
`Association` (something they own consumes it), and the collector materializes one node per
referenced id from the enum.

A property of a single access point is not a role, so it is never a capability. It is an attribute
on the element kind that carries it. A browser UI a human opens is marked by `webUi: true` on its
interface, not by a `Realization`. That boolean exists only on `ApplicationInterface` and
`TechnologyInterface`. The protocol an interface speaks (MCP, say) is not a capability either.

`cap:web-ui` and `cap:mcp` are tags of that kind, and producers still reference them. An entry can
leave the enum only once no producer references it: `reconcile_capability_enum` in
`tooling/collect.py` fails the whole collector run on any `cap:` id the enum does not hold.

## The three places a new entry touches

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
