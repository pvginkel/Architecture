import { Counter, Histogram, Registry, collectDefaultMetrics } from "prom-client";
import type { RequestHandler, Router } from "express";
import express from "express";

export type ValidateOutcome = "valid" | "invalid" | "bad_request" | "error";

export interface Metrics {
  registry: Registry;
  validateRequests: Counter<"outcome">;
  validateDuration: Histogram<"outcome">;
  validateBodyBytes: Histogram<string>;
  schemaLoadErrors: Counter<string>;
}

export function createMetrics(): Metrics {
  const registry = new Registry();
  collectDefaultMetrics({ register: registry });

  const validateRequests = new Counter({
    name: "arch_validate_requests_total",
    help: "Total POST /api/validate calls by outcome.",
    labelNames: ["outcome"] as const,
    registers: [registry],
  });

  const validateDuration = new Histogram({
    name: "arch_validate_duration_seconds",
    help: "Time spent handling POST /api/validate (seconds), by outcome.",
    labelNames: ["outcome"] as const,
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    registers: [registry],
  });

  const validateBodyBytes = new Histogram({
    name: "arch_validate_body_bytes",
    help: "Size of submitted artifact bodies (bytes).",
    buckets: [256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304],
    registers: [registry],
  });

  const schemaLoadErrors = new Counter({
    name: "arch_schema_load_errors_total",
    help: "Schema files that failed to parse or meta-validate at startup.",
    registers: [registry],
  });

  return { registry, validateRequests, validateDuration, validateBodyBytes, schemaLoadErrors };
}

export function mountMetrics(metrics: Metrics): Router {
  const router = express.Router();
  router.get("/metrics", (async (_req, res) => {
    res.setHeader("Content-Type", metrics.registry.contentType);
    res.send(await metrics.registry.metrics());
  }) as RequestHandler);
  return router;
}
