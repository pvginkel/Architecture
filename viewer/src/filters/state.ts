// Filter state model + visible-graph computation. Replaces Plan 1's per-set
// filter state and inline useVisibleGraph.
//
// Semantics (locked, see plan-3-filter-rail.md Step 4):
//   - Within a group: OR. Empty selection in a group = no constraint.
//   - Across groups: AND.
//   - Relationship type filters EDGES, not nodes. No relation type selected =>
//     all relations among visible nodes; some selected => only those types.
//   - Environment defaults to {prd}; elements with no environment are
//     env-agnostic and always pass.

import { KIND_LABELS, RELATIONSHIP_TYPES } from "../generated/vocab";
import type { ArchElement, ArchModel } from "../data/model";
import type { ManifestRelation } from "../data/manifest";

export const KIND_GROUP = "kind";
export const RELATIONSHIP_GROUP = "relationship";
export const LAYER_GROUP = "layer";
export const PRODUCER_GROUP = "producer";
export const RELEASE_GROUP = "release";
export const WORKLOAD_GROUP = "workload";
export const ENVIRONMENT_GROUP = "environment";

// The node-filtering groups, in no particular order (group display order lives
// in groups.ts). The relationship group is deliberately excluded — it filters
// edges, not nodes.
export const NODE_GROUP_IDS = [
  KIND_GROUP,
  LAYER_GROUP,
  PRODUCER_GROUP,
  RELEASE_GROUP,
  WORKLOAD_GROUP,
  ENVIRONMENT_GROUP,
] as const;

export type FilterState = Map<string, Set<string>>;

/** Relationship types kept off the canvas by default — loose Association edges,
 *  which carry little structural signal and clutter the view. The view baseline
 *  pre-selects every *other* type so these stay hidden until the user opts in;
 *  switching views or clearing filters restores this. */
export const HIDDEN_RELATIONSHIP_TYPES: ReadonlySet<string> = new Set([
  "Association",
]);

/** The relationship-group selection a fresh view seeds to: every type except the
 *  hidden ones. Deliberately the complement, not an empty set — an empty
 *  selection means "show all relations" (see computeExpandedVisibleGraph), which would
 *  reveal exactly the edges we mean to hide. A non-empty complement keeps the
 *  edge filter always active. */
export function defaultRelationshipSelection(): Set<string> {
  return new Set(RELATIONSHIP_TYPES.filter((type) => !HIDDEN_RELATIONSHIP_TYPES.has(type)));
}

/** The attribute a node group tests on an element. `undefined` = the element
 *  doesn't carry that attribute (only meaningful for environment). */
export function nodeValue(el: ArchElement, groupId: string): string | undefined {
  switch (groupId) {
    case KIND_GROUP:
      return el.kind;
    case LAYER_GROUP:
      return el.layer;
    case PRODUCER_GROUP:
      return el.producer;
    case RELEASE_GROUP:
      return el.stats?.release;
    case WORKLOAD_GROUP:
      return el.stats?.workload;
    case ENVIRONMENT_GROUP:
      return el.environment;
    default:
      throw new Error(`nodeValue: '${groupId}' is not a node group`);
  }
}

/** Does an element satisfy one node group's selection? Empty/absent selection =
 *  no constraint.
 *
 *  Environment is special: an element with no environment is env-agnostic and
 *  always passes (a capability survives the prd default). Release and workload
 *  are strict, by contrast — selecting a release means "show that release", so
 *  an element that carries no release/workload (a product, a capability) is
 *  *excluded*, not waved through. */
export function passesNodeGroup(
  el: ArchElement,
  groupId: string,
  selection: Set<string> | undefined,
): boolean {
  if (!selection || selection.size === 0) {
    return true;
  }
  const value = nodeValue(el, groupId);
  if (groupId === ENVIRONMENT_GROUP && value === undefined) {
    return true;
  }
  return value !== undefined && selection.has(value);
}

export function matchesSearch(el: ArchElement, term: string): boolean {
  if (!term) {
    return true;
  }
  const haystack = [el.label, KIND_LABELS[el.kind], el.producer]
    .join(" ")
    .toLowerCase();
  return haystack.includes(term);
}

/** True when an element passes every node group's selection (AND across groups)
 *  and the global search term. */
export function passesNodeFilters(
  el: ArchElement,
  filterState: FilterState,
  term: string,
): boolean {
  return (
    matchesSearch(el, term) &&
    NODE_GROUP_IDS.every((g) => passesNodeGroup(el, g, filterState.get(g)))
  );
}

/** Elements passing every node group's selection (AND across groups) and the
 *  global search term. */
export function computeVisibleElements(
  model: ArchModel,
  filterState: FilterState,
  searchTerm: string,
): ArchElement[] {
  const term = searchTerm.trim().toLowerCase();
  return model.elements.filter((el) => passesNodeFilters(el, filterState, term));
}

/** Does the relation-type selection permit this type? Empty/absent selection =
 *  no constraint (every type passes). Shared by edge rendering and by the
 *  expansion traversal, which follows only currently-selected relationship
 *  types. */
export function relationSelected(
  relSelection: Set<string> | undefined,
  type: string,
): boolean {
  return !relSelection || relSelection.size === 0 || relSelection.has(type);
}

export interface VisibleGraph {
  visibleElements: ArchElement[];
  visibleRelations: ManifestRelation[];
}

/** The node ids reachable from each expansion anchor within its hop radius.
 *
 *  Walked over the FULL federated model (not the active view's scope) and
 *  following only currently-selected relationship types — that traversal gate
 *  is the only filter honoured here. Node filters are deliberately ignored: the
 *  walk must reach past a filtered-out node to stay connected, and the caller
 *  re-applies node filters when rendering. Each anchor runs its own BFS (a
 *  shared visited set would let one anchor's reach truncate another's), and the
 *  per-anchor reachable sets are unioned. */
export function computeExpansionUniverse(
  model: ArchModel,
  anchors: Map<string, number>,
  relSelection: Set<string> | undefined,
): Set<string> {
  const universe = new Set<string>();
  if (anchors.size === 0) {
    return universe;
  }
  const adjacency = new Map<string, string[]>();
  const link = (from: string, to: string) => {
    const list = adjacency.get(from);
    if (list) {
      list.push(to);
    } else {
      adjacency.set(from, [to]);
    }
  };
  for (const rel of model.relations) {
    if (!relationSelected(relSelection, rel.type)) {
      continue;
    }
    link(rel.source, rel.target);
    link(rel.target, rel.source);
  }
  for (const [anchorId, radius] of anchors) {
    const visited = new Set<string>([anchorId]);
    let frontier = [anchorId];
    for (let hop = 0; hop < radius; hop++) {
      const next: string[] = [];
      for (const id of frontier) {
        for (const neighbour of adjacency.get(id) ?? []) {
          if (!visited.has(neighbour)) {
            visited.add(neighbour);
            next.push(neighbour);
          }
        }
      }
      frontier = next;
    }
    for (const id of visited) {
      universe.add(id);
    }
  }
  return universe;
}

/** The visible graph: the view-scoped elements (or, when a node is isolated,
 *  only that node) plus the expansion universe, narrowed by the node filters +
 *  search, then the edges among the survivors filtered by relationship type.
 *
 *  Expansion draws from the full `model`, so the universe can reach elements
 *  outside `scopedModel`; node filters still apply to everything (an expanded
 *  node that fails a filter is added-but-hidden), which is what lets a filter
 *  narrow an expanded scope. With no anchors and no isolation this is exactly
 *  the plain filtered view of `scopedModel`. */
export function computeExpandedVisibleGraph(
  model: ArchModel,
  scopedModel: ArchModel,
  filterState: FilterState,
  searchTerm: string,
  anchors: Map<string, number>,
  isolatedId: string | null,
  revealedIds: ReadonlySet<string> = new Set(),
): VisibleGraph {
  const relSelection = filterState.get(RELATIONSHIP_GROUP);
  const universe = computeExpansionUniverse(model, anchors, relSelection);

  const candidateIds = isolatedId
    ? new Set<string>([isolatedId])
    : new Set(scopedModel.elements.map((el) => el.id));
  for (const id of universe) {
    candidateIds.add(id);
  }
  // Nodes the user revealed by expanding a derived path: shown unconditionally,
  // bypassing scope and node filters (they are hidden precisely because some
  // filter/scope excludes them — that is what made the path derived). See
  // "Expand derived path" in ArchitectureMap.
  for (const id of revealedIds) {
    candidateIds.add(id);
  }

  const term = searchTerm.trim().toLowerCase();
  const visibleElements: ArchElement[] = [];
  for (const id of candidateIds) {
    // Every candidate id is a scoped element, a relation endpoint, or a revealed
    // node, so it resolves in the model (buildModel drops dangling relations).
    const el = model.elementById.get(id)!;
    if (revealedIds.has(id) || passesNodeFilters(el, filterState, term)) {
      visibleElements.push(el);
    }
  }
  const visibleIds = new Set(visibleElements.map((el) => el.id));
  const visibleRelations = model.relations.filter(
    (rel) =>
      relationSelected(relSelection, rel.type) &&
      visibleIds.has(rel.source) &&
      visibleIds.has(rel.target),
  );
  return { visibleElements, visibleRelations };
}

export function initialFilterState(): FilterState {
  // Transient pre-load state, replaced by the view baseline once the manifest's
  // first view resolves. Mirrors the baseline: prd environment + hidden
  // relations off.
  return new Map<string, Set<string>>([
    [ENVIRONMENT_GROUP, new Set(["prd"])],
    [RELATIONSHIP_GROUP, defaultRelationshipSelection()],
  ]);
}

export function toggleFilterOption(
  state: FilterState,
  groupId: string,
  value: string,
): FilterState {
  const next = new Map(state);
  const current = new Set(next.get(groupId) ?? []);
  if (current.has(value)) {
    current.delete(value);
  } else {
    current.add(value);
  }
  if (current.size === 0) {
    next.delete(groupId);
  } else {
    next.set(groupId, current);
  }
  return next;
}

export function addFilterOptions(
  state: FilterState,
  groupId: string,
  values: string[],
): FilterState {
  const next = new Map(state);
  const current = new Set(next.get(groupId) ?? []);
  for (const value of values) {
    current.add(value);
  }
  if (current.size === 0) {
    next.delete(groupId);
  } else {
    next.set(groupId, current);
  }
  return next;
}

export function removeFilterOptions(
  state: FilterState,
  groupId: string,
  values: string[],
): FilterState {
  const next = new Map(state);
  const current = new Set(next.get(groupId) ?? []);
  for (const value of values) {
    current.delete(value);
  }
  if (current.size === 0) {
    next.delete(groupId);
  } else {
    next.set(groupId, current);
  }
  return next;
}

export function serializeFilters(state: FilterState): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [groupId, values] of state) {
    out[groupId] = [...values];
  }
  return out;
}

export function deserializeFilters(obj: Record<string, string[]>): FilterState {
  const state: FilterState = new Map();
  for (const [groupId, values] of Object.entries(obj)) {
    if (Array.isArray(values) && values.length > 0) {
      state.set(groupId, new Set(values));
    }
  }
  return state;
}
