import { describe, it, expect } from "vitest";
import path from "node:path";
import request from "supertest";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";
import { createMetrics } from "../src/metrics.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");

function makeApp() {
  const metrics = createMetrics();
  const app = createApp({
    bundle: loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT }),
    viewerRoot: "/nonexistent",
    metrics,
  });
  return { app, metrics };
}

describe("GET /metrics", () => {
  it("returns Prometheus exposition with default + custom metrics", async () => {
    const { app } = makeApp();
    const res = await request(app).get("/metrics");
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toMatch(/^text\/plain/);
    // Custom counters/histograms are present even before any sample.
    expect(res.text).toContain("arch_validate_requests_total");
    expect(res.text).toContain("arch_validate_duration_seconds");
    expect(res.text).toContain("arch_validate_body_bytes");
    expect(res.text).toContain("arch_schema_load_errors_total");
    // Default Node metrics are present.
    expect(res.text).toMatch(/process_cpu_user_seconds_total|nodejs_eventloop_lag_seconds/);
  });

  it("increments arch_validate_requests_total with outcome=valid on a valid call", async () => {
    const { app } = makeApp();
    await request(app)
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify({ schemaVersion: "0.1", producer: "x" }));
    const m = await request(app).get("/metrics");
    expect(m.text).toMatch(/arch_validate_requests_total\{outcome="valid"\}\s+1/);
  });

  it("increments outcome=invalid on a validation failure", async () => {
    const { app } = makeApp();
    await request(app)
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify({ schemaVersion: "0.1" })); // missing 'producer'
    const m = await request(app).get("/metrics");
    expect(m.text).toMatch(/arch_validate_requests_total\{outcome="invalid"\}\s+1/);
  });

  it("increments outcome=bad_request on a 4xx", async () => {
    const { app } = makeApp();
    await request(app)
      .post("/api/validate")
      .set("Content-Type", "application/xml")
      .send("<x/>");
    const m = await request(app).get("/metrics");
    expect(m.text).toMatch(/arch_validate_requests_total\{outcome="bad_request"\}\s+1/);
  });

  it("observes body bytes histogram with a non-zero sum after a request", async () => {
    const { app } = makeApp();
    await request(app)
      .post("/api/validate")
      .set("Content-Type", "application/json")
      .send(JSON.stringify({ schemaVersion: "0.1", producer: "x" }));
    const m = await request(app).get("/metrics");
    expect(m.text).toMatch(/arch_validate_body_bytes_sum\s+\d+/);
    expect(m.text).toMatch(/arch_validate_body_bytes_count\s+1/);
  });
});
