import { describe, it, expect } from "vitest";
import { sourceLocator } from "../src/source-locate.js";

const TEXT = [
  "schemaVersion: \"0.1\"", // 1
  "devices:", // 2
  "  - id: a", // 3
  "    stats:", // 4
  "      firmware: 9e10234", // 5
  "      a/b~c: x", // 6
  "  - &second", // 7
  "    id: b", // 8
  "notes: |", // 9
  "  first line", // 10
  "  second line", // 11
  "alias: *second", // 12
  "long: " + "y".repeat(80), // 13
].join("\n");

describe("sourceLocator", () => {
  const locate = sourceLocator(TEXT);

  it("puts a mapping value on its key's line and keeps the scalar as written", () => {
    expect(locate("/devices/0/stats/firmware")).toEqual({
      line: 5,
      scalar: { source: "9e10234", key: "firmware" },
    });
  });

  it("locates a mapping-valued key on the key's line, with no scalar", () => {
    expect(locate("/devices/0/stats")).toEqual({ line: 4 });
  });

  it("locates a sequence item on the item's first line", () => {
    expect(locate("/devices/0")).toEqual({ line: 3 });
    expect(locate("/devices/1")).toEqual({ line: 8 });
  });

  it("unescapes ~1 and ~0 in pointer segments", () => {
    expect(locate("/devices/0/stats/a~1b~0c")?.line).toBe(6);
  });

  it("follows an alias to its anchored node", () => {
    expect(locate("/alias/id")).toEqual({ line: 8, scalar: { source: "b", key: "id" } });
  });

  it("locates the root", () => {
    expect(locate("")).toEqual({ line: 1 });
  });

  it("shortens a multi-line or long scalar to its first line", () => {
    expect(locate("/notes")?.scalar?.source).toBe("|…");
    expect(locate("/long")?.scalar?.source).toBe(`${"y".repeat(57)}…`);
  });

  it("returns undefined for a pointer that does not map", () => {
    expect(locate("/devices/7")).toBeUndefined();
    expect(locate("/devices/x")).toBeUndefined();
    expect(locate("/missing")).toBeUndefined();
    expect(locate("/schemaVersion/deeper")).toBeUndefined();
  });

  it("locates in a JSON body", () => {
    const json = sourceLocator('{\n  "nodes": [\n    {"id": 1e5}\n  ]\n}');
    expect(json("/nodes/0/id")).toEqual({ line: 3, scalar: { source: "1e5", key: "id" } });
  });
});
