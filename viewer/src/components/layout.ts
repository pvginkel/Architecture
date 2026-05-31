import type { Edge, Node } from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { NODE_WIDTH, NODE_HEIGHT } from "../data/model";

const elk = new ELK();

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
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": "72",
      "elk.spacing.nodeNode": "40",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    },
    children: architectureNodes.map((node) => ({
      id: node.id,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
    edges: architectureEdges.map((edge) => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target],
    })),
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
