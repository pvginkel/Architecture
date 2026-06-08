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

export interface ManifestRelation {
  id: string;
  source: string;
  target: string;
  type: RelationshipType;
  boundBy?: string;
  boundByDefaultValue?: string;
  // Set by the collector on relations it synthesised by projecting an
  // instance-level edge onto its definition. Rendered as an inferred (dashed)
  // edge. Absent on authored relations.
  derived?: boolean;
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
