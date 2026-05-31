# Plan 2 — Logo schema widening + library enum

**Read first:** [`00-overview.md`](00-overview.md) and the `project_viewer-rework`
auto-memory.

**Goal:** today `logo` is an attribute of the `SoftwareProduct` *stereotype*
(`schema/v0.1/subset.yaml:138`), a free-form filename. That means a `Device`
(e.g. the UDM Pro) or a `Node` cannot carry a logo. Widen `logo` to a **common
attribute available on every kind**, and **validate it against an enum generated
from the bundled logo library** (`viewer/public/logos/`) so a typo or a
missing-file reference fails the build. Producers specify the logo by **name
without the file extension** (e.g. `ubiquiti`, not `ubiquiti.svg`) — the enum is
the set of extension-stripped basenames, and the viewer resolves the actual
asset extension at render time. Sync the producer docs both ways per the
CLAUDE.md `architecture-process/` ↔ `~/.claude/` rule.

**Prerequisites:** Plan 1 (delivered) — its logo renderer
(`viewer/src/components/ArchitectureMap.tsx`) assumed `logo` was a full filename,
so switching producers to bare names requires touching the viewer here. Scope is
schema + generator + a small viewer change + docs. Not independent of the viewer
anymore: bare names need the generator-emitted name→file map (Step 2b) and the
viewer lookup (Step 2c).

---

## Step 1 — Move `logo` from stereotype to common, with a library-enum source

In `schema/v0.1/subset.yaml`:

- **Remove** `logo` from `stereotypes.SoftwareProduct.addedAttributes` (keep
  `homepage` and `sourceRepository` there).
- **Add** `logo` to `commonAttributes` as an enum sourced from the logo library:

  ```yaml
  commonAttributes:
    # …existing…
    logo:
      type: enum
      enumSource: logoLibrary      # generator lists viewer/public/logos/
      required: false
      description: >
        Name of a logo from the bundled library (viewer/public/logos/),
        without the file extension (e.g. `ubiquiti`). Picked from the curated
        set; validated against it. Optional, on any kind.
  ```

  `enumSource` is a new discriminator (spelled out, per the no-abbreviations
  rule). Rationale for an inline directory-scan over a hand-authored
  `enums/logos.yaml`: the library is a directory of binary assets, not a curated
  semantic catalogue; generating a YAML enum file to mirror a folder is ceremony.
  Inline keeps the generator the single source of truth and adds no served
  artifact. (Alternative if you prefer an explicit served enum: have the
  generator *write* `schema/v0.1/enums/logos.yaml` from the directory and
  reference it via `enumRef` — but then it must be wired through the
  `GENERATED_DIR` orphan logic carefully. Inline is recommended.)

**Why the stereotype must lose `logo`:** `emit_per_kind_schema` adds common
attributes first, then stereotype `addedAttributes`. If `logo` lived in both, the
stereotype loop would also treat it as stereotype-specific and rule 5b
(`generate.py:353`) would *forbid* `logo` whenever `stereotype` is unset —
exactly the kinds we're widening to. So `logo` must be common-only.

## Step 2 — Generator: resolve `enumSource: logoLibrary`

In `tooling/generate.py`:

- Allow `enumSource` in the meta-schema: add `enumSource: { type: string }` to
  `attributeSpec` in `schema/v0.1/subset.schema.yaml:70`.
- In `attribute_to_json_schema` (`generate.py:202`), under the `enum` branch,
  handle `enumSource`:

  ```python
  elif "enumSource" in spec:
      out["enum"] = resolve_enum_source(spec["enumSource"])
  ```

- Add `resolve_enum_source("logoLibrary")`: list `viewer/public/logos/` (only
  `.svg`/`.png`; skip `titles.json`), strip each file's extension, and return the
  **sorted, de-duplicated** set of basenames. So `ubiquiti.svg` → `ubiquiti`.
  Fail loudly (raise) if the directory is missing or empty — no fallback. Define
  the logos path relative to `REPO_ROOT`. Reuse this same scan in Step 2b so the
  enum and the name→file map are built from one directory listing.

  **Collision is an error, not a silent collapse.** The library is genuinely
  mixed (~57 `.svg`, ~14 `.png`: calico, gitblit, metallb, kaniko, rust, xaml,
  zigbee2mqtt, …). If a bare name exists as *both* `ubiquiti.svg` and
  `ubiquiti.png`, raise — we can't know which the producer meant, and the
  name→file map (Step 2b) would be ambiguous. Today there's no such collision;
  fail loud if one is ever introduced rather than picking one extension.

Determinism: sort the basenames so reruns are byte-identical.

## Step 2b — Generator: emit a name→file map the viewer resolves against

**Why this exists:** Plan 1 already shipped the logo renderer
(`viewer/src/components/ArchitectureMap.tsx:91`), and it interpolates the value
straight into the URL with no extension:

```jsx
rightImage = <img src={`${import.meta.env.BASE_URL}logos/${data.logo}`} alt="" />;
```

So a bare `logo: ubiquiti` would request `logos/ubiquiti` → 404. Since the library
is mixed `.svg`/`.png`, the viewer can't hardcode an extension, and a
try-`.svg`-then-`.png` fallback is exactly the kind of guess-on-404 hedge the repo
forbids. Instead the generator — which already lists the directory for the enum —
emits the authoritative mapping, and the viewer looks the name up. A missing entry
is a build-time/type error, not a runtime surprise, mirroring how `vocab.ts`
already makes a stale vocabulary a type error.

- Extend `emit_vocab_ts` (`generate.py:511`) — or add a sibling emitter writing
  the same `viewer/src/generated/` module — to also emit a `LOGO_FILES` map from
  bare name to actual filename, built from the **same** directory scan as the
  enum:

  ```ts
  export const LOGO_FILES = {
    "ubiquiti": "ubiquiti.svg",
    "proxmox": "proxmox.svg",
    "calico": "calico.png",
    // …
  } as const;
  export type LogoName = keyof typeof LOGO_FILES;
  ```

  Keep keys **sorted** for byte-identical reruns. The map's key set is identical
  to the `logoLibrary` enum, so the schema and the viewer can never disagree about
  which logos exist — same scan, two outputs.

- If you add a new generated module instead of extending `vocab.ts`, wire its path
  the way `VOCAB_TS_PATH` is (`generate.py:35`) and write it next to the
  `vocab.ts` write (`generate.py:602`). Don't route it through the
  `schema/v0.1/generated/` orphan-detection logic — that's for schema files, and
  `vocab.ts` already lives outside it.

## Step 2c — Viewer: resolve the bare name through the map

In `viewer/src/components/ArchitectureMap.tsx:90-91`, resolve `data.logo` through
`LOGO_FILES` instead of using it as a filename:

```jsx
if (data.logo) {
  const file = LOGO_FILES[data.logo as LogoName];
  if (!file) {
    console.error(`[viewer] unknown logo '${data.logo}' — vocab is stale, rebuild`);
    rightImage = <span className="arch-node__stale-mark">?</span>;
  } else {
    rightImage = <img src={`${import.meta.env.BASE_URL}logos/${file}`} alt="" />;
  }
}
```

This mirrors the existing stale-capability branch right below it
(`ArchitectureMap.tsx:92-101`) — same "vocab is stale, rebuild" failure mode, same
`arch-node__stale-mark` fallback. Note the data model already types `logo?: string`
(`viewer/src/data/manifest.ts:30`); the validated artifacts only ever carry a name
that's in the enum, so the map lookup succeeds for real data — the guard exists
only to surface a stale generated module.

Also update the sample fixture `viewer/public/sample-architecture.json`: it
currently uses extension-bearing values (`"logo": "proxmox.svg"`, `"ubuntu.svg"`,
`"kubernetes.svg"`, `"openbao.svg"`, `"ubiquiti.svg"`, `"keycloak.svg"`,
`"postgresql.svg"`). Strip the extensions so the fixture matches the new schema and
exercises the map lookup.

## Step 3 — Regenerate and verify

```
cd tooling
poetry run python generate.py            # rewrites schema/v0.1/generated/*.schema.yaml + viewer/src/generated/
poetry run python generate.py --check    # clean
```

Every per-kind generated schema now carries `logo` as an optional enum-typed
property (e.g. `device.schema.yaml`, `node.schema.yaml` gain it), and the viewer's
generated module gains the `LOGO_FILES` map (Step 2b). Confirm:

- A `Device` with `logo: ubiquiti` validates.
- A `logo: ubiquiti.svg` (with extension) fails validation — the enum holds
  bare names.
- A `logo: not-in-library` fails validation.
- `SystemSoftware`/`ApplicationComponent` still validate with `logo` set, now
  without needing `stereotype: SoftwareProduct`.
- `LOGO_FILES` keys exactly match the `logoLibrary` enum, and each value is a real
  file in `viewer/public/logos/` (e.g. `calico` → `calico.png`, `ubiquiti` →
  `ubiquiti.svg`).

Validation runs through the shared `_arch.validate_doc` used by both
`tooling/validate.py` and `tooling/collect.py`, so producer CI and the pipeline
pick up the change automatically. Run the collector over the test fixtures /
real `docs/architecture/*.yaml` to confirm a clean build.

Viewer check: `cd viewer && pnpm build` (or the project's typecheck) — the
`LogoName` lookup must compile, and the updated `sample-architecture.json` should
render every logo (bare names resolved through `LOGO_FILES`), no broken images.

## Step 4 — Producer manual sync (both directions)

`architecture-process/producer-manual.md` documents `logo` under the
«SoftwareProduct» section (around line 214). Update it:

- Move the `logo` bullet out of «SoftwareProduct» into the common-attributes
  description: "available on any element kind, validated against the bundled
  logo library; use the file's name without its extension (e.g. `ubiquiti` for
  `viewer/public/logos/ubiquiti.svg`)."
- Document **how to add a new logo:** drop the SVG/PNG into `viewer/public/logos/`
  and regenerate (`poetry run python tooling/generate.py`) so the enum picks it
  up; reference it by its bare name (no extension). Until regenerated,
  referencing it fails validation.
- Keep `homepage` and `sourceRepository` under «SoftwareProduct».

Then mirror to the live copy at `~/.claude/architecture/producer-manual.md` (and
check `~/.claude/architecture/architecture.yaml` starter — if it shows a `logo`
under a stereotype example, move it). **Diff both sides before editing**; if
they've drifted, surface the drift rather than overwriting. Filename map is in
the repo `CLAUDE.md`.

## Step 5 — (Optional) backfill logos on real producers

Now that all kinds can carry `logo`, optionally enrich the real producer
artifacts — e.g. `docs/architecture/infrastructure.yaml` Devices (UDM Pro →
`ubiquiti`, the PVE chassis → `proxmox`), `home-automation.yaml`. Keep
this small and only where a library logo genuinely exists. The old static viewer
data (`viewer/src/data/architecture.ts`, removed in Plan 1) is a good reference
for which element had which logo.

## Acceptance criteria

- `poetry run python generate.py --check` clean after regeneration.
- A Device/Node with a library `logo` (bare name, no extension) validates; an
  unknown name or a name with an extension fails.
- `logo` no longer requires `stereotype: SoftwareProduct`.
- Generator emits `LOGO_FILES` (name→filename) into `viewer/src/generated/`, keys
  identical to the `logoLibrary` enum; a name present as both `.svg` and `.png`
  fails the build rather than collapsing silently.
- Viewer resolves `data.logo` through `LOGO_FILES`; bare names render, and the
  updated `sample-architecture.json` shows no broken images. `pnpm build`/typecheck
  passes.
- Producer manual updated and mirrored to `~/.claude/…`, with the
  "how to add a logo" note; no undisclosed drift between the two copies.

## Suggested commits

1. `subset.yaml` + `subset.schema.yaml` + `generate.py`: widen `logo`, add
   `enumSource: logoLibrary`, emit the `LOGO_FILES` map.
2. Regenerated `schema/v0.1/generated/*.schema.yaml` + `viewer/src/generated/`.
3. Viewer: resolve `data.logo` via `LOGO_FILES` in `ArchitectureMap.tsx`; strip
   extensions in `sample-architecture.json`.
4. Producer manual update + `~/.claude` mirror.
5. (optional) backfill logos on real producer artifacts.
