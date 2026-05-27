import { describe, it, expect } from "vitest";
import path from "node:path";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import { loadSchemas } from "../src/schema-loader.js";
import { translateErrors, extractByPointer } from "../src/error-translate.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");
const EXAMPLES = path.resolve(__dirname, "../../schema/v0.1/examples");

const bundle = loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT });

function loadExample(name: string): unknown {
  const text = readFileSync(path.join(EXAMPLES, name), "utf8");
  return yaml.load(text);
}

function validateAndTranslate(name: string) {
  const doc = loadExample(name);
  const ok = bundle.artifactValidator(doc);
  expect(ok).toBe(false);
  return translateErrors(bundle.artifactValidator.errors ?? [], doc);
}

describe("translateErrors against the v0.1 golden invalid fixtures", () => {
  it("additional-property: points at /nodes/0 with a useful hint", () => {
    const errs = validateAndTranslate("invalid-additional-property.yaml");
    const e = errs.find((x) => x.path === "/nodes/0");
    expect(e).toBeDefined();
    expect(e!.keyword).toBe("additionalProperties");
    expect(e!.message).toMatch(/unknown property/);
    expect(e!.schemaUrl).toBe(
      "https://architecture.webathome.org/schema/v0.1/generated/node.schema.json",
    );
  });

  it("malformed-id: pattern error on /nodes/0/id", () => {
    const errs = validateAndTranslate("invalid-malformed-id.yaml");
    const e = errs.find((x) => x.path === "/nodes/0/id");
    expect(e).toBeDefined();
    expect(e!.keyword).toBe("pattern");
    expect(e!.value).toBeTruthy();
    expect(e!.schemaUrl).toBe(
      "https://architecture.webathome.org/schema/v0.1/generated/node.schema.json",
    );
  });

  it("unknown-relationship-type: enum error on /relations/0/type", () => {
    const errs = validateAndTranslate("invalid-unknown-relationship-type.yaml");
    const e = errs.find((x) => x.path === "/relations/0/type");
    expect(e).toBeDefined();
    expect(e!.keyword).toBe("enum");
    expect(e!.message).toMatch(/not in the allowed enumeration/);
    expect(e!.hint).toMatch(/allowed:/);
    expect(e!.schemaUrl).toBe(
      "https://architecture.webathome.org/schema/v0.1/generated/relations.schema.json",
    );
  });

  // v3 removed the lifecycle conditional rules and `replacedBy` attribute,
  // so the cascade-dedup tests that targeted those error shapes are gone.
  // Cascade-dedup is still exercised through the per-keyword translators
  // below.
});

describe("per-keyword translators", () => {
  function makeErr(keyword: string, params: Record<string, unknown>, opts: { instancePath?: string; schemaPath?: string; message?: string } = {}) {
    return {
      keyword,
      params,
      instancePath: opts.instancePath ?? "",
      schemaPath: opts.schemaPath ?? "#",
      message: opts.message,
      schema: undefined,
      data: undefined,
    } as any;
  }

  it("type", () => {
    const out = translateErrors([makeErr("type", { type: "string" }, { instancePath: "/x" })], { x: 42 });
    expect(out[0]!.message).toMatch(/not of expected type string/);
  });

  it("const", () => {
    const out = translateErrors(
      [makeErr("const", { allowedValue: "0.1" }, { instancePath: "/schemaVersion" })],
      { schemaVersion: "0.2" },
    );
    expect(out[0]!.message).toMatch(/must equal/);
  });

  it("format", () => {
    const out = translateErrors(
      [makeErr("format", { format: "date" }, { instancePath: "/introduced" })],
      { introduced: "not-a-date" },
    );
    expect(out[0]!.message).toMatch(/not a valid date/);
  });

  it("minLength", () => {
    const out = translateErrors(
      [makeErr("minLength", { limit: 1 }, { instancePath: "/label" })],
      { label: "" },
    );
    expect(out[0]!.message).toMatch(/too short/);
  });

  it("uniqueItems", () => {
    const out = translateErrors(
      [makeErr("uniqueItems", { i: 2, j: 1 }, { instancePath: "/list" })],
      { list: [1, 2, 2] },
    );
    expect(out[0]!.message).toMatch(/positions 1 and 2 are duplicates/);
  });

  it("enum hint points to the capabilities enum for cap: ids", () => {
    const out = translateErrors(
      [makeErr("enum", { allowedValues: ["cap:iam"] }, { instancePath: "/x" })],
      { x: "cap:sso-v2" },
    );
    expect(out[0]!.schemaUrl).toBe(
      "https://architecture.webathome.org/schema/v0.1/enums/capabilities.json",
    );
  });
});

describe("extractByPointer", () => {
  const doc = {
    nodes: [{ id: "node:a", label: "A" }],
    s: "hello",
    "weird/key": 1,
  };

  it("returns the root for empty pointer", () => {
    expect(extractByPointer(doc, "")).toBe(doc);
  });

  it("walks object keys", () => {
    expect(extractByPointer(doc, "/s")).toBe("hello");
  });

  it("walks array indices", () => {
    expect(extractByPointer(doc, "/nodes/0/id")).toBe("node:a");
  });

  it("decodes ~1 as /", () => {
    expect(extractByPointer(doc, "/weird~1key")).toBe(1);
  });

  it("returns undefined for missing segments", () => {
    expect(extractByPointer(doc, "/nodes/9/id")).toBeUndefined();
    expect(extractByPointer(doc, "/missing")).toBeUndefined();
  });
});
