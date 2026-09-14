import { describe, expect, it } from "vitest";
import { resolveViewScope } from "./scope";
import { KIND_TO_LAYER, type ElementKind, type RelationshipType } from "../generated/vocab";
import type { ArchElement, ArchModel } from "../data/model";
import type { Manifest, ManifestRelation, ViewDefinition } from "../data/manifest";

function el(id: string, kind: ElementKind): ArchElement {
  return {
    id,
    label: id,
    summary: "",
    introduced: "2024-01-01",
    lifecycle: "active",
    producer: "test",
    kind,
    layer: KIND_TO_LAYER[kind],
    isInstance: false,
  } as ArchElement;
}

function rel(source: string, type: RelationshipType, target: string): ManifestRelation {
  return { id: `${source}~${type}~${target}`, source, target, type };
}

// server ←Serving— filter ←Serving— jenkins —Serving→ bot: the view anchors the
// server, depth 1 reaches the filter, and jenkins sits one hop past the edge
// with a neighbour (bot) of its own that the view has no business showing.
const MODEL: ArchModel = (() => {
  const elements = [
    el("app:server", "ApplicationComponent"),
    el("app:filter", "ApplicationComponent"),
    el("ss:jenkins,1", "SystemSoftware"),
    el("app:bot", "ApplicationComponent"),
  ];
  return {
    elements,
    relations: [
      rel("app:filter", "Serving", "app:server"),
      rel("ss:jenkins,1", "Serving", "app:filter"),
      rel("ss:jenkins,1", "Serving", "app:bot"),
    ],
    elementById: new Map(elements.map((e) => [e.id, e])),
  };
})();

const MANIFEST = { derived: { capabilityRealizations: {} } } as unknown as Manifest;

function view(fields: Partial<ViewDefinition>): ViewDefinition {
  return { id: "v", label: "V", description: "", icon: "Map", ...fields };
}

function scope(fields: Partial<ViewDefinition>): string[] {
  return [...resolveViewScope(view(fields), MODEL, MANIFEST)].sort();
}

describe("resolveViewScope", () => {
  it("expands from an include, pulling in the included element's own neighbours", () => {
    expect(scope({ include: ["app:server", "/^ss:jenkins,/"], neighbourDepth: 1 })).toEqual(
      ["app:bot", "app:filter", "app:server", "ss:jenkins,1"],
    );
  });

  it("adds includeUnexpanded after the expansion, without its neighbours", () => {
    expect(
      scope({ include: ["app:server"], includeUnexpanded: ["/^ss:jenkins,/"], neighbourDepth: 1 }),
    ).toEqual(["app:filter", "app:server", "ss:jenkins,1"]);
  });

  it("resolves a literal includeUnexpanded id", () => {
    expect(scope({ include: ["app:server"], includeUnexpanded: ["ss:jenkins,1"] })).toEqual([
      "app:server",
      "ss:jenkins,1",
    ]);
  });

  it("keeps includeUnexpanded past exclude and the universe gates", () => {
    expect(
      scope({
        include: ["app:server"],
        includeUnexpanded: ["ss:jenkins,1"],
        exclude: ["ss:jenkins,1"],
        excludeKinds: ["SystemSoftware"],
        neighbourDepth: 1,
      }),
    ).toEqual(["app:filter", "app:server", "ss:jenkins,1"]);
  });
});
