// View-model: turn a fetched ArchiMate manifest into the flat element/relation
// shape the ReactFlow canvas consumes. Replaces the role of the old hand-built
// architecture.ts taxonomy.

import { Position, type Edge, type Node } from "@xyflow/react";
import {
  ELEMENT_KINDS,
  KIND_TO_ARRAY,
  KIND_TO_LAYER,
  RELATIONSHIP_LABELS,
  type CapabilityId,
  type ElementKind,
  type LayerId,
} from "../generated/vocab";
import { LAYER_ACCENT } from "../theme";
import type { Manifest, ManifestElement, ManifestRelation } from "./manifest";

// A manifest element tagged with its kind (from the array it lived in), its
// computed layer, and the capability it realizes (if any). The index signature
// lets it ride directly as ReactFlow node data.
export interface ArchElement extends ManifestElement {
  kind: ElementKind;
  layer: LayerId;
  capabilityId?: CapabilityId;
  // A runtime instance — a concrete deployed unit (a Helm release's workload /
  // container) rather than an architectural definition. Carries `stats.release`.
  // Views can drop these wholesale (see ViewDefinition.excludeInstances).
  isInstance: boolean;
  [key: string]: unknown;
}

export type ArchNodeData = ArchElement & { dimmed?: boolean; highlighted?: boolean };

export interface RelationshipEdgeData extends Record<string, unknown> {
  relation: ManifestRelation;
  sourceLabel: string;
  targetLabel: string;
  typeLabel: string;
  color: string;
  highlighted?: boolean;
  dimmed?: boolean;
}

export interface ArchModel {
  elements: ArchElement[];
  relations: ManifestRelation[];
  elementById: Map<string, ArchElement>;
}

export const NODE_WIDTH = 300;
export const NODE_HEIGHT = 158;

/** Invert derived.capabilityRealizations into element-id → capability. First
 *  realized capability wins, deterministically (object insertion order). */
function buildElementCapability(manifest: Manifest): Map<string, CapabilityId> {
  const map = new Map<string, CapabilityId>();
  for (const [cap, members] of Object.entries(manifest.derived.capabilityRealizations)) {
    for (const id of members) {
      if (!map.has(id)) {
        map.set(id, cap as CapabilityId);
      }
    }
  }
  return map;
}

export function buildModel(manifest: Manifest): ArchModel {
  const elementCapability = buildElementCapability(manifest);
  const elements: ArchElement[] = [];

  for (const kind of ELEMENT_KINDS) {
    const arrayKey = KIND_TO_ARRAY[kind];
    const layer = KIND_TO_LAYER[kind];
    for (const el of manifest[arrayKey]) {
      elements.push({
        ...el,
        kind,
        layer,
        capabilityId: elementCapability.get(el.id),
        isInstance: el.stats?.release !== undefined,
      });
    }
  }

  const elementById = new Map(elements.map((el) => [el.id, el]));
  return { elements, relations: manifest.relations, elementById };
}

export function toFlowNode(el: ArchElement): Node<ArchNodeData> {
  return {
    id: el.id,
    type: "architecture",
    position: { x: 0, y: 0 },
    data: el,
    draggable: false,
    sourcePosition: Position.Bottom,
    targetPosition: Position.Top,
    zIndex: 10,
    style: { width: NODE_WIDTH, height: NODE_HEIGHT },
  };
}

export function toFlowNodes(elements: ArchElement[]): Node<ArchNodeData>[] {
  return elements.map(toFlowNode);
}

export function toFlowEdge(
  rel: ManifestRelation,
  elementById: Map<string, ArchElement>,
): Edge<RelationshipEdgeData> {
  const source = elementById.get(rel.source);
  const target = elementById.get(rel.target);
  const color = source ? LAYER_ACCENT[source.layer] : "#9aa09a";

  return {
    id: rel.id,
    source: rel.source,
    target: rel.target,
    animated: false,
    type: "relationship",
    data: {
      relation: rel,
      sourceLabel: source?.label ?? rel.source,
      targetLabel: target?.label ?? rel.target,
      typeLabel: RELATIONSHIP_LABELS[rel.type],
      color,
    },
    interactionWidth: 18,
    markerEnd: {
      type: "arrowclosed",
      color,
      width: 16,
      height: 16,
    },
  };
}

export function toFlowEdges(
  relations: ManifestRelation[],
  elementById: Map<string, ArchElement>,
): Edge<RelationshipEdgeData>[] {
  return relations.map((rel) => toFlowEdge(rel, elementById));
}
