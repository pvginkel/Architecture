import type { Edge, Node } from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { NODE_WIDTH, NODE_HEIGHT, type ArchNodeData, type RelationshipEdgeData } from "../data/model";
import type { LayerId } from "../generated/vocab";

const elk = new ELK();

// --- Tier 1 layout semantics --------------------------------------------------
// ELK gets fed the architecture meaning it was previously starved of:
//   1. Each node is pinned to a vertical band by its ArchiMate layer
//      (partitioning), so the same kind of element always lands in the same
//      row regardless of view or topology.
//   2. Each edge carries a priority derived from its relationship type, so the
//      structurally important relations (composition, realization, serving) are
//      drawn short and straight while associations stop dragging the layout.

// Top-to-bottom band order. Strategy on top, technology at the bottom — the
// conventional ArchiMate stack. Cross-cutting groupings get their own band at
// the bottom for now; this ordering is the obvious knob to revisit.
const LAYER_BAND: Record<LayerId, number> = {
  strategy: 0,
  business: 1,
  application: 2,
  technology: 3,
  "cross-cutting": 4,
};

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
      "elk.direction": "DOWN",
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
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    },
    children: architectureNodes.map((node) => {
      const layer = (node.data as ArchNodeData).layer;
      return {
        id: node.id,
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        layoutOptions: {
          "elk.partitioning.partition": String(LAYER_BAND[layer]),
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
