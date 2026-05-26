import {
  Activity,
  Boxes,
  Braces,
  Cable,
  CloudCog,
  Code2,
  Database,
  Eye,
  Filter,
  Home,
  KeyRound,
  Layers,
  LockKeyhole,
  Monitor,
  Network,
  Package,
  Route,
  Search,
  Server,
  Shield,
  Sparkles,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import {
  Background,
  Controls,
  getSmoothStepPath,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import {
  architectureEdges,
  architectureNodes,
  capabilityLabels,
  edgeTypeLabels,
  type ArchitectureEdge,
  type ArchitectureNode,
  type CapabilityId,
  type EdgeType,
} from "../data/architecture";
import { getDirectedLayout } from "./layout";
import { emitToParent, onSetView } from "../parent-bridge";

interface ArchitectureNodeData extends ArchitectureNode {
  dimmed?: boolean;
}

interface TooltipState {
  x: number;
  y: number;
  node: ArchitectureNode;
}

interface EdgeTooltipState {
  x: number;
  y: number;
  edge: ArchitectureEdge;
  sourceLabel: string;
  targetLabel: string;
  typeLabel: string;
}

interface RelationshipEdgeData extends Record<string, unknown> {
  relationship: ArchitectureEdge;
  sourceLabel: string;
  targetLabel: string;
  typeLabel: string;
  color: string;
  highlighted?: boolean;
  dimmed?: boolean;
}

const nodeWidth = 270;
const nodeHeight = 132;

const capabilityColors: Record<CapabilityId, string> = {
  compute: "#52756f",
  networking: "#c36f38",
  storage: "#6d7f3f",
  identity: "#835a9d",
  observability: "#4f6fb0",
  delivery: "#6a5ea8",
  "developer-tools": "#3f7f8f",
  "ai-rag": "#a64d66",
  "home-automation": "#558046",
  media: "#b17836",
  "personal-apps": "#8d6351",
};

const edgeColors: Record<EdgeType, string> = {
  "runs-on": "#52756f",
  deploys: "#6a5ea8",
  builds: "#8f5b2e",
  "pulls-image": "#3f7f8f",
  routes: "#c36f38",
  "stores-data": "#6d7f3f",
  authenticates: "#835a9d",
  "gets-secrets": "#a64d66",
  observes: "#4f6fb0",
};

const capabilityIcons: Record<CapabilityId, LucideIcon> = {
  compute: Server,
  networking: Network,
  storage: Database,
  identity: KeyRound,
  observability: Activity,
  delivery: Workflow,
  "developer-tools": Code2,
  "ai-rag": Sparkles,
  "home-automation": Home,
  media: Monitor,
  "personal-apps": Boxes,
};

const edgeIcons: Record<EdgeType, LucideIcon> = {
  "runs-on": Layers,
  deploys: CloudCog,
  builds: Package,
  "pulls-image": Braces,
  routes: Route,
  "stores-data": Database,
  authenticates: Shield,
  "gets-secrets": LockKeyhole,
  observes: Eye,
};

function toFlowNode(node: ArchitectureNode): Node<ArchitectureNodeData> {
  return {
    id: node.id,
    type: "architecture",
    position: node.position,
    data: node,
    draggable: false,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    zIndex: 10,
    style: {
      width: nodeWidth,
      height: nodeHeight,
    },
  };
}

function toFlowEdge(edge: ArchitectureEdge): Edge<RelationshipEdgeData> {
  const source = architectureNodes.find((node) => node.id === edge.source);
  const target = architectureNodes.find((node) => node.id === edge.target);

  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    animated: false,
    type: "relationship",
    data: {
      relationship: edge,
      sourceLabel: source?.label ?? edge.source,
      targetLabel: target?.label ?? edge.target,
      typeLabel: edgeTypeLabels[edge.type],
      color: edgeColors[edge.type],
    },
    interactionWidth: 18,
    markerEnd: {
      type: "arrowclosed",
      color: edgeColors[edge.type],
      width: 16,
      height: 16,
    },
  };
}

function ArchitectureNodeCard({ data }: NodeProps<Node<ArchitectureNodeData>>) {
  const Icon = capabilityIcons[data.capability];
  const color = capabilityColors[data.capability];

  return (
    <article
      className={`arch-node arch-node--${data.status}${
        data.dimmed ? " arch-node--dimmed" : ""
      }`}
      style={{ "--node-accent": color } as CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="node-handle" />
      <Handle type="source" position={Position.Right} className="node-handle" />
      <div className="arch-node__top">
        <span className="arch-node__icon" aria-hidden="true">
          <Icon size={16} strokeWidth={2.2} />
        </span>
        <span className="arch-node__logo" aria-hidden="true">
          {data.logo ? (
            <img src={`/logos/${data.logo}`} alt="" />
          ) : null}
        </span>
      </div>
      <h3>{data.label}</h3>
      <p>{data.kind}</p>
      <div className="arch-node__meta">
        <span>{capabilityLabels[data.capability]}</span>
        {data.stats?.introduced ? <span>{data.stats.introduced}</span> : null}
      </div>
    </article>
  );
}

function RelationshipEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<Edge<RelationshipEdgeData>>) {
  const relationship = data?.relationship;
  if (!relationship) {
    return null;
  }

  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 10,
  });
  const isPrimary = relationship.strength === "primary";
  const baseWidth = isPrimary ? 2.6 : 1.5;
  const baseOpacity = isPrimary ? 0.78 : 0.46;
  const strokeWidth = data.highlighted ? baseWidth + 1.6 : baseWidth;
  const strokeOpacity = data.dimmed
    ? baseOpacity * 0.15
    : data.highlighted
      ? 0.98
      : baseOpacity;

  return (
    <g className="relationship-edge">
      <path
        id={id}
        className="relationship-edge__path"
        d={edgePath}
        fill="none"
        markerEnd={markerEnd}
        stroke={data.color}
        strokeDasharray={isPrimary ? undefined : "7 7"}
        strokeOpacity={strokeOpacity}
        strokeWidth={strokeWidth}
      />
      <path
        className="relationship-edge__interaction"
        d={edgePath}
        fill="none"
        pointerEvents="stroke"
        stroke="transparent"
        strokeWidth={24}
      />
    </g>
  );
}

function EdgeTooltip({ tooltip }: { tooltip: EdgeTooltipState }) {
  const Icon = edgeIcons[tooltip.edge.type];

  return (
    <div
      className="edge-tooltip"
      style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
    >
      <div className="edge-tooltip__title">
        <Icon size={15} />
        <span>{tooltip.typeLabel}</span>
      </div>
      <p>{tooltip.edge.label}</p>
      <div className="edge-tooltip__route">
        <strong>{tooltip.sourceLabel}</strong>
        <span>to</span>
        <strong>{tooltip.targetLabel}</strong>
      </div>
    </div>
  );
}

const nodeTypes = {
  architecture: ArchitectureNodeCard,
};

const edgeTypes = {
  relationship: RelationshipEdge,
};

function selectedNodeMatches(node: ArchitectureNode, term: string) {
  if (!term) {
    return true;
  }

  const haystack = [node.label, node.kind, node.capability, node.status]
    .join(" ")
    .toLowerCase();

  return haystack.includes(term.toLowerCase());
}

function useVisibleGraph(
  searchTerm: string,
  capabilityFilter: Set<CapabilityId>,
  edgeFilter: Set<EdgeType>,
  directedPositions: Map<string, { x: number; y: number }> | null,
) {
  return useMemo(() => {
    const edgeTypeVisible = (type: EdgeType) =>
      edgeFilter.size === 0 || edgeFilter.has(type);

    const baseIds = new Set<string>();
    const noFilters = capabilityFilter.size === 0 && edgeFilter.size === 0;
    if (noFilters) {
      for (const node of architectureNodes) {
        baseIds.add(node.id);
      }
    } else {
      if (capabilityFilter.size > 0) {
        for (const node of architectureNodes) {
          if (capabilityFilter.has(node.capability)) {
            baseIds.add(node.id);
          }
        }
      }
      if (edgeFilter.size > 0) {
        for (const edge of architectureEdges) {
          if (edgeFilter.has(edge.type)) {
            baseIds.add(edge.source);
            baseIds.add(edge.target);
          }
        }
      }
    }

    const visibleNodeIds = new Set<string>();
    for (const node of architectureNodes) {
      if (baseIds.has(node.id) && selectedNodeMatches(node, searchTerm)) {
        visibleNodeIds.add(node.id);
      }
    }
    const visibleArchitectureNodes = architectureNodes.filter((node) =>
      visibleNodeIds.has(node.id),
    );

    const flowNodes = visibleArchitectureNodes.map((node) => {
      const flowNode = toFlowNode(node);
      const directedPosition = directedPositions?.get(node.id);
      if (directedPosition) {
        return {
          ...flowNode,
          position: directedPosition,
        };
      }
      return flowNode;
    });

    const flowEdges = architectureEdges
      .filter((edge) => edgeTypeVisible(edge.type))
      .filter(
        (edge) =>
          visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target),
      )
      .map(toFlowEdge);

    return {
      nodes: flowNodes,
      edges: flowEdges,
      visibleArchitectureNodes,
    };
  }, [capabilityFilter, directedPositions, edgeFilter, searchTerm]);
}

function Tooltip({ tooltip }: { tooltip: TooltipState }) {
  const { node, x, y } = tooltip;

  return (
    <div className="node-tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="node-tooltip__title">{node.label}</div>
      <div className="node-tooltip__kind">{node.kind}</div>
      <p>{node.summary}</p>
      <dl>
        {node.stats?.sourceRepo ? (
          <>
            <dt>Repo</dt>
            <dd>{node.stats.sourceRepo}</dd>
          </>
        ) : null}
        {node.stats?.version ? (
          <>
            <dt>Version</dt>
            <dd>{node.stats.version}</dd>
          </>
        ) : null}
        {node.stats?.loc ? (
          <>
            <dt>LoC</dt>
            <dd>{node.stats.loc}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
}) {
  return (
    <button
      className={`toggle-button ${active ? "toggle-button--active" : ""}`}
      onClick={onClick}
      title={title}
      type="button"
    >
      {children}
    </button>
  );
}

function ArchitectureMapInner() {
  const { fitView } = useReactFlow();
  const [searchTerm, setSearchTerm] = useState("");
  const [capabilityFilter, setCapabilityFilter] = useState<Set<CapabilityId>>(
    new Set(),
  );
  const [edgeFilter, setEdgeFilter] = useState<Set<EdgeType>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltipState | null>(null);
  const [directedPositions, setDirectedPositions] = useState<Map<
    string,
    { x: number; y: number }
  > | null>(null);
  const { nodes, edges, visibleArchitectureNodes } = useVisibleGraph(
    searchTerm,
    capabilityFilter,
    edgeFilter,
    directedPositions,
  );

  useEffect(() => {
    emitToParent({
      type: "view-change",
      view: JSON.stringify({
        search: searchTerm,
        capabilities: Array.from(capabilityFilter),
        edges: Array.from(edgeFilter),
      }),
    });
  }, [searchTerm, capabilityFilter, edgeFilter]);

  useEffect(() => {
    return onSetView((view) => {
      try {
        const parsed = JSON.parse(view) as {
          search?: string;
          capabilities?: CapabilityId[];
          edges?: EdgeType[];
        };
        if (typeof parsed.search === "string") {
          setSearchTerm(parsed.search);
        }
        if (Array.isArray(parsed.capabilities)) {
          setCapabilityFilter(new Set(parsed.capabilities));
        }
        if (Array.isArray(parsed.edges)) {
          setEdgeFilter(new Set(parsed.edges));
        }
      } catch {
        // ignore malformed views from the parent
      }
    });
  }, []);

  const connectedNodeIds = useMemo(() => {
    if (!selectedId) {
      return null;
    }
    const connected = new Set<string>([selectedId]);
    for (const edge of edges) {
      if (edge.source === selectedId) {
        connected.add(edge.target);
      } else if (edge.target === selectedId) {
        connected.add(edge.source);
      }
    }
    return connected;
  }, [edges, selectedId]);

  const decoratedEdges = useMemo(() => {
    if (!selectedId) {
      return edges;
    }
    return edges.map((edge) => {
      const touchesSelected =
        edge.source === selectedId || edge.target === selectedId;
      if (touchesSelected) {
        return {
          ...edge,
          zIndex: 20,
          data: edge.data ? { ...edge.data, highlighted: true } : edge.data,
        };
      }
      return {
        ...edge,
        data: edge.data ? { ...edge.data, dimmed: true } : edge.data,
      };
    });
  }, [edges, selectedId]);

  const decoratedNodes = useMemo(() => {
    if (!connectedNodeIds) {
      return nodes;
    }
    return nodes.map((node) => {
      if (connectedNodeIds.has(node.id)) {
        return node;
      }
      return {
        ...node,
        data: { ...node.data, dimmed: true },
      };
    });
  }, [nodes, connectedNodeIds]);

  const layoutKey = useMemo(
    () =>
      [
        visibleArchitectureNodes.map((node) => node.id).join(","),
        edges.map((edge) => edge.id).join(","),
      ].join("|"),
    [edges, visibleArchitectureNodes],
  );

  useEffect(() => {
    let cancelled = false;

    getDirectedLayout(nodes, edges).then((laidOut) => {
      if (cancelled) {
        return;
      }

      setDirectedPositions(
        new Map(laidOut.map((item) => [item.id, item.position])),
      );
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          fitView({
            duration: 320,
            padding: 0.12,
            maxZoom: window.innerWidth < 760 ? 0.58 : 0.72,
          });
        });
      });
    });

    return () => {
      cancelled = true;
    };
  }, [layoutKey, fitView]);

  const onNodeMouseEnter = useCallback<NodeMouseHandler>((event, node) => {
    if (node.type !== "architecture") {
      return;
    }
    setTooltip({
      x: event.clientX,
      y: event.clientY,
      node: node.data as ArchitectureNode,
    });
  }, []);

  const onNodeMouseMove = useCallback<NodeMouseHandler>((event, node) => {
    if (node.type !== "architecture") {
      return;
    }
    setTooltip((current) =>
      current
        ? {
            ...current,
            x: event.clientX,
            y: event.clientY,
          }
        : null,
    );
  }, []);

  const onNodeMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  const onEdgeMouseEnter = useCallback(
    (event: ReactMouseEvent, edge: Edge<RelationshipEdgeData>) => {
      if (!edge.data) {
        return;
      }
      setEdgeTooltip({
        x: event.clientX,
        y: event.clientY,
        edge: edge.data.relationship,
        sourceLabel: edge.data.sourceLabel,
        targetLabel: edge.data.targetLabel,
        typeLabel: edge.data.typeLabel,
      });
    },
    [],
  );

  const onEdgeMouseMove = useCallback(
    (event: ReactMouseEvent, edge: Edge<RelationshipEdgeData>) => {
      if (!edge.data) {
        return;
      }
      setEdgeTooltip((current) =>
        current
          ? {
              ...current,
              x: event.clientX,
              y: event.clientY,
            }
          : null,
      );
    },
    [],
  );

  const onEdgeMouseLeave = useCallback(() => {
    setEdgeTooltip(null);
  }, []);

  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
    if (node.type !== "architecture") {
      return;
    }
    setSelectedId(node.id);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedId(null);
  }, []);

  const onEdgeClick = useCallback(() => {
    setSelectedId(null);
  }, []);

  const toggleCapability = (capability: CapabilityId) => {
    setCapabilityFilter((current) => {
      const next = new Set(current);
      if (next.has(capability)) {
        next.delete(capability);
      } else {
        next.add(capability);
      }
      return next;
    });
  };

  const toggleEdge = (edgeType: EdgeType) => {
    setEdgeFilter((current) => {
      const next = new Set(current);
      if (next.has(edgeType)) {
        next.delete(edgeType);
      } else {
        next.add(edgeType);
      }
      return next;
    });
  };

  const clearFilters = () => {
    setSearchTerm("");
    setCapabilityFilter(new Set());
    setEdgeFilter(new Set());
  };

  return (
    <div className="architecture-page">
      <section className="workspace">
        <div className="map-shell">
          <div className="controls-panel">
            <div className="controls-panel__row">
              <label className="search-box">
                <Search size={16} />
                <input
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Search components"
                />
              </label>
              <button
                className="icon-text-button"
                onClick={clearFilters}
                title="Reset filters"
              >
                <X size={16} />
                Reset Filters
              </button>
            </div>

            <div className="controls-panel__filters">
              <span className="controls-panel__label">
                <Filter size={14} />
                Capability
              </span>
              {(Object.keys(capabilityLabels) as CapabilityId[]).map(
                (capability) => {
                  const Icon = capabilityIcons[capability];
                  return (
                    <ToggleButton
                      key={capability}
                      active={capabilityFilter.has(capability)}
                      onClick={() => toggleCapability(capability)}
                      title={capabilityLabels[capability]}
                    >
                      <Icon size={14} />
                      {capabilityLabels[capability]}
                    </ToggleButton>
                  );
                },
              )}
              <span className="controls-panel__break" aria-hidden />
              <span className="controls-panel__label">
                <Cable size={14} />
                Relationship
              </span>
              {(Object.keys(edgeTypeLabels) as EdgeType[]).map((edgeType) => {
                const Icon = edgeIcons[edgeType];
                return (
                  <ToggleButton
                    key={edgeType}
                    active={edgeFilter.has(edgeType)}
                    onClick={() => toggleEdge(edgeType)}
                    title={edgeTypeLabels[edgeType]}
                  >
                    <Icon size={14} />
                    {edgeTypeLabels[edgeType]}
                  </ToggleButton>
                );
              })}
            </div>
          </div>

          <div className="diagram-region" data-testid="architecture-diagram">
            <ReactFlow
              nodes={decoratedNodes}
              edges={decoratedEdges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              nodesDraggable={false}
              defaultViewport={{ x: 0, y: 0, zoom: 0.72 }}
              minZoom={0.24}
              maxZoom={1.35}
              onNodeClick={onNodeClick}
              onNodeMouseEnter={onNodeMouseEnter}
              onNodeMouseMove={onNodeMouseMove}
              onNodeMouseLeave={onNodeMouseLeave}
              onEdgeClick={onEdgeClick}
              onEdgeMouseEnter={onEdgeMouseEnter}
              onEdgeMouseMove={onEdgeMouseMove}
              onEdgeMouseLeave={onEdgeMouseLeave}
              onPaneClick={onPaneClick}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#d7d7ce" gap={24} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
            {tooltip ? <Tooltip tooltip={tooltip} /> : null}
            {edgeTooltip ? <EdgeTooltip tooltip={edgeTooltip} /> : null}
          </div>
        </div>

      </section>
    </div>
  );
}

export function ArchitectureMap() {
  return (
    <ReactFlowProvider>
      <ArchitectureMapInner />
    </ReactFlowProvider>
  );
}
