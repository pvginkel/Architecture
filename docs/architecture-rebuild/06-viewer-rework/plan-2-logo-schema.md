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

**Prerequisites:** none. Standalone — schema + generator + docs. Independent of
the viewer plans (the viewer reads `element.logo` regardless of where the schema
declares it).

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

- Add `resolve_enum_source("logoLibrary")`: list `viewer/public/logos/`, strip
  each file's extension (both `.svg` and `.png`), and return the **sorted,
  de-duplicated** set of basenames. So `ubiquiti.svg` → `ubiquiti`; if a name
  exists as both `.svg` and `.png` it collapses to one enum entry. Fail loudly
  (raise) if the directory is missing or empty — no fallback. Define the logos
  path relative to `REPO_ROOT`.

Determinism: sort the basenames so reruns are byte-identical. The viewer is
responsible for resolving a bare name back to a concrete asset (prefer `.svg`,
fall back to `.png`) — out of scope for this plan, noted for the viewer work.

## Step 3 — Regenerate and verify

```
cd tooling
poetry run python generate.py            # rewrites schema/v0.1/generated/*.schema.yaml
poetry run python generate.py --check    # clean
```

Every per-kind generated schema now carries `logo` as an optional enum-typed
property (e.g. `device.schema.yaml`, `node.schema.yaml` gain it). Confirm:

- A `Device` with `logo: ubiquiti` validates.
- A `logo: ubiquiti.svg` (with extension) fails validation — the enum holds
  bare names.
- A `logo: not-in-library` fails validation.
- `SystemSoftware`/`ApplicationComponent` still validate with `logo` set, now
  without needing `stereotype: SoftwareProduct`.

Validation runs through the shared `_arch.validate_doc` used by both
`tooling/validate.py` and `tooling/collect.py`, so producer CI and the pipeline
pick up the change automatically. Run the collector over the test fixtures /
real `docs/architecture/*.yaml` to confirm a clean build.

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
- Producer manual updated and mirrored to `~/.claude/…`, with the
  "how to add a logo" note; no undisclosed drift between the two copies.

## Suggested commits

1. `subset.yaml` + `subset.schema.yaml` + `generate.py`: widen `logo`, add
   `enumSource: logoLibrary`.
2. Regenerated `schema/v0.1/generated/*.schema.yaml`.
3. Producer manual update + `~/.claude` mirror.
4. (optional) backfill logos on real producer artifacts.
