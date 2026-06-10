// Presentation theme, typed against the generated vocab so tsc enforces
// completeness: a missing kind/layer/capability — or a stale key not in the
// union — fails the build. There is no runtime "default icon" path; runtime
// skew (data newer than the build) is handled loudly in the node card.

import {
  Activity,
  AppWindow,
  Archive,
  Box,
  Boxes,
  Briefcase,
  Clapperboard,
  Cog,
  Container,
  Cpu,
  Database,
  DoorOpen,
  Eye,
  FileJson,
  Folders,
  GitBranch,
  Globe,
  Group,
  HardDrive,
  HeartPulse,
  House,
  Inbox,
  KeyRound,
  LockKeyhole,
  Map,
  Monitor,
  Network,
  Package,
  Plug,
  Radio,
  Rocket,
  Scale,
  ScanLine,
  ScrollText,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Waypoints,
  Workflow,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type {
  CapabilityId,
  ElementKind,
  LayerId,
  RelationshipType,
} from "./generated/vocab";

// ArchiMate-layer accents, re-saturated for the light theme/site (--panel
// #fbfbf8). Fed into the node card's existing --node-accent / color-mix.
export const LAYER_ACCENT: Record<LayerId, string> = {
  technology: "#5b8c5a",
  application: "#4f7cac",
  strategy: "#c2703d",
  business: "#c9a227",
  "cross-cutting": "#7c7f86",
};

// Kind glyph (left icon), one per ArchiMate kind.
export const KIND_ICON: Record<ElementKind, LucideIcon> = {
  Node: Server,
  Device: Cpu,
  SystemSoftware: Boxes,
  ApplicationComponent: Box,
  ApplicationService: Workflow,
  ApplicationInterface: Plug,
  TechnologyService: Cog,
  TechnologyInterface: Plug,
  Capability: Sparkles,
  BusinessService: Briefcase,
  Grouping: Group,
};

// Generic icon per capability, used only as the right-image fallback when an
// element that realizes a capability has no logo.
export const CAPABILITY_ICON: Record<CapabilityId, LucideIcon> = {
  "cap:iam": KeyRound,
  "cap:secrets-management": LockKeyhole,
  "cap:pki": ShieldCheck,
  "cap:ingress": DoorOpen,
  "cap:load-balancing": Scale,
  "cap:high-availability": HeartPulse,
  "cap:dns": Globe,
  "cap:dhcp": Network,
  "cap:relational-database": Database,
  "cap:document-store": FileJson,
  "cap:vector-store": Boxes,
  "cap:full-text-search": Search,
  "cap:cache": Zap,
  "cap:message-queue": Inbox,
  "cap:pub-sub-broker": Radio,
  "cap:object-storage": Archive,
  "cap:shared-filesystem": Folders,
  "cap:block-storage": HardDrive,
  "cap:metrics": Activity,
  "cap:logging": ScrollText,
  "cap:observability": Eye,
  "cap:container-orchestration": Container,
  "cap:hypervisor": Server,
  "cap:image-registry": Package,
  "cap:source-control": GitBranch,
  "cap:continuous-integration": Workflow,
  "cap:configuration-management": SlidersHorizontal,
  "cap:remote-access": Monitor,
  "cap:vpn": Waypoints,
  "cap:media-streaming": Clapperboard,
  "cap:home-automation": House,
  "cap:iot-device": Cpu,
  "cap:mcp": Plug,
};

// ---------- ArchiMate relationship notation ----------
//
// Standard ArchiMate line styling: per relationship type, a line dash pattern
// plus an endpoint decoration at the source and/or target. Transcribed from the
// Archi editor's connection figures (see tmp/archimate-line-rules.json). Typed
// `Record<RelationshipType, …>` so a relationship type with no entry fails tsc —
// the same guardrail as CAPABILITY_ICON (see CLAUDE.md).
//
// The endpoint decorations are drawn as shared SVG markers; the RelationshipEdge
// component (ArchitectureMap) resolves a decoration + the edge's layer colour to
// a marker id (see edgeMarkerId) and the marker set is emitted once by
// EdgeMarkerDefs.

export type EdgeDecoration =
  | "filledArrow" // solid triangle (Triggering, Flow, Assignment target)
  | "openArrow" // open V (Serving, Access, Influence, directed Association)
  | "hollowTriangle" // open generalization/realization head
  | "filledDiamond" // Composition source
  | "hollowDiamond" // Aggregation source
  | "ball"; // Assignment source

export interface RelationshipStyle {
  // stroke-dasharray; undefined = solid line.
  dash?: string;
  // Decoration at the source / target endpoint; undefined = none.
  source?: EdgeDecoration;
  target?: EdgeDecoration;
}

// Dotted (Archi setLineDash([2])) and dashed ([6,3]) at base width. Fixed user
// units — close enough at our stroke widths; not scaled per stroke.
const DOTTED = "2 2";
const DASHED = "6 3";

export const RELATIONSHIP_STYLE: Record<RelationshipType, RelationshipStyle> = {
  Composition: { source: "filledDiamond" },
  Aggregation: { source: "hollowDiamond" },
  Assignment: { source: "ball", target: "filledArrow" },
  Realization: { dash: DOTTED, target: "hollowTriangle" },
  Serving: { target: "openArrow" },
  // Access: dotted; the arrow placement is dynamic on accessType (default Write
  // = target arrow). RelationshipEdge overrides source/target per accessType.
  Access: { dash: DOTTED, target: "openArrow" },
  Influence: { dash: DASHED, target: "openArrow" },
  Triggering: { target: "filledArrow" },
  Flow: { dash: DASHED, target: "filledArrow" },
  Specialization: { target: "hollowTriangle" },
  // Association: undirected by default (no decoration). RelationshipEdge adds a
  // target openArrow when relation.directed is set.
  Association: {},
  // Junctions are n-ary nodes, not pairwise edges; if one rides as an edge we
  // draw it plain rather than inventing a decoration (see line-rules $junctions).
  AndJunction: {},
  OrJunction: {},
};

/** Whether a decoration's fill is the line colour (needs a colour-matched
 *  marker) or a hollow white centre with a coloured stroke. */
export const DECORATION_HOLLOW: Record<EdgeDecoration, boolean> = {
  filledArrow: false,
  openArrow: false, // open = stroke only, but still colour-keyed (the V is the line colour)
  hollowTriangle: true,
  filledDiamond: false,
  hollowDiamond: true,
  ball: false,
};

export const EDGE_DECORATIONS: EdgeDecoration[] = [
  "filledArrow",
  "openArrow",
  "hollowTriangle",
  "filledDiamond",
  "hollowDiamond",
  "ball",
];

// The fallback edge colour toFlowEdge uses when a relation's source layer can't
// be resolved (model.ts). Markers are pre-generated for every layer accent plus
// this, so any edge colour has a matching marker.
export const EDGE_FALLBACK_COLOR = "#9aa09a";

/** Every colour an edge (and therefore a marker) can take: the layer accents
 *  plus the fallback. Deduped, stable order. */
export const EDGE_MARKER_COLORS: string[] = [
  ...new Set([...Object.values(LAYER_ACCENT), EDGE_FALLBACK_COLOR]),
];

/** Sanitise a colour to an id-safe token (`#5b8c5a` → `5b8c5a`). */
function colorToken(color: string): string {
  return color.replace(/[^a-zA-Z0-9]/g, "");
}

/** Id of the shared SVG marker for a decoration at a given edge colour. Used
 *  both when emitting the marker defs and when referencing them on an edge. */
export function edgeMarkerId(decoration: EdgeDecoration, color: string): string {
  return `am-${decoration}-${colorToken(color)}`;
}

// View-tab glyphs, keyed by the `icon` name a view declares in its YAML. The
// map doubles as the allow-list: a view may only name an icon imported here, so
// the tab-strip's icon set stays explicit and tree-shaken (no full-registry
// import). Adding an icon to a view = add it here. ViewTabs throws on a name not
// in this map, matching the no-default-glyph stance above.
export const VIEW_ICON: Record<string, LucideIcon> = {
  Map,
  Rocket,
  Network,
  AppWindow,
  KeyRound,
  Database,
  House,
  Cpu,
  Sparkles,
  Radio,
  ScanLine,
  Globe,
};
