// Render-time relationship derivation.
//
// Two visible nodes are often connected only *through* nodes that the current
// view/filters hide (a definitions-only view hides the runtime instances that
// carry the real edges; isolate/expand hides filtered-out neighbours). Without
// derivation such a view is a field of disconnected boxes. This engine bridges
// the gap: for every pair of visible nodes joined by a run of consecutive hidden
// nodes, it composes the chain of relationships into a single derived edge,
// following the ArchiMate 3.2 relationship-derivation rules (Appendix B,
// transcribed below from tmp/derived-relationships-roles.json).
//
// It replaces the collector's old instance→definition projection (a single
// hard-coded slice of these rules, baked unconditionally into the manifest).
// Here it runs over the *visible* set, so a bridge only appears when the path
// it stands for is actually hidden.
//
// Confidence: stock ArchiMate marks the inheritance rules (PDR1–PDR4) as
// "potential" (modeller judgement). We promote them to "valid" for our alias
// semantics — an instance→definition Specialization — and drop everything else
// that stays "potential". The engine still *computes* potential derivations so
// surfacing them later (an even-lighter "suggestion" style) is a one-line change
// (see deriveBridges' confidenceFloor).

import { ALLOWED_TRIPLES, RELATIONSHIP_TYPES, type RelationshipType } from "../generated/vocab";
import type { ArchModel } from "../data/model";
import type { ManifestRelation } from "../data/manifest";
import { relationSelected } from "../filters/state";

// Largest run of consecutive hidden nodes the engine will bridge across. A path
// with more hidden interior nodes than this is dropped (and counted — see the
// console.warn in deriveBridges), never silently truncated. Tunable: raising it
// finds longer bridges at more pathfinding cost; lowering it is stricter.
export const MAX_HIDDEN_HOPS = 5;

type Confidence = "valid" | "potential";
type Category = "structural" | "dependency" | "dynamic" | "other";
type RuleVar = "a" | "b" | "c";

// Category membership and strength orderings, from the rule file. Type names are
// lowercase here (the rule file's vocabulary); our RelationshipType is
// PascalCase, bridged by lowering on the way in and TYPE_BY_LOWER on the way out.
const CATEGORY_MEMBERS: Record<Category, string[]> = {
  structural: ["composition", "aggregation", "assignment", "realization"],
  dependency: ["serving", "access", "influence", "association"],
  dynamic: ["triggering", "flow"],
  other: ["specialization"],
};

// weakestTypeOf: lower index = weaker = wins. Only ever compares within one
// category, given how the rules are written.
const STRENGTH: Record<"structural" | "dependency", string[]> = {
  structural: ["realization", "assignment", "aggregation", "composition"],
  dependency: ["association", "influence", "access", "serving"],
};

interface Pattern {
  source: RuleVar;
  target: RuleVar;
  types?: string[]; // explicit lowercase type names
  category?: Category | "any"; // or a category (any = every type)
}

type DeriveType =
  | { kind: "fixedType"; type: string }
  | { kind: "copyTypeOf"; rel: "P" | "Q" }
  | { kind: "weakestTypeOf"; rels: ("P" | "Q")[] };

interface DerivationRule {
  id: string;
  confidence: Confidence;
  p: Pattern;
  q: Pattern;
  derive: { source: RuleVar; target: RuleVar; type: DeriveType };
  // PDR12 only: the shared element must be a Grouping. Groupings are pruned from
  // the viewer model, so a rule carrying this never fires — kept for fidelity.
  groupingVar?: RuleVar;
}

// The full rule set. DR1–DR8 are "valid"; PDR1–PDR12 are "potential" (PDR1–PDR4
// promote — see promote()). Transcribed verbatim from the rule file.
const RULES: DerivationRule[] = [
  { id: "DR1", confidence: "valid", p: { source: "a", target: "b", types: ["specialization"] }, q: { source: "b", target: "c", types: ["specialization"] }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "specialization" } } },
  { id: "DR2", confidence: "valid", p: { source: "a", target: "b", category: "structural" }, q: { source: "b", target: "c", category: "structural" }, derive: { source: "a", target: "c", type: { kind: "weakestTypeOf", rels: ["P", "Q"] } } },
  { id: "DR3", confidence: "valid", p: { source: "a", target: "b", category: "structural" }, q: { source: "b", target: "c", category: "dependency" }, derive: { source: "a", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "DR4", confidence: "valid", p: { source: "a", target: "b", category: "structural" }, q: { source: "c", target: "b", category: "dependency" }, derive: { source: "c", target: "a", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "DR5", confidence: "valid", p: { source: "a", target: "b", category: "structural" }, q: { source: "b", target: "c", category: "dynamic" }, derive: { source: "a", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "DR6", confidence: "valid", p: { source: "a", target: "b", category: "structural" }, q: { source: "c", target: "b", types: ["flow"] }, derive: { source: "c", target: "a", type: { kind: "fixedType", type: "flow" } } },
  { id: "DR7", confidence: "valid", p: { source: "a", target: "b", types: ["triggering"] }, q: { source: "b", target: "c", category: "structural" }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "triggering" } } },
  { id: "DR8", confidence: "valid", p: { source: "a", target: "b", types: ["triggering"] }, q: { source: "b", target: "c", types: ["triggering"] }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "triggering" } } },
  { id: "PDR1", confidence: "potential", p: { source: "a", target: "b", types: ["specialization"] }, q: { source: "b", target: "c", category: "any" }, derive: { source: "a", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR2", confidence: "potential", p: { source: "a", target: "b", types: ["specialization"] }, q: { source: "c", target: "b", category: "any" }, derive: { source: "c", target: "a", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR3", confidence: "potential", p: { source: "a", target: "b", types: ["specialization"] }, q: { source: "a", target: "c", category: "any" }, derive: { source: "b", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR4", confidence: "potential", p: { source: "a", target: "b", types: ["specialization"] }, q: { source: "c", target: "a", category: "any" }, derive: { source: "c", target: "b", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR5", confidence: "potential", p: { source: "a", target: "b", category: "structural" }, q: { source: "c", target: "a", category: "dependency" }, derive: { source: "c", target: "b", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR6", confidence: "potential", p: { source: "a", target: "b", category: "structural" }, q: { source: "a", target: "c", category: "dependency" }, derive: { source: "b", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR7", confidence: "potential", p: { source: "a", target: "b", category: "dependency" }, q: { source: "b", target: "c", category: "dependency" }, derive: { source: "a", target: "c", type: { kind: "weakestTypeOf", rels: ["P", "Q"] } } },
  { id: "PDR8", confidence: "potential", p: { source: "a", target: "b", types: ["flow"] }, q: { source: "b", target: "c", category: "structural" }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "flow" } } },
  { id: "PDR9", confidence: "potential", p: { source: "a", target: "b", category: "structural" }, q: { source: "a", target: "c", category: "dynamic" }, derive: { source: "b", target: "c", type: { kind: "copyTypeOf", rel: "Q" } } },
  { id: "PDR10", confidence: "potential", p: { source: "a", target: "b", types: ["flow"] }, q: { source: "b", target: "c", types: ["flow"] }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "flow" } } },
  { id: "PDR11", confidence: "potential", p: { source: "a", target: "b", types: ["triggering"] }, q: { source: "c", target: "b", category: "structural" }, derive: { source: "a", target: "c", type: { kind: "fixedType", type: "triggering" } } },
  { id: "PDR12", confidence: "potential", p: { source: "b", target: "a", types: ["aggregation", "composition"] }, q: { source: "b", target: "c", types: ["realization", "assignment"] }, derive: { source: "a", target: "c", type: { kind: "copyTypeOf", rel: "Q" } }, groupingVar: "b" },
];

// PDR1–PDR4: specialization inheritance. Promotes to "valid" when the
// Specialization edge is instance→definition (our alias semantics).
const PROMOTABLE = new Set(["PDR1", "PDR2", "PDR3", "PDR4"]);

// Lowercase rule-vocabulary name → our PascalCase RelationshipType.
const TYPE_BY_LOWER = new Map<string, RelationshipType>(
  RELATIONSHIP_TYPES.map((t) => [t.toLowerCase(), t]),
);

/** A relationship reduced to what derivation cares about: endpoints + a
 *  lowercase type, the accumulated confidence of the chain that produced it (an
 *  asserted edge starts "valid"), and the path it bridges:
 *   - `via`      — the hidden interior nodes consumed so far (incl. the partial's
 *                  current hidden endpoint); on a closed chain, exactly the nodes
 *                  the derived edge spans, which "Expand derived path" reveals.
 *   - `viaEdges` — the asserted edge ids consumed along that chain, so the viewer
 *                  can highlight the precise path (one more than `via`: a chain
 *                  of n interior nodes has n+1 edges).
 *   - `id`       — set only on the asserted-edge entries in `byPair`; the source
 *                  edge id a seed/step contributes to `viaEdges`. */
interface Rel {
  id?: string;
  source: string;
  target: string;
  type: string; // lowercase
  confidence: Confidence;
  via?: string[];
  viaEdges?: string[];
}

function typeMatches(typeLower: string, pat: Pattern): boolean {
  if (pat.types) {
    return pat.types.includes(typeLower);
  }
  if (pat.category === "any") {
    return true;
  }
  if (pat.category) {
    return CATEGORY_MEMBERS[pat.category].includes(typeLower);
  }
  return false;
}

// Rules indexed by the concrete (P-type, Q-type) lowercase pair, so compose
// tries only the handful of rules whose patterns can match a given pair of
// relationship types — not all 20 in both orderings. Built once at load; a pair
// with no matching rule is simply absent.
const RULES_BY_TYPE_PAIR = new Map<string, DerivationRule[]>();
for (const tp of RELATIONSHIP_TYPES) {
  for (const tq of RELATIONSHIP_TYPES) {
    const lp = tp.toLowerCase();
    const lq = tq.toLowerCase();
    const matched = RULES.filter((rule) => typeMatches(lp, rule.p) && typeMatches(lq, rule.q));
    if (matched.length > 0) {
      RULES_BY_TYPE_PAIR.set(`${lp}|${lq}`, matched);
    }
  }
}

/** The weaker of two types per the strength ordering (both share a category, by
 *  construction of the rules that use weakestTypeOf). */
function weakestType(types: string[]): string | null {
  for (const cat of ["structural", "dependency"] as const) {
    const order = STRENGTH[cat];
    if (types.every((t) => order.includes(t))) {
      return types.reduce((best, t) =>
        order.indexOf(t) < order.indexOf(best) ? t : best,
      );
    }
  }
  return null;
}

function deriveTypeOf(spec: DeriveType, p: Rel, q: Rel): string | null {
  switch (spec.kind) {
    case "fixedType":
      return spec.type;
    case "copyTypeOf":
      return (spec.rel === "P" ? p : q).type;
    case "weakestTypeOf":
      return weakestType(spec.rels.map((r) => (r === "P" ? p : q).type));
  }
}

/** Apply one rule to an ordered pair (p plays P, q plays Q) whose shared element
 *  is `mid`. Returns the single derived relationship, or null if the rule
 *  doesn't match. `mid` is the node being eliminated — it must be the element
 *  the rule's shared variable binds to, and must not survive as an endpoint. */
function applyRule(
  rule: DerivationRule,
  p: Rel,
  q: Rel,
  mid: string,
  isInstance: (id: string) => boolean,
): Rel | null {
  // Type compatibility is already established by RULES_BY_TYPE_PAIR (compose's
  // lookup key), so applyRule starts straight at variable binding.
  if (rule.groupingVar) {
    // The shared element would have to be a Grouping; groupings are pruned, so
    // this rule can never apply in our model.
    return null;
  }
  // Bind each variable to a concrete element; reject on conflict.
  const bind = new Map<RuleVar, string>();
  const set = (v: RuleVar, el: string): boolean => {
    const prev = bind.get(v);
    if (prev !== undefined && prev !== el) {
      return false;
    }
    bind.set(v, el);
    return true;
  };
  if (!set(rule.p.source, p.source) || !set(rule.p.target, p.target)) {
    return null;
  }
  if (!set(rule.q.source, q.source) || !set(rule.q.target, q.target)) {
    return null;
  }
  // The variable shared between P and Q must bind to the eliminated node.
  const pVars = new Set<RuleVar>([rule.p.source, rule.p.target]);
  const shared = [rule.q.source, rule.q.target].filter((v) => pVars.has(v));
  if (shared.length === 0 || shared.some((v) => bind.get(v) !== mid)) {
    return null;
  }
  const source = bind.get(rule.derive.source);
  const target = bind.get(rule.derive.target);
  if (source === undefined || target === undefined) {
    return null;
  }
  if (source === target || source === mid || target === mid) {
    return null;
  }
  const type = deriveTypeOf(rule.derive.type, p, q);
  if (type === null) {
    return null;
  }
  let confidence = rule.confidence;
  if (confidence === "potential" && PROMOTABLE.has(rule.id)) {
    // P is the Specialization edge (a→b). Promote for instance→definition.
    if (isInstance(p.source) && !isInstance(p.target)) {
      confidence = "valid";
    }
  }
  return { source, target, type, confidence };
}

/** Compose two relationships sharing element `mid` into every derived
 *  relationship the rule set yields (trying each rule in both P/Q orderings).
 *  The step's confidence is combined with the two inputs' accumulated
 *  confidence (any "potential" link makes the whole chain potential). */
function compose(r1: Rel, r2: Rel, mid: string, isInstance: (id: string) => boolean): Rel[] {
  const out: Rel[] = [];
  for (const [p, q] of [
    [r1, r2],
    [r2, r1],
  ] as const) {
    const rules = RULES_BY_TYPE_PAIR.get(`${p.type}|${q.type}`);
    if (!rules) {
      continue;
    }
    for (const rule of rules) {
      const derived = applyRule(rule, p, q, mid, isInstance);
      if (derived) {
        const chained: Confidence =
          r1.confidence === "valid" && r2.confidence === "valid" && derived.confidence === "valid"
            ? "valid"
            : "potential";
        out.push({ ...derived, confidence: chained });
      }
    }
  }
  return out;
}

/** Keep the strongest confidence per distinct (source, type, target). */
function dedupeStrongest(rels: Rel[]): Rel[] {
  const best = new Map<string, Rel>();
  for (const r of rels) {
    const key = `${r.source}|${r.type}|${r.target}`;
    const prev = best.get(key);
    if (!prev || (prev.confidence === "potential" && r.confidence === "valid")) {
      best.set(key, r);
    }
  }
  return [...best.values()];
}

/** Synthetic, viewer-only relationships bridging visible nodes across hidden
 *  runs. Returns one ManifestRelation per surviving derived triple, tagged
 *  `derived: true` with a `confidence`, deterministic id, sorted.
 *
 *  `confidenceFloor` is the weakest confidence kept — "valid" (default) drops
 *  the unpromoted potential derivations; "potential" surfaces everything, the
 *  hook for a future suggestion style. */
export function deriveBridges(
  model: ArchModel,
  visibleIds: ReadonlySet<string>,
  confidenceFloor: Confidence = "valid",
): DerivedRelation[] {
  // Relations among the FULL graph, indexed by unordered endpoint pair, and the
  // undirected adjacency the path search walks.
  const byPair = new Map<string, Rel[]>();
  const adjacency = new Map<string, Set<string>>();
  let hasHidden = false;
  const pairKey = (u: string, v: string) => (u < v ? `${u} ${v}` : `${v} ${u}`);
  for (const rel of model.relations) {
    const key = pairKey(rel.source, rel.target);
    const list = byPair.get(key);
    const entry: Rel = {
      id: rel.id,
      source: rel.source,
      target: rel.target,
      type: rel.type.toLowerCase(),
      confidence: "valid",
    };
    if (list) {
      list.push(entry);
    } else {
      byPair.set(key, [entry]);
    }
    (adjacency.get(rel.source) ?? adjacency.set(rel.source, new Set()).get(rel.source)!).add(rel.target);
    (adjacency.get(rel.target) ?? adjacency.set(rel.target, new Set()).get(rel.target)!).add(rel.source);
    if (!visibleIds.has(rel.source) || !visibleIds.has(rel.target)) {
      hasHidden = true;
    }
  }
  // Nothing hidden (e.g. the Everything view) → no bridges, no work.
  if (!hasHidden) {
    return [];
  }
  const relationsBetween = (u: string, v: string): Rel[] => byPair.get(pairKey(u, v)) ?? [];
  const isInstance = (id: string): boolean => model.elementById.get(id)?.isInstance ?? false;

  // Asserted relations already visible — a derived edge that duplicates one is
  // suppressed (global constraint: don't re-derive an asserted relationship).
  const assertedVisible = new Set<string>();
  for (const rel of model.relations) {
    if (visibleIds.has(rel.source) && visibleIds.has(rel.target)) {
      assertedVisible.add(`${rel.source}|${rel.type}|${rel.target}`);
    }
  }

  // Bridge by BFS relaxation, not path enumeration. Enumerating every simple
  // visible→hidden…→visible path is exponential — a dense hidden subgraph (the
  // instances behind a definitions-only view) explodes into millions of paths.
  // Instead, from each visible source we propagate *partial* derivations across
  // the hidden subgraph, keeping at each hidden node only the deduplicated set of
  // relationships reachable from the source (bounded by type × direction, a
  // small constant). That collapses the path blow-up to roughly
  // (hidden nodes × that constant) work per source, and the result is identical
  // for the chains we care about (the rules only ever compose pairwise anyway).
  //
  // A partial at hidden node h is a relationship connecting the source to h. We
  // seed with the source's asserted edges to its hidden neighbours, relax inward
  // up to MAX_HIDDEN_HOPS hidden nodes, then close every partial against the
  // visible neighbours of its node to emit a source→visible bridge.
  // Confidence is monotonic along a chain: combine() only ever downgrades
  // valid→potential, never the reverse, and promotion happens at the composing
  // step. So a potential partial can only ever yield potential bridges. When the
  // floor is "valid" we therefore never propagate (or emit) potential partials —
  // that prunes whole swaths of the hidden subgraph the moment a chain goes
  // potential (e.g. a dependency∘dependency step), which is what kept the dense
  // instance subgraph cheap.
  const keepPotential = confidenceFloor === "potential";
  const derived: Rel[] = [];
  let overflow = 0; // partial chains still open at the hop cap (longer, not derived)
  for (const start of visibleIds) {
    const seeds = adjacency.get(start);
    if (!seeds) {
      continue;
    }
    // reach: hidden id → (triple key → strongest partial reaching it).
    const reach = new Map<string, Map<string, Rel>>();
    const addPartial = (h: string, r: Rel): boolean => {
      if (!keepPotential && r.confidence === "potential") {
        return false;
      }
      let bucket = reach.get(h);
      if (!bucket) {
        bucket = new Map();
        reach.set(h, bucket);
      }
      const key = `${r.source}|${r.type}|${r.target}`;
      const prev = bucket.get(key);
      // New, or an upgrade of a previously-potential partial to valid.
      if (prev && !(prev.confidence === "potential" && r.confidence === "valid")) {
        return false;
      }
      bucket.set(key, r);
      return true;
    };
    // Seed: asserted edges from the source to each hidden neighbour (1 hop).
    let frontier: { node: string; rel: Rel }[] = [];
    for (const h of seeds) {
      if (visibleIds.has(h)) {
        continue; // direct visible→visible edges are asserted, not bridged
      }
      for (const r of relationsBetween(start, h)) {
        const seed: Rel = { ...r, via: [h], viaEdges: r.id ? [r.id] : [] };
        if (addPartial(h, seed)) {
          frontier.push({ node: h, rel: seed });
        }
      }
    }
    // Relax inward. Seeds are 1 hidden node deep; MAX_HIDDEN_HOPS − 1 further
    // rounds reach chains of up to MAX_HIDDEN_HOPS hidden nodes. Only freshly
    // added partials are propagated (a standard BFS frontier), so each partial
    // is expanded once.
    for (let hop = 1; hop < MAX_HIDDEN_HOPS && frontier.length > 0; hop++) {
      const next: { node: string; rel: Rel }[] = [];
      for (const { node: h, rel: p } of frontier) {
        for (const h2 of adjacency.get(h) ?? []) {
          if (h2 === start || visibleIds.has(h2)) {
            continue; // visible nodes are closed at emit, not traversed through
          }
          for (const edge of relationsBetween(h, h2)) {
            for (const c of compose(p, edge, h, isInstance)) {
              // h was just eliminated; h2 is the new (hidden) endpoint — both
              // belong to the bridged run, and `edge` is the link between them.
              const ext: Rel = {
                ...c,
                via: [...(p.via ?? []), h2],
                viaEdges: edge.id ? [...(p.viaEdges ?? []), edge.id] : p.viaEdges,
              };
              if (addPartial(h2, ext)) {
                next.push({ node: h2, rel: ext });
              }
            }
          }
        }
      }
      frontier = next;
    }
    overflow += frontier.length; // chains still open past the cap
    // Close: compose each partial against edges from its node to visible nodes.
    for (const [h, partials] of reach) {
      for (const b of adjacency.get(h) ?? []) {
        if (!visibleIds.has(b) || b === start) {
          continue;
        }
        const edges = relationsBetween(h, b);
        if (edges.length === 0) {
          continue;
        }
        for (const p of partials.values()) {
          for (const edge of edges) {
            // b is visible (not interior); the bridged run is p.via, which
            // already includes h, the node being closed here. `edge` is the
            // final link, from h onto the visible endpoint b.
            for (const c of compose(p, edge, h, isInstance)) {
              derived.push({
                ...c,
                via: p.via ?? [],
                viaEdges: edge.id ? [...(p.viaEdges ?? []), edge.id] : p.viaEdges,
              });
            }
          }
        }
      }
    }
  }
  if (overflow > 0) {
    console.warn(
      `[derive] ${overflow} partial chain(s) still open at MAX_HIDDEN_HOPS=${MAX_HIDDEN_HOPS}; longer bridges not derived`,
    );
  }

  // Global constraints + confidence floor, then emit.
  const keep = confidenceFloor === "valid";
  const out: DerivedRelation[] = [];
  const emitted = new Set<string>();
  for (const r of dedupeStrongest(derived)) {
    if (keep && r.confidence !== "valid") {
      continue;
    }
    const type = TYPE_BY_LOWER.get(r.type);
    if (!type) {
      continue;
    }
    const key = `${r.source}|${type}|${r.target}`;
    if (emitted.has(key) || assertedVisible.has(key)) {
      continue;
    }
    const sourceKind = model.elementById.get(r.source)?.kind;
    const targetKind = model.elementById.get(r.target)?.kind;
    if (!sourceKind || !targetKind) {
      continue;
    }
    // The metamodel must permit this triple (Appendix B.5). Cross-domain
    // motivation restrictions (B.4) are vacuous here — our subset has no
    // motivation-layer kinds — so the triple matrix is the whole gate.
    if (!ALLOWED_TRIPLES.has(`${sourceKind}|${type}|${targetKind}`)) {
      continue;
    }
    emitted.add(key);
    out.push({
      id: `rel:derived:${r.source}|${type}|${r.target}`,
      source: r.source,
      target: r.target,
      type,
      derived: true,
      confidence: r.confidence,
      via: r.via ?? [],
      viaEdges: r.viaEdges ?? [],
    });
  }
  out.sort((a, b) => a.id.localeCompare(b.id));
  return out;
}

/** A bridged relationship: a ManifestRelation always tagged derived, carrying
 *  the confidence it was derived at (a future suggestion style reads this), the
 *  hidden interior nodes it bridges (`via`, revealed by "Expand derived path"),
 *  and the asserted edge ids forming that path (`viaEdges`, highlighted on
 *  expand). */
export interface DerivedRelation extends ManifestRelation {
  derived: true;
  confidence: Confidence;
  via: string[];
  viaEdges: string[];
}

/** Drop derived edges whose type the relationship-type selection excludes, so
 *  render-time derived edges honour `relationSelected` exactly as asserted edges
 *  do (empty/absent selection = no constraint; see filters/state.ts). There is
 *  deliberately NO revealed-node bypass here: that bypass is for the *asserted*
 *  edges linking revealed interior nodes (so an expanded path is not a field of
 *  disconnected boxes); extending it to derived edges would let a hidden-type
 *  derived edge reappear after "Expand derived path". */
export function filterDerivedByRelation(
  derived: DerivedRelation[],
  relSelection: Set<string> | undefined,
): DerivedRelation[] {
  return derived.filter((d) => relationSelected(relSelection, d.type));
}
