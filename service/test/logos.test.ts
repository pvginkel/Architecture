import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import request from "supertest";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");

// A minimal valid PNG (1x1 transparent) — enough bytes to round-trip.
const PNG_BYTES = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010806000000" +
    "1f15c4890000000a49444154789c6360000002000100ffff0300000600" +
    "05fef7d4 a90000000049454e44ae426082".replace(/\s+/g, ""),
  "hex",
);
const SVG_BYTES = Buffer.from("<svg xmlns='http://www.w3.org/2000/svg'/>", "utf8");

let viewerRoot: string;

beforeAll(() => {
  viewerRoot = mkdtempSync(path.join(tmpdir(), "arch-logos-"));
  mkdirSync(path.join(viewerRoot, "logos"), { recursive: true });
  writeFileSync(path.join(viewerRoot, "logos", "keycloak.svg"), SVG_BYTES);
  writeFileSync(path.join(viewerRoot, "logos", "calico.png"), PNG_BYTES);
  // Non-logo files must be ignored by the stem scan.
  writeFileSync(path.join(viewerRoot, "logos", "titles.json"), "{}");
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

describe("GET /api/logo", () => {
  it("serves a known SVG with the right content-type, cache header, and exact bytes", async () => {
    const res = await request(makeApp())
      .get("/api/logo")
      .query({ name: "keycloak" })
      .buffer(true)
      .parse((r, cb) => {
        const chunks: Buffer[] = [];
        r.on("data", (c: Buffer) => chunks.push(c));
        r.on("end", () => cb(null, Buffer.concat(chunks)));
      });
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("image/svg+xml");
    expect(res.headers["cache-control"]).toBe("public, max-age=86400");
    expect(Buffer.from(res.body).equals(SVG_BYTES)).toBe(true);
  });

  it("serves a known PNG with the right content-type and round-trips its bytes", async () => {
    const res = await request(makeApp())
      .get("/api/logo")
      .query({ name: "calico" })
      .buffer(true)
      .parse((r, cb) => {
        const chunks: Buffer[] = [];
        r.on("data", (c: Buffer) => chunks.push(c));
        r.on("end", () => cb(null, Buffer.concat(chunks)));
      });
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("image/png");
    expect(Buffer.from(res.body).equals(PNG_BYTES)).toBe(true);
  });

  it("404s for an unknown name", async () => {
    const res = await request(makeApp()).get("/api/logo").query({ name: "does-not-exist" });
    expect(res.status).toBe(404);
  });

  it("404s for the non-logo titles.json stem (only .svg/.png are logos)", async () => {
    const res = await request(makeApp()).get("/api/logo").query({ name: "titles" });
    expect(res.status).toBe(404);
  });

  it("404s for a path-traversal attempt rather than escaping the logos dir", async () => {
    const traversal = await request(makeApp())
      .get("/api/logo")
      .query({ name: "../../etc/passwd" });
    expect(traversal.status).toBe(404);

    const sibling = await request(makeApp()).get("/api/logo").query({ name: "../index" });
    expect(sibling.status).toBe(404);
  });

  it("404s when name is omitted", async () => {
    const res = await request(makeApp()).get("/api/logo");
    expect(res.status).toBe(404);
  });

  it("404s when name is coerced to a non-string array/object query value", async () => {
    // Express's query parser turns name[]=… into an array and name[x]=… into an
    // object; the `typeof name !== "string"` guard must fall through to 404, not
    // crash or mis-resolve.
    const asArray = await request(makeApp())
      .get("/api/logo")
      .query({ "name[]": "keycloak" });
    expect(asArray.status).toBe(404);

    const asObject = await request(makeApp())
      .get("/api/logo")
      .query({ "name[x]": "keycloak" });
    expect(asObject.status).toBe(404);
  });

  it("fails loudly (non-2xx) when a stem collides across both extensions", async () => {
    // Use an isolated viewerRoot so the ambiguous stem doesn't pollute the
    // shared fixture used by the other tests.
    const dupRoot = mkdtempSync(path.join(tmpdir(), "arch-logos-dup-"));
    mkdirSync(path.join(dupRoot, "logos"), { recursive: true });
    writeFileSync(path.join(dupRoot, "logos", "dup.svg"), SVG_BYTES);
    writeFileSync(path.join(dupRoot, "logos", "dup.png"), PNG_BYTES);
    try {
      const app = createApp({
        bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
        viewerRoot: dupRoot,
        dataRoot: "/nonexistent",
      });
      const res = await request(app).get("/api/logo").query({ name: "dup" });
      expect(res.status).not.toBeLessThan(500);
    } finally {
      rmSync(dupRoot, { recursive: true, force: true });
    }
  });
});
