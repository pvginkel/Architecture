// View resolution: turn a ViewDefinition into the scoped element set the canvas
// works within, and the baseline filter state the rail seeds to.
//
// Resolution algorithm (mirrors views.schema.yaml / plan-4-views.md):
//
//   base   = elements matching predicate (AND across fields, OR within a field)
//   base   = (base ∪ include) − exclude
//   scoped = base ∪ { elements within neighbourDepth relation-hops of base }
//
// `excludeInstances: true` removes runtime instances (elements carrying an
// `environment` and/or `stats.release`) from the universe first, so they appear
// in neither the base nor the neighbour expansion — a definitions-only view
// that depth can't undo. The Environment filter is a no-op within such a view:
// every surviving element is environment-agnostic, so nothing is left to refine.
//
// Environment is deliberately NOT folded into the scope: it is the one
// dimension the live Environment filter owns, seeded to the view's
// `defaultEnvironment` (default "prd"). That is what lets a view reveal
// dev/tst/uat *within* its scope — a scope that pre-filtered to prd could never
// bring those elements back. So the predicate builds the scope (the universe
// the view contains) and the filter rail refines within it; switching to
// Everything (empty predicate → whole model) is the way to roam wider.

import type { ArchModel } from "../data/model";
import type { Manifest, ViewDefinition, ViewPredicate } from "../data/manifest";
import {
  ENVIRONMENT_GROUP,
  RELATIONSHIP_GROUP,
  defaultRelationshipSelection,
  type FilterState,
} from "../filters/state";

const DEFAULT_ENVIRONMENT = "prd";

/** Element ids each capability covers: the capability node itself plus every
 *  element that realises it. Used to resolve a `capabilities` predicate. */
function capabilityMembers(manifest: Manifest): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const [cap, realisers] of Object.entries(
    manifest.derived.capabilityRealizations,
  )) {
    const members = new Set<string>(realisers);
    members.add(cap);
    map.set(cap, members);
  }
  return map;
}

/** Does `predicate` have no constraining field? Such a predicate matches all. */
function isEmptyPredicate(predicate: ViewPredicate | undefined): boolean {
  if (!predicate) {
    return true;
  }
  return (
    !predicate.layers?.length &&
    !predicate.kinds?.length &&
    !predicate.producers?.length &&
    !predicate.capabilities?.length &&
    !predicate.lifecycle?.length &&
    !predicate.environments?.length &&
    !predicate.releases?.length
  );
}

function matchesPredicate(
  el: ArchModel["elements"][number],
  predicate: ViewPredicate,
  capMembers: Map<string, Set<string>>,
): boolean {
  if (predicate.layers?.length && !predicate.layers.includes(el.layer)) {
    return false;
  }
  if (predicate.kinds?.length && !predicate.kinds.includes(el.kind)) {
    return false;
  }
  if (predicate.producers?.length && !predicate.producers.includes(el.producer)) {
    return false;
  }
  if (predicate.lifecycle?.length && !predicate.lifecycle.includes(el.lifecycle)) {
    return false;
  }
  if (predicate.environments?.length) {
    if (el.environment === undefined || !predicate.environments.includes(el.environment)) {
      return false;
    }
  }
  if (predicate.releases?.length) {
    const release = el.stats?.release;
    if (release === undefined || !predicate.releases.includes(release)) {
      return false;
    }
  }
  if (predicate.capabilities?.length) {
    const inAny = predicate.capabilities.some((cap) =>
      capMembers.get(cap)?.has(el.id),
    );
    if (!inAny) {
      return false;
    }
  }
  return true;
}

/** Undirected adjacency over the model's relations. */
function buildAdjacency(model: ArchModel): Map<string, string[]> {
  const adjacency = new Map<string, string[]>();
  const push = (from: string, to: string) => {
    const list = adjacency.get(from);
    if (list) {
      list.push(to);
    } else {
      adjacency.set(from, [to]);
    }
  };
  for (const rel of model.relations) {
    push(rel.source, rel.target);
    push(rel.target, rel.source);
  }
  return adjacency;
}

/** Grow `seed` by `depth` undirected relation hops, staying within the model.
 *  `admits` gates which elements may be reached — an element it rejects is
 *  neither added nor traversed, so the hop budget is spent only on admitted
 *  nodes (used to keep excluded instances out of the expansion entirely). */
function expandNeighbours(
  seed: Set<string>,
  depth: number,
  model: ArchModel,
  admits: (id: string) => boolean,
): Set<string> {
  if (depth <= 0) {
    return new Set(seed);
  }
  const adjacency = buildAdjacency(model);
  const result = new Set(seed);
  let frontier = [...seed];
  for (let hop = 0; hop < depth; hop++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const neighbour of adjacency.get(id) ?? []) {
        if (!result.has(neighbour) && model.elementById.has(neighbour) && admits(neighbour)) {
          result.add(neighbour);
          next.push(neighbour);
        }
      }
    }
    if (next.length === 0) {
      break;
    }
    frontier = next;
  }
  return result;
}

/** The set of element ids a view scopes (predicate ∪ include − exclude, then
 *  neighbour-expanded). Environment is applied later by the filter layer. */
export function resolveViewScope(
  view: ViewDefinition,
  model: ArchModel,
  manifest: Manifest,
): Set<string> {
  const capMembers = capabilityMembers(manifest);
  // Universe gates: excludeInstances (env-/release-tagged runtime instances, see
  // model.ts) and excludeKinds (whole kinds, e.g. the physical Device fleet) drop
  // matching elements from the entire resolution — not the base, not as expansion
  // neighbours, not via explicit include — and they aren't traversed, so
  // neighbourDepth can't pull them back. With neither gate set, admits is a
  // cheap pass-through.
  const excludedKinds = new Set(view.excludeKinds ?? []);
  const admits =
    view.excludeInstances || excludedKinds.size > 0
      ? (id: string) => {
          const el = model.elementById.get(id);
          if (!el) {
            return true;
          }
          if (view.excludeInstances && el.isInstance) {
            return false;
          }
          return !excludedKinds.has(el.kind);
        }
      : () => true;
  const base = new Set<string>();
  if (isEmptyPredicate(view.predicate)) {
    for (const el of model.elements) {
      if (admits(el.id)) {
        base.add(el.id);
      }
    }
  } else {
    for (const el of model.elements) {
      if (admits(el.id) && matchesPredicate(el, view.predicate!, capMembers)) {
        base.add(el.id);
      }
    }
  }
  for (const id of view.include ?? []) {
    if (model.elementById.has(id) && admits(id)) {
      base.add(id);
    }
  }
  for (const id of view.exclude ?? []) {
    base.delete(id);
  }
  return expandNeighbours(base, view.neighbourDepth ?? 0, model, admits);
}

/** The filter state a view seeds on open: the Environment group set to the
 *  view's `defaultEnvironment` (default "prd"), and the Relationship group set
 *  to every type except the noisy ones (see defaultRelationshipSelection), so
 *  the canvas opens decluttered. All node groups start empty so the whole scope
 *  shows; the user narrows from there. Clearing filters and switching views both
 *  return to this. */
export function viewBaselineFilterState(view: ViewDefinition): FilterState {
  return new Map<string, Set<string>>([
    [ENVIRONMENT_GROUP, new Set([view.defaultEnvironment ?? DEFAULT_ENVIRONMENT])],
    [RELATIONSHIP_GROUP, defaultRelationshipSelection()],
  ]);
}

/** Choose the view to open: `?view=<id>` when it names a real view, else the
 *  first view (Landscape). A malformed/unknown id is a loud, non-fatal boundary
 *  (user-supplied URL) — warn and fall back. Returns null only for an empty
 *  view list, which the collector never emits (Everything is always present). */
export function pickInitialView(views: ViewDefinition[]): ViewDefinition | null {
  if (views.length === 0) {
    return null;
  }
  const requested = new URLSearchParams(window.location.search).get("view");
  if (requested) {
    const match = views.find((v) => v.id === requested);
    if (match) {
      return match;
    }
    console.warn(
      `[viewer] unknown ?view=${requested} — falling back to ${views[0].id}`,
    );
  }
  return views[0];
}
