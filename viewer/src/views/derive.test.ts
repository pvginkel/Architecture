import { describe, expect, it, vi } from "vitest";
import { deriveBridges, MAX_HIDDEN_HOPS } from "./derive";
import { KIND_TO_LAYER, type ElementKind, type RelationshipType } from "../generated/vocab";
import type { ArchElement, ArchModel } from "../data/model";
import type { ManifestRelation } from "../data/manifest";

function el(id: string, kind: ElementKind, instance = false): ArchElement {
  return {
    id,
    label: id,
    summary: "",
    introduced: "2024-01-01",
    lifecycle: "active",
    producer: "test",
    kind,
    layer: KIND_TO_LAYER[kind],
    isInstance: instance,
  } as ArchElement;
}

function rel(source: string, type: RelationshipType, target: string): ManifestRelation {
  return { id: `${source}~${type}~${target}`, source, target, type };
}

function model(elements: ArchElement[], relations: ManifestRelation[]): ArchModel {
  return { elements, relations, elementById: new Map(elements.map((e) => [e.id, e])) };
}

describe("deriveBridges", () => {
  it("reproduces the instance→definition projection (the old collect-time edge)", () => {
    // DefA ←Spec— InstA —Serving→ InstB —Spec→ DefB, with only the definitions
    // visible, derives DefA —Serving→ DefB (PDR3 then PDR4, both promoted).
    const m = model(
      [
        el("defA", "ApplicationComponent"),
        el("defB", "ApplicationComponent"),
        el("instA", "ApplicationComponent", true),
        el("instB", "ApplicationComponent", true),
      ],
      [
        rel("instA", "Specialization", "defA"),
        rel("instB", "Specialization", "defB"),
        rel("instA", "Serving", "instB"),
      ],
    );
    const out = deriveBridges(m, new Set(["defA", "defB"]));
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      source: "defA",
      target: "defB",
      type: "Serving",
      derived: true,
      confidence: "valid",
    });
    // `via` records the hidden instances the bridge spans, for "Expand path".
    expect([...out[0].via].sort()).toEqual(["instA", "instB"]);
  });

  it("keeps a definition→definition Specialization chain merely potential (dropped at the valid floor)", () => {
    // X —Spec→ Z —Serving→ Y, all definitions: X inherits Z's Serving (PDR1),
    // but with no instance→definition step there is no promotion.
    const m = model(
      [
        el("x", "ApplicationComponent"),
        el("y", "ApplicationComponent"),
        el("z", "ApplicationComponent"),
      ],
      [rel("x", "Specialization", "z"), rel("z", "Serving", "y")],
    );
    const visible = new Set(["x", "y"]);
    expect(deriveBridges(m, visible)).toHaveLength(0);

    const surfaced = deriveBridges(m, visible, "potential");
    expect(surfaced).toHaveLength(1);
    expect(surfaced[0]).toMatchObject({
      source: "x",
      target: "y",
      type: "Serving",
      confidence: "potential",
    });
  });

  it("folds a multi-hop structural chain to its weakest type (DR2 fixpoint)", () => {
    // A =Composition⇒ h1 =Composition⇒ h2 =Aggregation⇒ B  ⟹  A =Aggregation⇒ B.
    const m = model(
      [
        el("a", "ApplicationComponent"),
        el("b", "ApplicationComponent"),
        el("h1", "ApplicationComponent"),
        el("h2", "ApplicationComponent"),
      ],
      [
        rel("a", "Composition", "h1"),
        rel("h1", "Composition", "h2"),
        rel("h2", "Aggregation", "b"),
      ],
    );
    const out = deriveBridges(m, new Set(["a", "b"]));
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ source: "a", target: "b", type: "Aggregation" });
  });

  it("suppresses a derived triple the metamodel forbids", () => {
    // capDef =Composition⇒ h —Serving→ appDef would derive a
    // Capability —Serving→ ApplicationComponent edge, which is not an allowed
    // triple, so nothing is emitted.
    const m = model(
      [
        el("capDef", "Capability"),
        el("appDef", "ApplicationComponent"),
        el("h", "Capability"),
      ],
      [rel("capDef", "Composition", "h"), rel("h", "Serving", "appDef")],
    );
    expect(deriveBridges(m, new Set(["capDef", "appDef"]))).toHaveLength(0);
  });

  it("does not re-derive an asserted relationship already on canvas", () => {
    const m = model(
      [
        el("defA", "ApplicationComponent"),
        el("defB", "ApplicationComponent"),
        el("instA", "ApplicationComponent", true),
        el("instB", "ApplicationComponent", true),
      ],
      [
        rel("instA", "Specialization", "defA"),
        rel("instB", "Specialization", "defB"),
        rel("instA", "Serving", "instB"),
        rel("defA", "Serving", "defB"), // the same edge, asserted
      ],
    );
    expect(deriveBridges(m, new Set(["defA", "defB"]))).toHaveLength(0);
  });

  it("returns nothing when no node is hidden (e.g. the Everything view)", () => {
    const m = model(
      [el("a", "ApplicationComponent"), el("b", "ApplicationComponent")],
      [rel("a", "Serving", "b")],
    );
    expect(deriveBridges(m, new Set(["a", "b"]))).toHaveLength(0);
  });

  it("drops (and reports) a path with more than MAX_HIDDEN_HOPS hidden nodes", () => {
    // A — h1 — h2 — … — h(cap+1) — B: too many hidden interior nodes to bridge.
    const hidden = Array.from({ length: MAX_HIDDEN_HOPS + 1 }, (_, i) => `h${i}`);
    const chain = ["a", ...hidden, "b"];
    const relations: ManifestRelation[] = [];
    for (let i = 0; i < chain.length - 1; i++) {
      relations.push(rel(chain[i], "Composition", chain[i + 1]));
    }
    const elements = [
      el("a", "ApplicationComponent"),
      el("b", "ApplicationComponent"),
      ...hidden.map((id) => el(id, "ApplicationComponent")),
    ];
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const out = deriveBridges(model(elements, relations), new Set(["a", "b"]));
    expect(out).toHaveLength(0);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("MAX_HIDDEN_HOPS"));
    warn.mockRestore();
  });
});
