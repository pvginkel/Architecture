import { Spline, TriangleAlert } from "lucide-react";
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
  KIND_LABELS,
  LAYER_LABELS,
  LOGO_FILES,
  type LogoName,
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
import {
  loadManifest,
  resolveSrc,
  type Manifest,
  type ViewDefinition,
} from "../data/manifest";
import { CAPABILITY_ICON, KIND_ICON, LAYER_ACCENT } from "../theme";
import { getDirectedLayout } from "./layout";
import { ViewTabs } from "./ViewTabs";
import { emitToParent, onSetView } from "../parent-bridge";
import { FilterRail } from "../filters/FilterRail";
import { buildGroups } from "../filters/groups";
import {
  loadActiveView,
  loadCollapsed,
  saveActiveView,
  saveCollapsed,
} from "../filters/persistence";
import {
  addFilterOptions,
  computeVisibleGraph,
  initialFilterState,
  serializeFilters,
  toggleFilterOption,
  type FilterState,
} from "../filters/state";
import {
  pickInitialView,
  resolveViewScope,
  viewBaselineFilterState,
} from "../views/scope";

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

// Each node exposes a source and a target handle on both its top and bottom
// edges. The edge builder picks which pair to use per relation so an upward
// edge connects the two facing sides (top of the lower node → bottom of the
// upper node) instead of looping around. Handle ids are referenced by the
// sourceHandle/targetHandle assigned in useVisibleGraph.
const HANDLE = {
  sourceTop: "src-top",
  sourceBottom: "src-bottom",
  targetTop: "tgt-top",
  targetBottom: "tgt-bottom",
} as const;

function NodeHandles() {
  return (
    <>
      <Handle id={HANDLE.targetTop} type="target" position={Position.Top} className="node-handle" />
      <Handle id={HANDLE.sourceTop} type="source" position={Position.Top} className="node-handle" />
      <Handle
        id={HANDLE.targetBottom}
        type="target"
        position={Position.Bottom}
        className="node-handle"
      />
      <Handle
        id={HANDLE.sourceBottom}
        type="source"
        position={Position.Bottom}
        className="node-handle"
      />
    </>
  );
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
        <NodeHandles />
        <div className="arch-node__stale-badge">
          <TriangleAlert size={16} /> unknown {what}
        </div>
        <h3>{data.label}</h3>
      </article>
    );
  }

  let rightImage: ReactNode = null;
  if (data.logo) {
    const file = LOGO_FILES[data.logo as LogoName];
    if (!file) {
      console.error(`[viewer] unknown logo '${data.logo}' — vocab is stale, rebuild`);
      rightImage = <span className="arch-node__stale-mark">?</span>;
    } else {
      rightImage = <img src={`${import.meta.env.BASE_URL}logos/${file}`} alt="" />;
    }
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

  // A deployed-container instance (helm-charts producer) carries release /
  // workload / container in stats; its card leads with the container and a
  // "release » workload" locator. Everything else (products, services) keeps
  // the label + kind-label shape.
  const stats = data.stats ?? {};
  const isInstance =
    typeof stats.container === "string" &&
    typeof stats.release === "string" &&
    typeof stats.workload === "string";
  const stage = data.environment;
  // The merged label carries a " (env)" postfix; the stage now has its own
  // chip, so strip it from the displayed label.
  const displayLabel =
    stage && data.label.endsWith(` (${stage})`)
      ? data.label.slice(0, -` (${stage})`.length)
      : data.label;

  return (
    <article
      className={`arch-node arch-node--${data.lifecycle}${
        data.dimmed ? " arch-node--dimmed" : ""
      }${data.highlighted ? " arch-node--highlighted" : ""}`}
      style={{ "--node-accent": accent } as CSSProperties}
    >
      <NodeHandles />
      <div className="arch-node__top">
        <span className="arch-node__icon" aria-hidden="true">
          <Icon size={16} strokeWidth={2.2} />
        </span>
        <span className="arch-node__top-right">
          {stage ? <span className="arch-node__stage">{stage}</span> : null}
          {rightImage ? (
            <span className="arch-node__logo" aria-hidden="true">
              {rightImage}
            </span>
          ) : null}
        </span>
      </div>
      {isInstance ? (
        <>
          <h3>{stats.container}</h3>
          <p className="arch-node__locator">
            <span className="arch-node__release">{stats.release}</span>
            <span className="arch-node__locator-sep"> » </span>
            <span className="arch-node__workload">{stats.workload}</span>
          </p>
        </>
      ) : (
        <>
          <h3>{displayLabel}</h3>
          <p>{KIND_LABELS[data.kind]}</p>
        </>
      )}
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
  // Opacity rides on the group, not the path's strokeOpacity, so the arrowhead
  // marker (a separate, shared SVG element that doesn't inherit strokeOpacity)
  // dims and brightens together with the line.
  const opacity = data.dimmed ? 0.12 : data.highlighted ? 0.98 : baseOpacity;
  // Derived edges (collector-projected from instance-level facts) read as
  // inferred, not modelled: dashed line, slightly muted unless highlighted.
  const derived = data.relation.derived === true;

  return (
    <g
      className="relationship-edge"
      style={{ opacity: derived && !data.highlighted ? opacity * 0.8 : opacity }}
    >
      <path
        id={id}
        className="relationship-edge__path"
        d={edgePath}
        fill="none"
        markerEnd={markerEnd}
        stroke={data.color}
        strokeWidth={strokeWidth}
        strokeDasharray={derived ? "6 4" : undefined}
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

function useVisibleGraph(
  model: ArchModel | null,
  filterState: FilterState,
  searchTerm: string,
  directedPositions: Map<string, { x: number; y: number }> | null,
) {
  return useMemo(() => {
    if (!model) {
      return { nodes: [], edges: [], visibleElements: [] as ArchElement[] };
    }

    const { visibleElements, visibleRelations } = computeVisibleGraph(
      model,
      filterState,
      searchTerm,
    );

    const nodes = toFlowNodes(visibleElements).map((node) => {
      const position = directedPositions?.get(node.id);
      return position ? { ...node, position } : node;
    });
    const edges = toFlowEdges(visibleRelations, model.elementById).map((edge) => {
      const source = directedPositions?.get(edge.source);
      const target = directedPositions?.get(edge.target);
      // Upward edge: the target sits higher (smaller y) than the source. Route
      // it between the facing sides — out the source's top, into the target's
      // bottom. Otherwise (downward or same row) keep the default bottom→top.
      const upward = source && target && target.y < source.y;
      return upward
        ? { ...edge, sourceHandle: HANDLE.sourceTop, targetHandle: HANDLE.targetBottom }
        : { ...edge, sourceHandle: HANDLE.sourceBottom, targetHandle: HANDLE.targetTop };
    });

    return { nodes, edges, visibleElements };
  }, [model, filterState, searchTerm, directedPositions]);
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
            <dt>{key.charAt(0).toUpperCase() + key.slice(1)}</dt>
            <dd>{value}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}

function ArchitectureMapInner() {
  const { fitView } = useReactFlow();
  const src = useMemo(() => resolveSrc(), []);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterState, setFilterState] = useState<FilterState>(() => initialFilterState());
  const [activeViewId, setActiveViewId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => loadCollapsed(src));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [edgeTooltip, setEdgeTooltip] = useState<EdgeTooltipState | null>(null);
  const [directedPositions, setDirectedPositions] = useState<Map<
    string,
    { x: number; y: number }
  > | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadManifest(src)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setManifest(loaded);
        const storedId = loadActiveView(src);
        const initial =
          loaded.views.find((v) => v.id === storedId) ?? pickInitialView(loaded.views);
        if (initial) {
          setActiveViewId(initial.id);
          setFilterState(viewBaselineFilterState(initial));
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
  }, [src]);

  const model = useMemo(() => (manifest ? buildModel(manifest) : null), [manifest]);

  const activeView = useMemo<ViewDefinition | null>(
    () => manifest?.views.find((v) => v.id === activeViewId) ?? null,
    [manifest, activeViewId],
  );

  // The active view restricts the model to its scoped element set; the filter
  // rail and canvas then operate within that scope. With no active view yet
  // (manifest still loading its first view) the full model stands in.
  const scopedModel = useMemo<ArchModel | null>(() => {
    if (!model) {
      return null;
    }
    if (!manifest || !activeView) {
      return model;
    }
    const scope = resolveViewScope(activeView, model, manifest);
    const elements = model.elements.filter((el) => scope.has(el.id));
    const relations = model.relations.filter(
      (rel) => scope.has(rel.source) && scope.has(rel.target),
    );
    return {
      elements,
      relations,
      elementById: new Map(elements.map((el) => [el.id, el])),
    };
  }, [model, manifest, activeView]);

  const { nodes, edges, visibleElements } = useVisibleGraph(
    scopedModel,
    filterState,
    searchTerm,
    directedPositions,
  );

  const groups = useMemo(
    () => (scopedModel ? buildGroups(scopedModel, filterState, searchTerm) : []),
    [scopedModel, filterState, searchTerm],
  );

  const selectView = useCallback(
    (viewId: string) => {
      const view = manifest?.views.find((v) => v.id === viewId);
      if (!view) {
        return;
      }
      setActiveViewId(viewId);
      saveActiveView(src, viewId);
      setSearchTerm("");
      setFilterState(viewBaselineFilterState(view));
      setSelectedId(null);
    },
    [manifest, src],
  );

  useEffect(() => {
    if (!activeViewId) {
      return;
    }
    emitToParent({
      type: "view-change",
      view: activeViewId,
      filters: JSON.stringify({
        search: searchTerm,
        filters: serializeFilters(filterState),
      }),
    });
  }, [activeViewId, searchTerm, filterState]);

  useEffect(() => {
    return onSetView((viewId) => selectView(viewId));
  }, [selectView]);

  const toggleOption = useCallback((groupId: string, value: string) => {
    setFilterState((current) => toggleFilterOption(current, groupId, value));
  }, []);

  const selectAll = useCallback((groupId: string, values: string[]) => {
    setFilterState((current) => addFilterOptions(current, groupId, values));
  }, []);

  const toggleCollapse = useCallback(
    (groupId: string) => {
      setCollapsed((current) => {
        const next = { ...current, [groupId]: !current[groupId] };
        saveCollapsed(src, next);
        return next;
      });
    },
    [src],
  );

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
      if (node.id === selectedId) {
        return { ...node, zIndex: 20, data: { ...node.data, highlighted: true } };
      }
      if (connectedNodeIds.has(node.id)) {
        return node;
      }
      return { ...node, data: { ...node.data, dimmed: true } };
    });
  }, [nodes, connectedNodeIds, selectedId]);

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

  const clearFilters = useCallback(() => {
    setSearchTerm("");
    setFilterState(
      activeView ? viewBaselineFilterState(activeView) : initialFilterState(),
    );
  }, [activeView]);

  return (
    <div className="architecture-page">
      <section className="workspace">
        {model ? (
          <FilterRail
            groups={groups}
            filterState={filterState}
            collapsed={collapsed}
            searchTerm={searchTerm}
            onSearch={setSearchTerm}
            onToggleCollapse={toggleCollapse}
            onToggleOption={toggleOption}
            onSelectAll={selectAll}
            onClear={clearFilters}
          />
        ) : null}

        <div className="diagram-region" data-testid="architecture-diagram">
          {manifest && manifest.views.length > 0 ? (
            <ViewTabs
              views={manifest.views}
              activeViewId={activeViewId}
              onSelect={selectView}
            />
          ) : null}

          <div className="canvas-region">
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
              <Background gap={24} size={1} />
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
