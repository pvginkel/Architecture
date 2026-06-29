import { describe, expect, it } from "vitest";
import {
  computeExpandedVisibleGraph,
  defaultRelationshipSelection,
  RELATIONSHIP_GROUP,
  type FilterState,
} from "./state";
import { KIND_TO_LAYER, type ElementKind, type RelationshipType } from "../generated/vocab";
import type { ArchElement, ArchModel } from "../data/model";
import type { ManifestRelation } from "../data/manifest";

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

function model(elements: ArchElement[], relations: ManifestRelation[]): ArchModel {
  return { elements, relations, elementById: new Map(elements.map((e) => [e.id, e])) };
}

describe("computeExpandedVisibleGraph revealed bypass", () => {
  // TS-02-01: the "Expand derived path" reveal must still surface the interior
  // (revealed) nodes and the asserted edges linking them, including a type the
  // view otherwise hides (Association). Proves the asserted revealed-node bypass
  // at state.ts:264-277 is intact and was NOT removed by the Task 1 derived
  // filter (which deliberately has NO revealed bypass).
  it("still surfaces revealed interior nodes and their asserted hidden-type edges via the revealed bypass", () => {
    // Visible scope is just `a`; i1/i2 are interior nodes of an expanded path,
    // linked to each other by an asserted Association (a hidden type).
    const m = model(
      [
        el("a", "ApplicationComponent"),
        el("i1", "ApplicationComponent"),
        el("i2", "ApplicationComponent"),
      ],
      [
        rel("a", "Composition", "i1"),
        rel("i1", "Association", "i2"),
      ],
    );
    const scoped = model([el("a", "ApplicationComponent")], []);

    // Relationship selection hides Association (the default baseline).
    const filterState: FilterState = new Map([
      [RELATIONSHIP_GROUP, defaultRelationshipSelection()],
    ]);
    expect((filterState.get(RELATIONSHIP_GROUP) as Set<string>).has("Association")).toBe(false);

    const revealedIds = new Set(["i1", "i2"]);
    const { visibleElements, visibleRelations } = computeExpandedVisibleGraph(
      m,
      scoped,
      filterState,
      "",
      new Map(),
      null,
      revealedIds,
    );

    const visibleIds = new Set(visibleElements.map((e) => e.id));
    // The revealed interior nodes are present despite being outside scope.
    expect(visibleIds.has("i1")).toBe(true);
    expect(visibleIds.has("i2")).toBe(true);

    // The asserted Association edge linking the two revealed nodes survives even
    // though Association is hidden — the revealed bypass keeps the path connected.
    expect(
      visibleRelations.some(
        (r) => r.source === "i1" && r.target === "i2" && r.type === "Association",
      ),
    ).toBe(true);
  });
});
