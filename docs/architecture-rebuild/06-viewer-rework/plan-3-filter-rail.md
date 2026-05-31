# Plan 3 — Two-panel filter rail

**Read first:** [`00-overview.md`](00-overview.md) and the `project_viewer-rework`
auto-memory.

**Goal:** turn the viewer into a two-panel layout — a left **filter rail**, the
rest canvas — modelled on the UDM topology filter panel
(`tmp/udm-filter-panel.png`). Replace Plan 1's stopgap control strip with proper,
collapsible filter groups, per-group search/scroll for large groups, a
selected-summary, Select-All, and a fixed **Clear filters** footer. Persist
collapsed state per manifest URL.

**Prerequisites:** Plan 1 (manifest loader, view-model, vocab, theme).

**Out of scope:** views and the view tab strip (Plan 4). Build the filter state
model so Plan 4 can set a baseline into it, but don't add tabs here.

---

## Step 1 — Two-panel shell

Restructure the layout in `ArchitectureMap.tsx` + `architecture.css`:

- Left `<aside class="filter-rail">`, fixed width (~300–320px), full height,
  its own vertical scroll for the group list; a fixed footer pinned to the
  bottom of the aside.
- Right: the `.diagram-region` (ReactFlow) fills remaining width.
- Use the existing CSS tokens (`--panel #fbfbf8`, `--line #dadbd2`,
  `--muted #696e68`, `--ink #242725`, `--panel-strong`). Match the calm light
  aesthetic; the UDM reference is dark — adapt, don't copy its palette.
- Mobile/narrow: the rail can collapse to a toggle (optional; the iframe is
  desktop-first — keep it simple).

## Step 2 — Derive filter groups from the manifest

New `viewer/src/filters/groups.ts`. Build, from the loaded manifest + vocab, an
ordered list of filter groups. Each group: `{ id, title, options: [{ value,
label, count }] }`, options sorted by count desc then label (UDM style).

Groups (this order):

1. **Element type** — kinds *present in the data*, `KIND_LABELS`, count = #
   elements of that kind (post other-filters or total — see Step 4).
2. **Relationship type** — relation `type`s present, `RELATIONSHIP_LABELS`.
3. **Layer** — the 5 `LayerId`s present, `LAYER_LABELS`.
4. **Producer** — `manifest.producers` (or distinct `element.producer`), counts.
5. **Environment** — `dev/tst/uat/prd` present, `ENVIRONMENT` labels.

Counts reflect the current dataset. Decide once and document: counts are computed
against the dataset **with all *other* groups' selections applied but not this
group's** (UDM behaviour — selecting in one group narrows the others' counts).
Simpler acceptable v1: counts against the full (prd-default) dataset. Pick one and
keep it consistent.

## Step 3 — `FilterGroup` component (collapsible; large-group treatment)

New `viewer/src/filters/FilterGroup.tsx`:

- Header row: title + chevron; clicking toggles collapse (UDM `^`/`v`).
- Body when expanded:
  - **< 8 options:** a plain checkbox list with `label (count)`.
  - **≥ 8 options:** the large-group treatment, matching the ASCII art /
    `tmp/udm-filter-panel.png`:
    - a **search box** at the top filtering options by label;
    - a **selected-summary** row (`Selected (n)`), collapsible, listing/among
      chosen options;
    - a **nested scroll panel** (`max-height`, `overflow-y: auto`) holding the
      checkbox list — yes, a scrollbar inside the rail's scrollbar;
    - a **Select All** action pinned at the bottom of the panel (selects the
      currently-filtered options).
- Each option: checkbox + label + count.

## Step 4 — Filter state + semantics

New `viewer/src/filters/state.ts` (or fold into the map component). State = a
`Map<groupId, Set<optionValue>>`. Semantics (locked):

- **Within a group: OR.** Empty selection in a group = "no constraint from this
  group" (everything passes), *not* "nothing".
- **Across groups: AND.** A node is visible iff it passes Element-type AND Layer
  AND Producer AND Environment.
- **Relationship type group filters edges, not nodes.** With no relation type
  selected: show **all** relations among visible nodes (this is the
  "two element types, no relations ⇒ all relations between the shown elements"
  behaviour). With relation types selected: show only those types among visible
  nodes.
- **Environment defaults to `{prd}`** selected (plus elements that have no
  `environment` always pass — they're env-agnostic). The user can add dev/tst/uat.
  This is the prd-default until Plan 4's views own it.

Implement the visible-graph computation to replace Plan 1's `useVisibleGraph`:
compute visible node id set from the AND-of-OR node predicates, then edges =
relations among visible nodes filtered by the relation-type set. Re-run ELK on
the visible subgraph (as today).

## Step 5 — Fixed footer: Clear filters

Pinned footer in the aside: **Clear filters** resets every group to empty —
except re-apply the Environment `{prd}` default. (In Plan 4 this instead resets to
the active view's baseline; leave a clear seam for that.)

## Step 6 — Persist collapsed state per manifest URL

- `viewer/src/filters/persistence.ts`: `localStorage` key
  `arch-viewer:collapsed:${hash(srcUrl)}` where `hash` is a small stable string
  hash (djb2/FNV-1a — a few lines, no dependency). Value = JSON map
  `groupId → boolean`.
- Load on mount, persist on toggle. Keying off the `?src` hash means different
  manifests remember their own collapse state. Only collapsed state is persisted
  here — not selections (selections are owned by views in Plan 4).

## Step 7 — Remove the stopgap controls

Delete Plan 1's temporary `.controls-panel` strip and its toggle handlers; the
rail fully replaces it. Keep the search affordance — move a global element search
into the rail or keep a small search at the canvas top; your call, but don't
regress search.

## Acceptance criteria

- Two-panel layout: scrollable rail with the 5 groups + fixed Clear-filters
  footer; canvas fills the rest and resizes.
- A group with ≥ 8 options (Producer or Element type, depending on data) shows
  search + nested scroll + selected-summary + Select All; a small group is a
  plain list.
- Semantics verified: selecting two element types with no relation type shows all
  edges between those nodes; adding a relation type restricts edges; across-group
  AND holds; empty group = no constraint.
- Environment defaults to prd; revealing dev/tst/uat adds those elements.
- Collapse a group, reload → still collapsed; load with a different `?src` →
  independent collapse state.
- `npm run build` passes.

## Suggested commits

1. Two-panel shell + CSS.
2. Filter group derivation + `FilterGroup` component (collapsible, large-group
   treatment).
3. Filter state + semantics + visible-graph rewrite.
4. Collapsed-state persistence keyed by `?src` hash.
5. Remove stopgap controls.
