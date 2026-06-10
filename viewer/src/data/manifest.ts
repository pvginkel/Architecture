// Types and loader for the federated ArchiMate manifest the viewer consumes.
//
// The manifest is produced by tooling/collect.py (assemble_merged_dataset) and
// served CORS-open at /data/v0.1/architecture.json. The viewer can consume any
// conformant manifest via ?src=<url>; ours is the default.

import type {
  EnvironmentId,
  LifecycleState,
  RelationshipType,
} from "../generated/vocab";

// One interface for every element kind. The JSON is loose enough that a single
// shape with the union of optional per-kind attributes is simpler than eleven
// near-identical interfaces; the element's kind is carried by which array it
// lives in (see model.ts), not by a discriminant field on the element.
export interface ManifestElement {
  id: string;
  label: string;
  summary: string;
  introduced: string;
  lifecycle: LifecycleState;
  producer: string;
  retirementBy?: string;
  // Per-kind attributes (present only on the kinds that declare them).
  environment?: EnvironmentId;
  cluster?: string;
  stereotype?: string;
  homepage?: string;
  logo?: string;
  sourceRepository?: string;
  stats?: Record<string, string>;
}

// ArchiMate Access direction: which end of the edge the open arrow sits on,
// i.e. whether the active element reads from, writes to, or both, the data
// object. Absent => Write (the Archi default), drawn as a target arrow.
export type AccessType = "Read" | "Write" | "ReadWrite" | "Unspecified";

export interface ManifestRelation {
  id: string;
  source: string;
  target: string;
  type: RelationshipType;
  boundBy?: string;
  boundByDefaultValue?: string;
  // ArchiMate notation refinements, optional on the relevant relation types
  // (ignored on others). `directed` turns a plain Association into a directed
  // one (open arrow at the target); `accessType` places the Access arrow per
  // read/write semantics. See theme.ts RELATIONSHIP_STYLE.
  directed?: boolean;
  accessType?: AccessType;
  // Set by the viewer's render-time derivation engine (views/derive.ts) on the
  // synthetic relationships it bridges between visible nodes across hidden ones.
  // Drawn in grey to read as inferred. Not a wire field — absent on every
  // relation in the manifest, which are all asserted.
  derived?: boolean;
  // On a derived relation: the hidden interior nodes the bridge spans, in chain
  // order. "Expand derived path" reveals them. Absent on asserted relations.
  via?: string[];
  // On a derived relation: the asserted edge ids forming that path (one more than
  // `via`). Used to highlight exactly the path on expand. Absent on asserted.
  viaEdges?: string[];
}

export interface ManifestDerived {
  groupings: Record<string, string[]>;
  capabilityRealizations: Record<string, string[]>;
}

// A view's attribute selector. Within a field the values OR; across fields they
// AND. An absent/empty predicate matches every element (the Everything view).
export interface ViewPredicate {
  layers?: string[];
  kinds?: string[];
  producers?: string[];
  capabilities?: string[];
  lifecycle?: string[];
  environments?: string[];
  releases?: string[];
}

// A curated view, authored as YAML in the Architecture repo and inlined into
// the manifest by the collector. See src/views/scope.ts for resolution.
export interface ViewDefinition {
  id: string;
  label: string;
  description: string;
  // Lucide icon name (PascalCase, as exported by lucide-react), resolved to a
  // glyph on the view tab. See ViewTabs.
  icon: string;
  predicate?: ViewPredicate;
  include?: string[];
  exclude?: string[];
  excludeInstances?: boolean;
  excludeKinds?: string[];
  excludeProducers?: string[];
  neighbourDepth?: number;
  defaultEnvironment?: string;
}

export interface Manifest {
  schemaVersion: string;
  producers: string[];
  nodes: ManifestElement[];
  devices: ManifestElement[];
  systemSoftware: ManifestElement[];
  applicationComponents: ManifestElement[];
  applicationServices: ManifestElement[];
  applicationInterfaces: ManifestElement[];
  technologyServices: ManifestElement[];
  technologyInterfaces: ManifestElement[];
  capabilities: ManifestElement[];
  businessServices: ManifestElement[];
  groupings: ManifestElement[];
  relations: ManifestRelation[];
  derived: ManifestDerived;
  views: ViewDefinition[];
}

/**
 * Resolve the manifest URL. `?src=` wins when present. In dev we default to the
 * dev server's /dev/architecture.json endpoint (see vite.config.ts), which is
 * the live production manifest with its views replaced by the ones authored in
 * this checkout — so dev always shows current data against the views being
 * edited. (`?src=sample-architecture.json` falls back to the committed static
 * sample when offline.) In a production build the viewer is served at /viewer/
 * and the manifest at /data/v0.1/ — the BASE_URL-relative path normalises to
 * /data/v0.1/.
 */
export function resolveSrc(): string {
  const param = new URLSearchParams(window.location.search).get("src");
  if (param) {
    return param;
  }
  if (import.meta.env.DEV) {
    return "/dev/architecture.json";
  }
  return `${import.meta.env.BASE_URL}../data/v0.1/architecture.json`;
}

/**
 * Fetch and parse a manifest. No error swallowing — a failed fetch or bad JSON
 * throws, and the app shell surfaces it as a visible error panel.
 */
export async function loadManifest(src: string): Promise<Manifest> {
  const res = await fetch(src);
  if (!res.ok) {
    throw new Error(`Failed to load manifest from ${src}: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as Manifest;
}
