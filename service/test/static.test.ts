import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import request from "supertest";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");

let viewerRoot: string;

beforeAll(() => {
  viewerRoot = mkdtempSync(path.join(tmpdir(), "arch-viewer-"));
  mkdirSync(path.join(viewerRoot, "assets"), { recursive: true });
  mkdirSync(path.join(viewerRoot, "logos"), { recursive: true });
  writeFileSync(path.join(viewerRoot, "index.html"), "<!doctype html><title>viewer</title>");
  writeFileSync(path.join(viewerRoot, "assets", "app.123abc.js"), "console.log('app');");
  writeFileSync(path.join(viewerRoot, "logos", "thing.svg"), "<svg/>");
});

afterAll(() => {
  rmSync(viewerRoot, { recursive: true, force: true });
});

function makeApp() {
  return createApp({
    bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
    viewerRoot,
    dataRoot: "/nonexistent",
  });
}

describe("viewer static handler", () => {
  it("serves index.html at /viewer/ with no-cache and CSP", async () => {
    const res = await request(makeApp()).get("/viewer/");
    expect(res.status).toBe(200);
    expect(res.text).toContain("viewer");
    expect(res.headers["cache-control"]).toBe("no-cache");
    expect(res.headers["content-security-policy"]).toContain("frame-ancestors");
    expect(res.headers["content-security-policy"]).toContain("https://webathome.org");
  });

  it("serves fingerprinted assets with the immutable long-cache header", async () => {
    const res = await request(makeApp()).get("/viewer/assets/app.123abc.js");
    expect(res.status).toBe(200);
    expect(res.headers["cache-control"]).toBe("public, max-age=31536000, immutable");
    expect(res.headers["content-security-policy"]).toContain("frame-ancestors");
  });

  it("serves logos with the short-cache header", async () => {
    const res = await request(makeApp()).get("/viewer/logos/thing.svg");
    expect(res.status).toBe(200);
    expect(res.headers["cache-control"]).toBe("public, max-age=86400");
  });

  it("SPA-falls-back any unknown /viewer/* to index.html", async () => {
    const res = await request(makeApp()).get("/viewer/something/that/does/not/exist");
    expect(res.status).toBe(200);
    expect(res.text).toContain("viewer");
    expect(res.headers["content-security-policy"]).toContain("frame-ancestors");
  });
});

describe("schema static handler", () => {
  it("serves the envelope yaml at /schema/v0.1/architecture.schema.yaml", async () => {
    const res = await request(makeApp()).get("/schema/v0.1/architecture.schema.yaml");
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("application/yaml");
    expect(res.headers["cache-control"]).toBe("public, max-age=300");
    expect(res.headers["access-control-allow-origin"]).toBe("*");
    expect(res.headers["etag"]).toMatch(/^"[0-9a-f]{40}"$/);
    expect(res.text).toContain("Architecture artifact (v0.1)");
  });

  it("serves the canonical json sibling at /schema/v0.1/architecture.schema.json", async () => {
    const res = await request(makeApp()).get("/schema/v0.1/architecture.schema.json");
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("application/schema+json");
    expect(() => JSON.parse(res.text)).not.toThrow();
    const doc = JSON.parse(res.text);
    expect(doc.$id).toBe(
      "https://architecture.webathome.org/schema/v0.1/architecture.schema.yaml",
    );
  });

  it("serves each generated kind schema in yaml and json", async () => {
    const yaml = await request(makeApp()).get("/schema/v0.1/generated/node.schema.yaml");
    expect(yaml.status).toBe(200);
    expect(yaml.headers["content-type"]).toContain("application/yaml");
    const json = await request(makeApp()).get("/schema/v0.1/generated/node.schema.json");
    expect(json.status).toBe(200);
    const doc = JSON.parse(json.text);
    expect(doc.title).toBe("Node (ArchiMate Node)");
  });

  it("serves enum files (yaml and json sibling)", async () => {
    const yaml = await request(makeApp()).get("/schema/v0.1/enums/capabilities.yaml");
    expect(yaml.status).toBe(200);
    expect(yaml.text).toContain("cap:iam");
    const json = await request(makeApp()).get("/schema/v0.1/enums/capabilities.json");
    expect(json.status).toBe(200);
    const doc = JSON.parse(json.text);
    expect(doc.entries.length).toBeGreaterThan(0);
  });

  it("serves vendored ArchiMate XSD as XML", async () => {
    const res = await request(makeApp()).get("/schema/v0.1/archimate/archimate3_Model.xsd");
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("application/xml");
    expect(res.headers["cache-control"]).toBe("public, max-age=300");
    expect(res.headers["access-control-allow-origin"]).toBe("*");
  });

  it("returns 404 for an unknown schema path", async () => {
    const res = await request(makeApp()).get("/schema/v0.1/nope.yaml");
    expect(res.status).toBe(404);
  });
});

describe("data static handler", () => {
  it("serves a populated dataRoot at /data/v0.1/architecture.yaml", async () => {
    const dataRoot = path.resolve(__dirname, "../../tmp-test-data-static");
    const fs = await import("node:fs");
    fs.mkdirSync(path.join(dataRoot, "v0.1"), { recursive: true });
    fs.writeFileSync(
      path.join(dataRoot, "v0.1", "architecture.yaml"),
      "schemaVersion: '0.1'\n",
    );
    try {
      const app = createApp({
        bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
        viewerRoot,
        dataRoot,
      });
      const res = await request(app).get("/data/v0.1/architecture.yaml");
      expect(res.status).toBe(200);
      expect(res.headers["content-type"]).toContain("application/yaml");
      expect(res.headers["access-control-allow-origin"]).toBe("*");
      expect(res.text).toContain("schemaVersion");
    } finally {
      fs.rmSync(dataRoot, { recursive: true, force: true });
    }
  });

  it("returns 404 when the merged dataset is not yet bundled (v2 stub)", async () => {
    const res = await request(makeApp()).get("/data/v0.1/architecture.yaml");
    expect(res.status).toBe(404);
  });
});
