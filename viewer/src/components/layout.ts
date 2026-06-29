import type { Edge, Node } from "@xyflow/react";
import ELK, { type ElkLayoutArguments, type ElkNode } from "elkjs/lib/elk-api.js";
import ElkWorker from "elkjs/lib/elk-worker.min.js?worker";
import { NODE_WIDTH, NODE_HEIGHT, type ArchNodeData, type RelationshipEdgeData } from "../data/model";
import type { ElementKind, LayerId } from "../generated/vocab";

// Run ELK in a Web Worker, not the elk.bundled.js in-thread build. The
// everything-view layout takes seconds (see layout perf notes); on the main
// thread that locks the tab. The graph fed to layout() and the positions
// returned are both plain JSON, so the postMessage hop is cheap relative to
// the compute. Vite's `?worker` import gives a Worker constructor.
//
// The instance is created LAZILY (getElk), never at module top level: the
// `?worker` default is not a usable Worker constructor under vitest's node env,
// so constructing `new ELK({ workerFactory: () => new ElkWorker() })` at import
// time throws and makes this module unimportable in tests. Deferring it behind a
// factory keeps the module importable and lets a test inject a fake ELK that
// never touches the `?worker` path.

/** The slice of the ELK instance this module uses. Typed against the concrete
 *  ElkNode/ElkLayoutArguments shapes `layoutNodes` passes so the real generic
 *  `ELK.layout<T extends ElkNode>` is structurally assignable, and so a test
 *  fake can implement just these two methods. */
export interface ElkLike {
  layout(graph: ElkNode, args?: ElkLayoutArguments): Promise<ElkNode>;
  terminateWorker(): void;
}

export type ElkFactory = () => ElkLike;

export interface LayoutRunOptions {
  /** Aborting terminates the worker and skips any pending/next pass; the run
   *  then rejects with LAYOUT_ABORTED. */
  signal?: AbortSignal;
  /** Test seam: defaults to the real `?worker`-backed factory. */
  elkFactory?: ElkFactory;
}

/** Rejection value of a superseded (aborted) layout run. The React effect
 *  recognises it and treats it as "stop"; any *other* rejection is a real ELK
 *  error and must surface (fail loud). */
export const LAYOUT_ABORTED = Symbol("LAYOUT_ABORTED");

// The default factory is the ONLY place that constructs the real worker-backed
// ELK; it is invoked lazily by getElk.
const defaultElkFactory: ElkFactory = () => new ELK({ workerFactory: () => new ElkWorker() });

// The live ELK instance, created lazily and reused across non-superseded runs
// (no worker churn). Torn down only on abort (resetElk), after which the next
// run lazily recreates it.
let elkInstance: ElkLike | null = null;

function getElk(factory: ElkFactory): ElkLike {
  if (!elkInstance) {
    elkInstance = factory();
  }
  return elkInstance;
}

/** Terminate the live worker and forget the instance. Called only on abort, so
 *  the next layout starts a fresh worker. Idempotent. */
function resetElk(): void {
  if (elkInstance) {
    elkInstance.terminateWorker();
    elkInstance = null;
  }
}

/** Race a pass's layout promise against the abort signal. Terminating the worker
 *  leaves the in-flight `layout()` promise permanently unsettled (the resolver is
 *  dropped — verified in elk-api.js PromisedWorker.terminate), so the run MUST
 *  stop awaiting it on abort rather than expect a resolution/rejection. The
 *  signal's abort is what tells the awaiter to give up. */
function raceAbort<T>(layoutPromise: Promise<T>, signal: AbortSignal | undefined): Promise<T> {
  if (!signal) {
    return layoutPromise;
  }
  let onAbort: (() => void) | undefined;
  const abortPromise = new Promise<T>((_, reject) => {
    if (signal.aborted) {
      reject(LAYOUT_ABORTED);
    } else {
      onAbort = () => reject(LAYOUT_ABORTED);
      signal.addEventListener("abort", onAbort, { once: true });
    }
  });
  // Remove the listener once the race settles either way, so a layout that wins
  // (the common path) leaves nothing attached to the signal.
  return Promise.race([layoutPromise, abortPromise]).finally(() => {
    if (onAbort) {
      signal.removeEventListener("abort", onAbort);
    }
  });
}

// --- Tier 1 layout semantics --------------------------------------------------
// ELK gets fed the architecture meaning it was previously starved of:
//   1. Each node is pinned to a vertical band by its ArchiMate layer
//      (partitioning), so the same kind of element always lands in the same
//      row regardless of view or topology.
//   2. Each edge carries a priority derived from its relationship type, so the
//      structurally important relations (composition, realization, serving) are
//      drawn short and straight while associations stop dragging the layout.

// Vertical bands, bottom -> top. The layout flows UP (see elk.direction below),
// so a higher partition index sits higher on the canvas: strategy on top,
// technology at the bottom — the conventional ArchiMate stack. Flowing up rather
// than down is what makes Serving/Realization arrows point upward
// (provider/realizer at the bottom, consumer/capability above), matching both
// the ArchiMate layered view and the way an infrastructure stack reads: the most
// depended-upon element sinks to the bottom.
//
// Hardware (Node, Device) is split off into its own band at the bottom — it is
// unambiguously the physical foundation, so pinning it there is safe and lets
// hosts/routers sit beneath the software that runs on them. The rest of the
// technology layer (SystemSoftware, TechnologyService, TechnologyInterface)
// stays a SINGLE band ordered by topology, deliberately NOT sub-banded by kind:
// SystemSoftware spans both low-level infra (a CSI driver) and app-grade
// software (a database), so a fixed kind order fights the graph. A storage
// TechnologyService that serves databases must sit below them, while the CSI
// SystemSoftware that realizes it must sit below the service — contradictory as
// fixed bands, but a clean bottom-up chain once topology (under the UP flow)
// orders them. Cross-cutting groupings get the bottom band for now.
const BAND_ORDER = [
  "cross-cutting",
  "hardware", // Node, Device
  "technology", // SystemSoftware, TechnologyService, TechnologyInterface — topology-ordered
  "application", // ApplicationComponent / ApplicationService / ApplicationInterface
  "business", // BusinessService
  "strategy", // Capability
] as const;

type BandKey = (typeof BAND_ORDER)[number];

/** The band an element belongs to. Hardware kinds are pinned to their own band;
 *  every other kind falls back to its layer (always a band key). */
function bandKey(kind: ElementKind, layer: LayerId): BandKey {
  if (kind === "Node" || kind === "Device") {
    return "hardware";
  }
  return layer as BandKey; // technology | application | business | strategy | cross-cutting
}

function bandPartition(node: Node): number {
  const data = node.data as ArchNodeData;
  const index = BAND_ORDER.indexOf(bandKey(data.kind, data.layer));
  if (index < 0) {
    throw new Error(`layout: no band for kind=${data.kind} layer=${data.layer}`);
  }
  return index;
}

// Higher = ELK tries harder to keep the two endpoints close and aligned.
const RELATION_PRIORITY: Record<string, number> = {
  Composition: 100,
  Aggregation: 95,
  Assignment: 90,
  Specialization: 85,
  Realization: 80,
  Serving: 70,
  Triggering: 60,
  Flow: 60,
  Access: 50,
  Influence: 40,
  Association: 10,
  AndJunction: 10,
  OrJunction: 10,
};
const DEFAULT_PRIORITY = 20;

function relationPriority(edge: Edge): number {
  const type = (edge.data as RelationshipEdgeData).relation.type;
  return RELATION_PRIORITY[type] ?? DEFAULT_PRIORITY;
}

const LAYOUT_OPTIONS = {
  "elk.algorithm": "layered",
  // UP, not DOWN: ArchiMate Serving/Realization point from provider to
  // consumer (edge source = the lower-layer provider). Flowing up places the
  // source below the target, so dependencies point upward and the most
  // depended-upon element settles at the bottom — the conventional layered
  // view. With UP, partition 0 is the bottom band (see LAYER_BAND).
  "elk.direction": "UP",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.partitioning.activate": "true",
  // Lay every node out in one shared coordinate system. With this on by
  // default, ELK packs each disconnected component independently and resets
  // their Y, which lets a fragment of (say) technology nodes float above the
  // strategy band — partitioning only orders within a component. Forcing a
  // single component makes the layer bands global and strict. The cost is a
  // wider canvas on dense views; that's acceptable — dense views are the
  // firehose, and the answer there is to scope, not to lay out.
  "elk.separateConnectedComponents": "false",
  "elk.layered.spacing.nodeNodeBetweenLayers": "96",
  // ReactFlow redraws every edge between handles, so ELK's edge geometry is
  // discarded. Reserving per-edge channels between layers is therefore pure
  // wasted vertical space — and with >1000 edges it dominates the layout
  // (gaps of ~1500px). Zero it out so the inter-row gap is just the node
  // height plus nodeNodeBetweenLayers.
  "elk.layered.spacing.edgeNodeBetweenLayers": "0",
  "elk.layered.spacing.edgeEdgeBetweenLayers": "0",
  "elk.spacing.nodeNode": "64",
  // nodePlacement.strategy is chosen per-pass by node count — see
  // nodePlacementStrategy().
} as const;

// Network simplex gives the most balanced/compact placement, but it dominates
// layout cost: on the real everything view (~540 nodes / ~990 edges) it ran
// ~20s vs ~2.2s for Brandes-Koepf — a 9x difference, and 20s on the main thread
// is the everything-view lockup. Brandes-Koepf keeps the same banded structure
// with slightly less column balancing. So use the nicer placement on small
// graphs and fall back to the cheap one once the view gets big.
const NETWORK_SIMPLEX_MAX_NODES = 80;

function nodePlacementStrategy(nodeCount: number): string {
  return nodeCount <= NETWORK_SIMPLEX_MAX_NODES ? "NETWORK_SIMPLEX" : "BRANDES_KOEPF";
}

export async function getDirectedLayout(
  nodes: Node[],
  edges: Edge[],
  options?: LayoutRunOptions,
) {
  const signal = options?.signal;
  // Pre-check: an already-aborted run does no work and rejects immediately.
  if (signal?.aborted) {
    throw LAYOUT_ABORTED;
  }

  const elk = getElk(options?.elkFactory ?? defaultElkFactory);

  // A single abort tears the worker down (so each pass's race unblocks) and, via
  // the per-pass raceAbort, makes this run reject with LAYOUT_ABORTED. Wired once
  // per run, removed in the finally so a settled run leaves no listener behind.
  const onAbort = () => {
    console.debug("[layout] aborted; terminating worker");
    resetElk();
  };
  signal?.addEventListener("abort", onAbort, { once: true });

  try {
    const architectureNodes = nodes.filter((node) => node.type === "architecture");
    const visibleIds = new Set(architectureNodes.map((node) => node.id));
    const architectureEdges = edges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
    );

    // Pass 1: lay the whole graph out. This gives the final positions for views
    // with no over-wide rows (the common case — one pass, no extra cost) and, when
    // a row is too wide, reveals exactly which nodes share that row.
    const first = await layoutNodes(
      elk,
      signal,
      architectureNodes.map((node) => ({
        id: node.id,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        layoutOptions: { "elk.partitioning.partition": String(bandPartition(node)) },
      })),
      architectureEdges.map((edge) => ({
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
        layoutOptions: { "elk.priority": String(relationPriority(edge)) },
      })),
    );

    const fans = discoverWideRowFans(architectureNodes, first);
    if (fans.length === 0) {
      return architectureNodes.map((node) => ({
        id: node.id,
        position: first.get(node.id) ?? node.position,
      }));
    }

    // Between passes: a filter change may have superseded this run while pass 1
    // ran. Don't start the (expensive) second pass for a layout no one wants.
    if (signal?.aborted) {
      throw LAYOUT_ABORTED;
    }

    // Pass 2: replace each wide row with a single super-node sized to the grid its
    // members will occupy, so ELK lays a compact backbone around the boxes instead
    // of stretching everything across a smeared row. Then expand the boxes back
    // into grids (which fit exactly — the super-node reserved their footprint).
    const collapsed = buildCollapsedGraph(architectureNodes, architectureEdges, fans);
    const second = await layoutNodes(elk, signal, collapsed.children, collapsed.edges);

    const positions = new Map<string, { x: number; y: number }>();
    for (const node of architectureNodes) {
      if (!collapsed.memberFan.has(node.id)) {
        positions.set(node.id, second.get(node.id) ?? node.position);
      }
    }
    for (const fan of fans) {
      const origin = second.get(fan.id);
      if (origin) {
        expandFan(fan, origin, positions);
      }
    }

    return architectureNodes.map((node) => ({
      id: node.id,
      position: positions.get(node.id) ?? node.position,
    }));
  } finally {
    signal?.removeEventListener("abort", onAbort);
  }
}

/** Run the shared ELK config over a child/edge set and return id -> position.
 *  The await races the abort signal: an aborted run rejects LAYOUT_ABORTED rather
 *  than hanging on the now-dead worker's unsettled promise. */
async function layoutNodes(
  elk: ElkLike,
  signal: AbortSignal | undefined,
  children: CollapsedGraph["children"],
  elkEdges: CollapsedGraph["edges"],
): Promise<Map<string, { x: number; y: number }>> {
  const layout = await raceAbort(
    elk.layout({
      id: "root",
      layoutOptions: {
        ...LAYOUT_OPTIONS,
        "elk.layered.nodePlacement.strategy": nodePlacementStrategy(children.length),
      },
      children,
      edges: elkEdges,
    }),
    signal,
  );
  return new Map(
    layout.children?.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]) ?? [],
  );
}

// --- Wide-row collapse ---------------------------------------------------------
// ELK's layered algorithm sizes the whole drawing to its widest layer and has no
// knob to cap a layer's width. A band of many sibling leaves with no edges among
// them — the home-automation view's device fleet, dozens of sensors/switches all
// serving the same bridge or hub — lands in one layer and blows it out to a
// single ~28000px row, dragging every other node across that span to align with
// it: a useless smear adrift in empty canvas. ELK's built-in wrapping.strategy
// only cuts the *sequence* of layers (for long-thin graphs); it can't subdivide
// one over-full layer.
//
// So we hide each wide row from a second ELK pass. The first pass reveals which
// nodes share an over-wide row (grouping by Y — one ELK layer is one Y under the
// UP flow); each such row is replaced by a single super-node sized to the grid
// its members will occupy. ELK then lays a compact backbone around the boxes,
// and we expand each box back into the grid — which fits exactly, since the
// super-node reserved its footprint. Discovering rows from a real layout (rather
// than a neighbour-set heuristic) catches heterogeneous rows too, e.g. the mix
// of HA-integrated devices that don't share an identical hub set. (ELK's edge
// geometry is discarded anyway: ReactFlow redraws every edge between handles.)
const PITCH_X = NODE_WIDTH + 64; // node box + elk.spacing.nodeNode
const PITCH_Y = NODE_HEIGHT + 56; // node box + a tight inter-row gap within the grid
// ~16 columns. Wide enough that an ordinary band never trips the wide-row rule,
// narrow enough that a big leaf fan folds into a few readable rows.
const MAX_ROW_WIDTH = 6000;
const FAN_COLUMNS = Math.max(1, Math.floor(MAX_ROW_WIDTH / PITCH_X));

interface FanPlan {
  id: string;
  memberIds: string[];
  width: number;
  height: number;
  partition: number;
}

interface CollapsedGraph {
  children: {
    id: string;
    width: number;
    height: number;
    layoutOptions: Record<string, string>;
  }[];
  edges: {
    id: string;
    sources: string[];
    targets: string[];
    layoutOptions: Record<string, string>;
  }[];
  memberFan: Map<string, FanPlan>;
}

/** From a completed layout, find every row (nodes sharing a Y, i.e. one ELK
 *  layer under the UP flow) with more than FAN_COLUMNS members, and turn each
 *  into a fan: a super-node sized to the grid those members will be laid out in.
 *  Rows that already fit are left alone, so a view with no wide row yields no
 *  fans and skips the second pass entirely. */
function discoverWideRowFans(
  nodes: Node[],
  positions: Map<string, { x: number; y: number }>,
): FanPlan[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const rows = new Map<number, string[]>();
  for (const node of nodes) {
    const position = positions.get(node.id);
    if (!position) {
      continue;
    }
    const key = Math.round(position.y);
    const members = rows.get(key);
    if (members) {
      members.push(node.id);
    } else {
      rows.set(key, [node.id]);
    }
  }

  const fans: FanPlan[] = [];
  let index = 0;
  for (const memberIds of rows.values()) {
    if (memberIds.length <= FAN_COLUMNS) {
      continue; // already fits one row — no need to collapse
    }
    const columns = Math.min(FAN_COLUMNS, memberIds.length);
    const gridRows = Math.ceil(memberIds.length / FAN_COLUMNS);
    fans.push({
      id: `__fan${index++}`,
      // Keep the left-to-right order ELK gave the row, so the grid keeps
      // neighbours adjacent rather than reshuffling.
      memberIds: [...memberIds].sort(
        (a, b) => (positions.get(a)?.x ?? 0) - (positions.get(b)?.x ?? 0),
      ),
      width: columns * NODE_WIDTH + (columns - 1) * (PITCH_X - NODE_WIDTH),
      height: gridRows * NODE_HEIGHT + (gridRows - 1) * (PITCH_Y - NODE_HEIGHT),
      partition: bandPartition(nodeById.get(memberIds[0])!),
    });
  }
  return fans;
}

/** Build the graph ELK's second pass lays out: every fan member removed, one
 *  super-node per fan in its place, and each fan member's edges redirected onto
 *  its super-node (deduped to one per hub, original direction kept). */
function buildCollapsedGraph(
  nodes: Node[],
  edges: Edge[],
  fans: FanPlan[],
): CollapsedGraph {
  const memberFan = new Map<string, FanPlan>();
  for (const fan of fans) {
    for (const id of fan.memberIds) {
      memberFan.set(id, fan);
    }
  }

  const children: CollapsedGraph["children"] = [
    ...nodes
      .filter((node) => !memberFan.has(node.id))
      .map((node) => ({
        id: node.id,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        layoutOptions: { "elk.partitioning.partition": String(bandPartition(node)) },
      })),
    ...fans.map((fan) => ({
      id: fan.id,
      width: fan.width,
      height: fan.height,
      layoutOptions: { "elk.partitioning.partition": String(fan.partition) },
    })),
  ];

  const elkEdges: CollapsedGraph["edges"] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    const sourceFan = memberFan.get(edge.source);
    const targetFan = memberFan.get(edge.target);
    if (sourceFan && targetFan) {
      continue; // both ends collapse away — no edge to draw in the layout graph
    }
    if (!sourceFan && !targetFan) {
      elkEdges.push({
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
        layoutOptions: { "elk.priority": String(relationPriority(edge)) },
      });
      continue;
    }
    // Exactly one end is a fan member — redirect it onto the super-node, keeping
    // the original direction, and keep just one edge per (fan, hub).
    const fan = (sourceFan ?? targetFan)!;
    const fromFan = Boolean(sourceFan);
    const hub = fromFan ? edge.target : edge.source;
    const key = `${fan.id}:${hub}:${fromFan ? "f" : "t"}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    elkEdges.push({
      id: `fan:${key}`,
      sources: [fromFan ? fan.id : hub],
      targets: [fromFan ? hub : fan.id],
      layoutOptions: { "elk.priority": String(relationPriority(edge)) },
    });
  }

  return { children, edges: elkEdges, memberFan };
}

/** Place a fan's members as a grid filling the box ELK reserved for its
 *  super-node, top-left origin, in the row order discovered earlier. */
function expandFan(
  fan: FanPlan,
  origin: { x: number; y: number },
  positions: Map<string, { x: number; y: number }>,
): void {
  fan.memberIds.forEach((id, i) => {
    positions.set(id, {
      x: origin.x + (i % FAN_COLUMNS) * PITCH_X,
      y: origin.y + Math.floor(i / FAN_COLUMNS) * PITCH_Y,
    });
  });
}
