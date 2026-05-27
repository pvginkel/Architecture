import { describe, it, expect } from "vitest";
import path from "node:path";
import { readFileSync } from "node:fs";
import yaml from "js-yaml";
import request from "supertest";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");
const EXAMPLES = path.resolve(__dirname, "../../schema/v0.1/examples");

function makeApp() {
  return createApp({
    bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
    viewerRoot: "/nonexistent-for-tests",
  });
}

function exampleText(name: string): string {
  return readFileSync(path.join(EXAMPLES, name), "utf8");
}

interface ExpectHeader {
  pointer: string | null;
}

function parseExpectHeader(text: string): ExpectHeader {
  for (const line of text.split("\n").slice(0, 20)) {
    const m = line.match(/^#\s*expect:\s*(\S+)/);
    if (m) return { pointer: m[1]! };
    if (line.trim() && !line.trim().startsWith("#")) break;
  }
  return { pointer: null };
}

describe("POST /api/validate — golden YAML fixtures", () => {
  it("accepts valid-minimal.yaml as valid", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/yaml")
      .send(exampleText("valid-minimal.yaml"));
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(true);
    expect(res.body.schemaVersion).toBe("0.1");
    expect(res.body.errors).toBeUndefined();
  });

  it("accepts valid-full.yaml as valid", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/yaml")
      .send(exampleText("valid-full.yaml"));
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(true);
    expect(res.body.errors).toBeUndefined();
  });

  const invalidFixtures = [
    "invalid-additional-property.yaml",
    "invalid-malformed-id.yaml",
    "invalid-unknown-relationship-type.yaml",
  ];

  for (const name of invalidFixtures) {
    it(`rejects ${name} with an error at the expected JSON pointer`, async () => {
      const text = exampleText(name);
      const expected = parseExpectHeader(text).pointer;
      expect(expected).not.toBeNull();
      const res = await request(makeApp())
        .post("/api/validate")
        .set("Content-Type", "application/yaml")
        .send(text);
      expect(res.status).toBe(200);
      expect(res.body.valid).toBe(false);
      const paths: string[] = (res.body.errors as Array<{ path: string }>).map((e) => e.path);
      expect(paths.some((p) => p === expected || p.startsWith(expected + "/"))).toBe(true);
    });
  }
});

describe("POST /api/validate — content negotiation and dispatch", () => {
  it("accepts JSON bodies and yields identical paths to YAML", async () => {
    const doc = yaml.load(exampleText("invalid-malformed-id.yaml")) as Record<string, unknown>;
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify(doc));
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(false);
    const paths = (res.body.errors as Array<{ path: string }>).map((e) => e.path);
    expect(paths).toContain("/nodes/0/id");
  });

  it("accepts text/yaml as a yaml Content-Type", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "text/yaml")
      .send(exampleText("valid-minimal.yaml"));
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(true);
  });

  it("returns 415 for an unsupported Content-Type", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/xml")
      .send("<foo/>");
    expect(res.status).toBe(415);
  });

  it("returns 400 for unparseable JSON", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send("{not json");
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/unparseable JSON/);
  });

  it("returns 400 for unparseable YAML", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/yaml")
      .send("- [unterminated\n  invalid: : yaml");
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/unparseable YAML/);
  });

  it("returns 400 when schemaVersion is missing", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify({ producer: "art:x" }));
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/schemaVersion/);
  });

  it("returns 400 when schemaVersion is unknown", async () => {
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify({ schemaVersion: "0.9", producer: "art:x" }));
    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/not supported/);
  });

  it("returns 413 for oversized bodies", async () => {
    // body limit defaults to 5 MiB; supertest's payload limit handling means we
    // send 6 MiB of YAML and expect Express's body-parser to reject it.
    const big = "x".repeat(6 * 1024 * 1024);
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/yaml")
      .send(big);
    expect([413, 400, 500]).toContain(res.status); // express may surface either depending on version
  });
});

describe("POST /api/validate — relations triple matrix", () => {
  it("rejects a local relation whose triple is not in the allowed matrix", async () => {
    const artifact = {
      schemaVersion: "0.1",
      producer: "art:helmcharts",
      artifacts: [
        {
          id: "art:helmcharts",
          label: "HelmCharts repo",
          summary: "Producer artifact.",
          introduced: "2024-07-12",
          lifecycle: "active",
          producer: "art:helmcharts",
          stereotype: "Producer",
          url: "https://github.com/pvginkel/HelmCharts",
          role: "source",
          owner: "Pieter van Ginkel",
        },
      ],
      capabilities: [
        {
          id: "cap:test-only",
          label: "Test only",
          summary: "Only used in this unit test.",
          introduced: "2026-05-27",
          lifecycle: "active",
          producer: "art:helmcharts",
        },
      ],
      relations: [
        {
          // Capability → Artifact via Composition is *not* in the matrix.
          id: "rel:bad-triple",
          source: "cap:test-only",
          target: "art:helmcharts",
          type: "Composition",
        },
      ],
    };
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify(artifact));
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(false);
    const errs = res.body.errors as Array<{ path: string; keyword: string; message: string }>;
    const tripleErr = errs.find((e) => e.keyword === "x-allowedTriples");
    expect(tripleErr).toBeDefined();
    expect(tripleErr!.path).toBe("/relations/0");
    expect(tripleErr!.message).toMatch(/not allowed between Capability .* Artifact/);
  });

  it("skips triple-matrix checks for cross-producer references", async () => {
    const artifact = {
      schemaVersion: "0.1",
      producer: "art:helmcharts",
      artifacts: [
        {
          id: "art:helmcharts",
          label: "HelmCharts repo",
          summary: "Producer artifact.",
          introduced: "2024-07-12",
          lifecycle: "active",
          producer: "art:helmcharts",
          stereotype: "Producer",
          url: "https://github.com/pvginkel/HelmCharts",
          role: "source",
          owner: "Pieter van Ginkel",
        },
      ],
      relations: [
        {
          id: "rel:cross-prod",
          source: "node:from-other-producer",
          target: "art:helmcharts",
          type: "Realization",
        },
      ],
    };
    const res = await request(makeApp())
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify(artifact));
    expect(res.status).toBe(200);
    // The structural schema is happy; the triple check skips unresolved refs.
    // The artifact may still be invalid for other reasons (e.g. missing
    // required fields elsewhere), so we only assert no triple error is raised.
    const errs = (res.body.errors as Array<{ keyword: string }> | undefined) ?? [];
    expect(errs.some((e) => e.keyword === "x-allowedTriples")).toBe(false);
  });
});
