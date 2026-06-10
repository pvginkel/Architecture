// Derive the ordered list of filter groups from the loaded model + vocab.
//
// Counts cross-narrow (UDM behaviour): an option's count is computed against the
// dataset with all *other* groups' selections (and the global search) applied,
// but NOT this group's own. Selecting in one group therefore narrows the others'
// counts. Option membership and sort order, by contrast, are fixed against the
// full dataset (count desc, then label) so the list doesn't reshuffle or pop
// rows in and out as you select — only the displayed numbers move.
//
// Node groups are membered against the active view's SCOPED model, so each view
// lists only the element attributes it actually contains. The relationship
// group is the deliberate exception: it is membered against the FULL model so
// every relationship type stays present in every view (see relationshipGroup).

import {
  KIND_LABELS,
  LAYER_LABELS,
  RELATIONSHIP_LABELS,
  ENVIRONMENT_LABELS,
  type ElementKind,
  type LayerId,
  type RelationshipType,
  type EnvironmentId,
} from "../generated/vocab";
import type { ArchElement, ArchModel } from "../data/model";
import {
  KIND_GROUP,
  LAYER_GROUP,
  PRODUCER_GROUP,
  RELEASE_GROUP,
  WORKLOAD_GROUP,
  ENVIRONMENT_GROUP,
  RELATIONSHIP_GROUP,
  NODE_GROUP_IDS,
  NO_VALUE,
  computeVisibleElements,
  matchesSearch,
  passesNodeGroup,
  nodeValue,
  type FilterState,
} from "./state";

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export interface FilterGroupModel {
  id: string;
  title: string;
  options: FilterOption[];
}

function tally<T>(items: T[], key: (item: T) => string | undefined): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const value = key(item);
    if (value === undefined) {
      continue;
    }
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

/** Build options for a node group: membership/order from the full dataset,
 *  displayed counts from `base` (other groups + search applied). */
function nodeOptions(
  model: ArchModel,
  base: ArchElement[],
  groupId: string,
  labelOf: (value: string) => string,
): FilterOption[] {
  const fullCounts = tally(model.elements, (el) => nodeValue(el, groupId));
  const liveCounts = tally(base, (el) => nodeValue(el, groupId));
  const options = [...fullCounts.entries()]
    .map(([value, full]) => ({
      value,
      label: labelOf(value),
      count: liveCounts.get(value) ?? 0,
      full,
    }))
    .sort((a, b) => b.full - a.full || a.label.localeCompare(b.label))
    .map(({ value, label, count }) => ({ value, label, count }));

  // Pin a "(none)" row to the bottom for groups whose data carries value-less
  // elements, so selecting concrete values doesn't silently drop them. Skip
  // environment: env-agnostic elements always pass, so the row would be a no-op.
  if (groupId !== ENVIRONMENT_GROUP) {
    const fullNone = model.elements.filter((el) => nodeValue(el, groupId) === undefined).length;
    if (fullNone > 0) {
      const count = base.filter((el) => nodeValue(el, groupId) === undefined).length;
      options.push({ value: NO_VALUE, label: "(none)", count });
    }
  }
  return options;
}

function nodeGroup(
  id: string,
  title: string,
  model: ArchModel,
  filterState: FilterState,
  term: string,
  labelOf: (value: string) => string,
): FilterGroupModel {
  // Count base: every element passing the search and all *other* node groups.
  const base = model.elements.filter(
    (el) =>
      matchesSearch(el, term) &&
      NODE_GROUP_IDS.filter((g) => g !== id).every((g) =>
        passesNodeGroup(el, g, filterState.get(g)),
      ),
  );
  return { id, title, options: nodeOptions(model, base, id, labelOf) };
}

function relationshipGroup(
  scopedModel: ArchModel,
  fullModel: ArchModel,
  filterState: FilterState,
  searchTerm: string,
): FilterGroupModel {
  // Unlike the node groups, the relationship list is NOT pruned to the active
  // view's scope: membership/order come from the FULL model, so every type the
  // data carries stays visible and selectable in every view (the relationship
  // selection also feeds the Isolate/Expand traversal, so a type silently
  // dropping out of the panel would silently gate what Expand can reach). Counts
  // still reflect only the scoped, currently-visible node set, so a type with no
  // edges in this view reads as 0 rather than vanishing.
  const visibleIds = new Set(
    computeVisibleElements(scopedModel, filterState, searchTerm).map((el) => el.id),
  );
  const fullCounts = tally(fullModel.relations, (rel) => rel.type);
  const liveCounts = tally(
    scopedModel.relations.filter(
      (rel) => visibleIds.has(rel.source) && visibleIds.has(rel.target),
    ),
    (rel) => rel.type,
  );
  const options = [...fullCounts.entries()]
    .map(([value, full]) => ({
      value,
      label: RELATIONSHIP_LABELS[value as RelationshipType],
      count: liveCounts.get(value) ?? 0,
      full,
    }))
    .sort((a, b) => b.full - a.full || a.label.localeCompare(b.label))
    .map(({ value, label, count }) => ({ value, label, count }));
  return { id: RELATIONSHIP_GROUP, title: "Relationship type", options };
}

export function buildGroups(
  model: ArchModel,
  fullModel: ArchModel,
  filterState: FilterState,
  searchTerm: string,
): FilterGroupModel[] {
  const term = searchTerm.trim().toLowerCase();
  const groups: FilterGroupModel[] = [
    nodeGroup(KIND_GROUP, "Element type", model, filterState, term, (v) => KIND_LABELS[v as ElementKind]),
    relationshipGroup(model, fullModel, filterState, searchTerm),
    nodeGroup(LAYER_GROUP, "Layer", model, filterState, term, (v) => LAYER_LABELS[v as LayerId]),
    nodeGroup(PRODUCER_GROUP, "Producer", model, filterState, term, (v) => v),
    nodeGroup(RELEASE_GROUP, "Release", model, filterState, term, (v) => v),
    nodeGroup(WORKLOAD_GROUP, "Workload", model, filterState, term, (v) => v),
    nodeGroup(ENVIRONMENT_GROUP, "Environment", model, filterState, term, (v) => ENVIRONMENT_LABELS[v as EnvironmentId]),
  ];
  // Drop groups with nothing present in the data.
  return groups.filter((group) => group.options.length > 0);
}
