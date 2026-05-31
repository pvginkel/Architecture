import { Cable, Filter, Layers, Search, Spline, TriangleAlert, X } from "lucide-react";
import {
  Fragment,
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
  ELEMENT_KINDS,
  KIND_LABELS,
  LAYER_IDS,
  LAYER_LABELS,
  RELATIONSHIP_TYPES,
  RELATIONSHIP_LABELS,
  type ElementKind,
  type LayerId,
  type RelationshipType,
} from "../generated/vocab";
import {
  buildModel,
  toFlowEdges,
  toFlowNodes,
  type ArchElement,
  type ArchModel,
  type ArchNodeData,
  type RelationshipEdgeData,
} from "../data/model";
import { loadManifest, resolveSrc, type Manifest } from "../data/manifest";
import { CAPABILITY_ICON, KIND_ICON, LAYER_ACCENT } from "../theme";
import { getDirectedLayout } from "./layout";
import { emitToParent, onSetView } from "../parent-bridge";

interface TooltipState {
  x: number;
  y: number;
  element: ArchElement;
}

interface EdgeTooltipState {
  x: number;
  y: number;
  sourceLabel: string;
  targetLabel: string;
  typeLabel: string;
}

function ArchitectureNodeCard({ data }: NodeProps<Node<ArchNodeData>>) {
  const Icon = KIND_ICON[data.kind];
  const accent = LAYER_ACCENT[data.layer];

  // Runtime skew guard: data newer than the build (a kind/layer the vocab
  // doesn't know). The theme maps are typed complete, so this is unreachable
  // unless the manifest carries a value this build has never seen. Be loud,
  // not silently generic.
  if (!Icon || !accent) {
    const what = !Icon ? `kind '${data.kind}'` : `layer '${data.layer}'`;
    console.error(`[viewer] unknown ${what} — vocab is stale, rebuild`);
    return (
      <article className="arch-node arch-node--stale">
        <Handle type="target" position={Position.Left} className="node-handle" />
        <Handle type="source" position={Position.Right} className="node-handle" />
        <div className="arch-node__stale-badge">
          <TriangleAlert size={16} /> unknown {what}
        </div>
        <h3>{data.label}</h3>
      </article>
    );
  }

  let rightImage: ReactNode = null;
  if (data.logo) {
    rightImage = <img src={`${import.meta.env.BASE_URL}logos/${data.logo}`} alt="" />;
  } else if (data.capabilityId) {
    const CapIcon = CAPABILITY_ICON[data.capabilityId];
    if (CapIcon) {
      rightImage = <CapIcon size={18} strokeWidth={2} />;
    } else {
      console.error(
        `[viewer] unknown capability '${data.capabilityId}' — vocab is stale, rebuild`,
      );
      rightImage = <span className="arch-node__stale-mark">?</span>;
    }
  }

  return (
    <article
      className={`arch-node arch-node--${data.lifecycle}${
        data.dimmed ? " arch-node--dimmed" : ""
      }`}
      style={{ "--node-accent": accent } as CSSProperties}
    >
      <Handle type="target" position={Position.Left} className="node-handle" />
      <Handle type="source" position={Position.Right} className="node-handle" />
      <div className="arch-node__top">
        <span className="arch-node__icon" aria-hidden="true">
          <Icon size={16} strokeWidth={2.2} />
        </span>
        <span className="arch-node__logo" aria-hidden="true">
          {rightImage}
        </span>
      </div>
      <h3>{data.label}</h3>
      <p>{KIND_LABELS[data.kind]}</p>
      <div className="arch-node__meta">
        <span>{data.producer}</span>
        {data.introduced ? <span>{data.introduced}</span> : null}
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
  if (!data?.relation) {
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
  const baseWidth = 2.2;
  const baseOpacity = 0.62;
  const strokeWidth = data.highlighted ? baseWidth + 1.6 : baseWidth;
  const strokeOpacity = data.dimmed ? 0.12 : data.highlighted ? 0.98 : baseOpacity;

  return (
    <g className="relationship-edge">
      <path
        id={id}
        className="relationship-edge__path"
        d={edgePath}
        fill="none"
        markerEnd={markerEnd}
        stroke={data.color}
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
  return (
    <div
      className="edge-tooltip"
      style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
    >
      <div className="edge-tooltip__title">
        <Spline size={15} />
        <span>{tooltip.typeLabel}</span>
      </div>
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

function elementMatchesSearch(el: ArchElement, term: string) {
  if (!term) {
    return true;
  }
  const haystack = [el.label, KIND_LABELS[el.kind], el.summary, el.producer]
    .join(" ")
    .toLowerCase();
  return haystack.includes(term);
}

function useVisibleGraph(
  model: ArchModel | null,
  searchTerm: string,
  layerFilter: Set<LayerId>,
  kindFilter: Set<ElementKind>,
  relFilter: Set<RelationshipType>,
  directedPositions: Map<string, { x: number; y: number }> | null,
) {
  return useMemo(() => {
    if (!model) {
      return { nodes: [], edges: [], visibleElements: [] as ArchElement[] };
    }

    const term = searchTerm.trim().toLowerCase();

    // prd default: drop dev/tst/uat. (The Environment filter UI lands in Plan 3;
    // the default applies now so the canvas isn't multiplied across stages.)
    // Within-group OR, across-group AND.
    const visibleElements = model.elements.filter((el) => {
      const envOk = el.environment === undefined || el.environment === "prd";
      const layerOk = layerFilter.size === 0 || layerFilter.has(el.layer);
      const kindOk = kindFilter.size === 0 || kindFilter.has(el.kind);
      return envOk && layerOk && kindOk && elementMatchesSearch(el, term);
    });

    const visibleIds = new Set(visibleElements.map((el) => el.id));
    const nodes = toFlowNodes(visibleElements).map((node) => {
      const position = directedPositions?.get(node.id);
      return position ? { ...node, position } : node;
    });

    // No relation type selected → all relations among visible nodes; some
    // selected → restrict to those.
    const visibleRelations = model.relations.filter(
      (rel) =>
        (relFilter.size === 0 || relFilter.has(rel.type)) &&
        visibleIds.has(rel.source) &&
        visibleIds.has(rel.target),
    );
    const edges = toFlowEdges(visibleRelations, model.elementById);

    return { nodes, edges, visibleElements };
  }, [model, searchTerm, layerFilter, kindFilter, relFilter, directedPositions]);
}

function Tooltip({ tooltip }: { tooltip: TooltipState }) {
  const { element, x, y } = tooltip;
  const stats = element.stats ?? {};

  return (
    <div className="node-tooltip" style={{ left: x + 14, top: y + 14 }}>
      <div className="node-tooltip__title">{element.label}</div>
      <div className="node-tooltip__kind">{KIND_LABELS[element.kind]}</div>
      <p>{element.summary}</p>
      <dl>
        <dt>Layer</dt>
        <dd>{LAYER_LABELS[element.layer]}</dd>
        <dt>Lifecycle</dt>
        <dd>{element.lifecycle}</dd>
        {element.environment ? (
          <>
            <dt>Environment</dt>
            <dd>{element.environment}</dd>
          </>
        ) : null}
        {element.sourceRepository ? (
          <>
            <dt>Repo</dt>
            <dd>{element.sourceRepository}</dd>
          </>
        ) : null}
        {Object.entries(stats).map(([key, value]) => (
          <Fragment key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </Fragment>
        ))}
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

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function ArchitectureMapInner() {
  const { fitView } = useReactFlow();
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [layerFilter, setLayerFilter] = useState<Set<LayerId>>(new Set());
  const [kindFilter, setKindFilter] = useState<Set<ElementKind>>(new Set());
  const [relFilter, setRelFilter] = useState<Set<RelationshipType>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltipState | null>(null);
  const [directedPositions, setDirectedPositions] = useState<Map<
    string,
    { x: number; y: number }
  > | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadManifest(resolveSrc())
      .then((loaded) => {
        if (!cancelled) {
          setManifest(loaded);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const model = useMemo(() => (manifest ? buildModel(manifest) : null), [manifest]);

  const { nodes, edges, visibleElements } = useVisibleGraph(
    model,
    searchTerm,
    layerFilter,
    kindFilter,
    relFilter,
    directedPositions,
  );

  useEffect(() => {
    emitToParent({
      type: "view-change",
      view: JSON.stringify({
        search: searchTerm,
        layers: Array.from(layerFilter),
        kinds: Array.from(kindFilter),
        relationships: Array.from(relFilter),
      }),
    });
  }, [searchTerm, layerFilter, kindFilter, relFilter]);

  useEffect(() => {
    return onSetView((view) => {
      const parsed = JSON.parse(view) as {
        search?: string;
        layers?: LayerId[];
        kinds?: ElementKind[];
        relationships?: RelationshipType[];
      };
      if (typeof parsed.search === "string") {
        setSearchTerm(parsed.search);
      }
      if (Array.isArray(parsed.layers)) {
        setLayerFilter(new Set(parsed.layers));
      }
      if (Array.isArray(parsed.kinds)) {
        setKindFilter(new Set(parsed.kinds));
      }
      if (Array.isArray(parsed.relationships)) {
        setRelFilter(new Set(parsed.relationships));
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
      const touchesSelected = edge.source === selectedId || edge.target === selectedId;
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
      return { ...node, data: { ...node.data, dimmed: true } };
    });
  }, [nodes, connectedNodeIds]);

  const layoutKey = useMemo(
    () =>
      [
        visibleElements.map((el) => el.id).join(","),
        edges.map((edge) => edge.id).join(","),
      ].join("|"),
    [edges, visibleElements],
  );

  useEffect(() => {
    if (nodes.length === 0) {
      return;
    }
    let cancelled = false;
    getDirectedLayout(nodes, edges).then((laidOut) => {
      if (cancelled) {
        return;
      }
      setDirectedPositions(new Map(laidOut.map((item) => [item.id, item.position])));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey, fitView]);

  const onNodeMouseEnter = useCallback<NodeMouseHandler>((event, node) => {
    if (node.type !== "architecture") {
      return;
    }
    setTooltip({ x: event.clientX, y: event.clientY, element: node.data as ArchElement });
  }, []);

  const onNodeMouseMove = useCallback<NodeMouseHandler>((event, node) => {
    if (node.type !== "architecture") {
      return;
    }
    setTooltip((current) =>
      current ? { ...current, x: event.clientX, y: event.clientY } : null,
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
        current ? { ...current, x: event.clientX, y: event.clientY } : null,
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

  const clearFilters = () => {
    setSearchTerm("");
    setLayerFilter(new Set());
    setKindFilter(new Set());
    setRelFilter(new Set());
  };

  return (
    <div className="architecture-page">
      <section className="workspace">
        <div className="map-shell">
          {model ? (
            <div className="controls-panel">
              <div className="controls-panel__row">
                <label className="search-box">
                  <Search size={16} />
                  <input
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    placeholder="Search elements"
                  />
                </label>
                <button
                  className="icon-text-button"
                  onClick={clearFilters}
                  title="Reset filters"
                  type="button"
                >
                  <X size={16} />
                  Reset Filters
                </button>
              </div>

              <div className="controls-panel__filters">
                <span className="controls-panel__label">
                  <Layers size={14} />
                  Layer
                </span>
                {LAYER_IDS.map((layer) => (
                  <ToggleButton
                    key={layer}
                    active={layerFilter.has(layer)}
                    onClick={() => setLayerFilter((current) => toggle(current, layer))}
                    title={LAYER_LABELS[layer]}
                  >
                    <span
                      className="toggle-swatch"
                      style={{ background: LAYER_ACCENT[layer] }}
                      aria-hidden
                    />
                    {LAYER_LABELS[layer]}
                  </ToggleButton>
                ))}
                <span className="controls-panel__break" aria-hidden />

                <span className="controls-panel__label">
                  <Filter size={14} />
                  Kind
                </span>
                {ELEMENT_KINDS.map((kind) => {
                  const Icon = KIND_ICON[kind];
                  return (
                    <ToggleButton
                      key={kind}
                      active={kindFilter.has(kind)}
                      onClick={() => setKindFilter((current) => toggle(current, kind))}
                      title={KIND_LABELS[kind]}
                    >
                      <Icon size={14} />
                      {KIND_LABELS[kind]}
                    </ToggleButton>
                  );
                })}
                <span className="controls-panel__break" aria-hidden />

                <span className="controls-panel__label">
                  <Cable size={14} />
                  Relationship
                </span>
                {RELATIONSHIP_TYPES.map((rel) => (
                  <ToggleButton
                    key={rel}
                    active={relFilter.has(rel)}
                    onClick={() => setRelFilter((current) => toggle(current, rel))}
                    title={RELATIONSHIP_LABELS[rel]}
                  >
                    {RELATIONSHIP_LABELS[rel]}
                  </ToggleButton>
                ))}
              </div>
            </div>
          ) : null}

          <div className="diagram-region" data-testid="architecture-diagram">
            {error ? (
              <div className="load-state load-state--error">
                <TriangleAlert size={22} />
                <p>Failed to load the architecture manifest.</p>
                <code>{error.message}</code>
              </div>
            ) : !model ? (
              <div className="load-state">Loading architecture…</div>
            ) : (
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
            )}
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
