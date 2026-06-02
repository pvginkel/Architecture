import type { Edge, Node } from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { NODE_WIDTH, NODE_HEIGHT, type ArchNodeData, type RelationshipEdgeData } from "../data/model";
import type { ElementKind, LayerId } from "../generated/vocab";

const elk = new ELK();

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

export async function getDirectedLayout(nodes: Node[], edges: Edge[]) {
  const architectureNodes = nodes.filter((node) => node.type === "architecture");
  const visibleIds = new Set(architectureNodes.map((node) => node.id));
  const architectureEdges = edges.filter(
    (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
  );

  const graph = {
    id: "root",
    layoutOptions: {
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
      // BRANDES_KOEPF, not NETWORK_SIMPLEX. Network simplex gives the most
      // balanced/compact placement, but it dominates layout cost: on the real
      // everything view (~540 nodes / ~990 edges) it ran ~20s vs ~2.2s for
      // Brandes–Köpf — a 9x difference, and 20s on the main thread is the
      // everything-view lockup. Brandes–Köpf keeps the same banded structure
      // with slightly less column balancing, which is an acceptable trade for
      // the firehose view.
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
    },
    children: architectureNodes.map((node) => {
      return {
        id: node.id,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        layoutOptions: {
          "elk.partitioning.partition": String(bandPartition(node)),
        },
      };
    }),
    edges: architectureEdges.map((edge) => {
      return {
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
        layoutOptions: {
          "elk.priority": String(relationPriority(edge)),
        },
      };
    }),
  };

  const layout = await elk.layout(graph);
  const positions = new Map(
    layout.children?.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]) ?? [],
  );

  return architectureNodes.map((node) => ({
    id: node.id,
    position: positions.get(node.id) ?? node.position,
  }));
}
