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
import type { CapabilityId, ElementKind, LayerId } from "./generated/vocab";

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
};

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
  Sparkles,
  ScanLine,
  Globe,
};
