import { describe, it, expect } from "vitest";
import path from "node:path";
import request from "supertest";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");
const REPO_USAGE = path.resolve(__dirname, "../../USAGE.md");

function makeApp() {
  return createApp({
    bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
    viewerRoot: "/nonexistent",
    usagePath: REPO_USAGE,
  });
}

describe("GET / (rendered USAGE.md)", () => {
  it("returns HTML", async () => {
    const res = await request(makeApp()).get("/");
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toMatch(/^text\/html/);
    expect(res.text.startsWith("<!doctype html>")).toBe(true);
  });

  it("includes the top-level USAGE.md heading", async () => {
    const res = await request(makeApp()).get("/");
    expect(res.text).toMatch(/<h1[^>]*>Architecture validation service<\/h1>/);
  });

  it("renders code blocks and tables", async () => {
    const res = await request(makeApp()).get("/");
    expect(res.text).toContain("<pre>");
    expect(res.text).toContain("<table>");
  });

  it("inlines the stylesheet (no external assets)", async () => {
    const res = await request(makeApp()).get("/");
    expect(res.text).toContain("<style>");
    // No external scripts or stylesheets.
    expect(res.text).not.toMatch(/<link\s+rel=["']stylesheet/);
    expect(res.text).not.toMatch(/<script\s/);
  });

  it("falls back gracefully when USAGE.md is missing", async () => {
    const app = createApp({
      bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
      viewerRoot: "/nonexistent",
      usagePath: "/does/not/exist/USAGE.md",
    });
    const res = await request(app).get("/");
    expect(res.status).toBe(200);
    expect(res.text).toContain("not bundled in this image");
  });
});
