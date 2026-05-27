import express, { type Router } from "express";
import yaml from "js-yaml";
import type { SchemaBundle } from "./schema-loader.js";
import { translateErrors, type TranslatedError } from "./error-translate.js";
import type { Metrics, ValidateOutcome } from "./metrics.js";

export interface ValidateOptions {
  bundle: SchemaBundle;
  /** Max body size in bytes. Defaults to 5 MiB per the spec. */
  bodyLimit?: number;
  /** Optional metrics sink. If absent, instrumentation is a no-op. */
  metrics?: Metrics;
}

const DEFAULT_LIMIT = 5 * 1024 * 1024;
const SUPPORTED_VERSIONS = new Set(["0.1"]);

/** Envelope-property → ArchiMate kind name (for the triple-matrix check). */
const KIND_BY_TOP_PROPERTY: Record<string, string> = {
  nodes: "Node",
  devices: "Device",
  systemSoftware: "SystemSoftware",
  applicationComponents: "ApplicationComponent",
  applicationServices: "ApplicationService",
  applicationInterfaces: "ApplicationInterface",
  technologyServices: "TechnologyService",
  technologyInterfaces: "TechnologyInterface",
  artifacts: "Artifact",
  capabilities: "Capability",
  businessServices: "BusinessService",
  groupings: "Grouping",
};

export function mountValidate(opts: ValidateOptions): Router {
  const router = express.Router();
  const limit = opts.bodyLimit ?? DEFAULT_LIMIT;

  // Single capture: accept anything we might validate, fall through to the
  // handler which decides what to do based on Content-Type. We do NOT register
  // express.json/text individually because we want a single 415 for unknown
  // types rather than silently empty bodies.
  router.post(
    "/api/validate",
    express.raw({ limit, type: () => true }),
    handle,
  );
  return router;

  function handle(req: express.Request, res: express.Response): void {
    const started = process.hrtime.bigint();
    let outcome: ValidateOutcome = "error";
    try {
      const ctype = (req.headers["content-type"] ?? "").split(";")[0]!.trim().toLowerCase();
      const raw = (req.body as Buffer | undefined) ?? Buffer.alloc(0);
      opts.metrics?.validateBodyBytes.observe(raw.length);

      let artifact: unknown;
      try {
        artifact = parseBody(raw, ctype);
      } catch (e) {
        if (e instanceof UnsupportedMediaTypeError) {
          outcome = "bad_request";
          res.status(415).json({ error: e.message });
          return;
        }
        if (e instanceof BadRequestError) {
          outcome = "bad_request";
          res.status(400).json({ error: e.message });
          return;
        }
        throw e;
      }

      const version = (artifact as { schemaVersion?: unknown })?.schemaVersion;
      if (typeof version !== "string") {
        outcome = "bad_request";
        res.status(400).json({ error: "artifact is missing required field 'schemaVersion'" });
        return;
      }
      if (!SUPPORTED_VERSIONS.has(version)) {
        outcome = "bad_request";
        res.status(400).json({
          error: `schemaVersion '${version}' is not supported by this service`,
          supported: [...SUPPORTED_VERSIONS],
        });
        return;
      }

      const ok = opts.bundle.artifactValidator(artifact);
      const schemaErrors = ok
        ? []
        : translateErrors(opts.bundle.artifactValidator.errors ?? [], artifact);
      const tripleErrors = checkRelationsTriples(artifact, opts.bundle);
      const all = [...schemaErrors, ...tripleErrors];

      outcome = all.length === 0 ? "valid" : "invalid";
      res.status(200).json({
        valid: all.length === 0,
        schemaVersion: version,
        ...(all.length > 0 ? { errors: all } : {}),
      });
    } finally {
      if (opts.metrics) {
        const elapsed = Number(process.hrtime.bigint() - started) / 1e9;
        opts.metrics.validateRequests.inc({ outcome });
        opts.metrics.validateDuration.observe({ outcome }, elapsed);
      }
    }
  }
}

class UnsupportedMediaTypeError extends Error {}
class BadRequestError extends Error {}

/**
 * js-yaml's default schema parses YAML 1.1 timestamps (e.g. `2024-07-12`)
 * into JS Date objects. JSON Schema's `format: date` / `format: date-time`
 * validates strings, so we round-trip Dates to their ISO form. Mirrors
 * tooling/validate.py's _normalize().
 */
function normalizeDates(value: unknown): unknown {
  if (value instanceof Date) {
    const iso = value.toISOString();
    // YAML dates without time (e.g. 2024-07-12) → js-yaml gives midnight UTC.
    // Recover the date-only form when the time component is exactly midnight.
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso;
  }
  if (Array.isArray(value)) return value.map(normalizeDates);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = normalizeDates(v);
    }
    return out;
  }
  return value;
}

function parseBody(raw: Buffer, ctype: string): unknown {
  if (ctype === "application/json") {
    if (raw.length === 0) {
      throw new BadRequestError("empty body");
    }
    try {
      return JSON.parse(raw.toString("utf8"));
    } catch (e) {
      throw new BadRequestError(`unparseable JSON: ${(e as Error).message}`);
    }
  }
  if (ctype === "application/yaml" || ctype === "text/yaml") {
    if (raw.length === 0) {
      throw new BadRequestError("empty body");
    }
    try {
      return normalizeDates(yaml.load(raw.toString("utf8")));
    } catch (e) {
      throw new BadRequestError(`unparseable YAML: ${(e as Error).message}`);
    }
  }
  throw new UnsupportedMediaTypeError(
    `Content-Type '${ctype || "(missing)"}' not supported; use application/json, application/yaml, or text/yaml`,
  );
}

function checkRelationsTriples(artifact: unknown, bundle: SchemaBundle): TranslatedError[] {
  if (!artifact || typeof artifact !== "object") return [];
  const env = artifact as Record<string, unknown>;
  const relations = env.relations;
  if (!Array.isArray(relations)) return [];

  // Build id → kind map from this artifact's own top-level element arrays.
  // Cross-producer references (ids not present locally) are skipped — the
  // collector enforces them at merge time.
  const kindById = new Map<string, string>();
  for (const [prop, kind] of Object.entries(KIND_BY_TOP_PROPERTY)) {
    const arr = env[prop];
    if (!Array.isArray(arr)) continue;
    for (const elt of arr) {
      const id = (elt as { id?: unknown }).id;
      if (typeof id === "string") kindById.set(id, kind);
    }
  }

  const errors: TranslatedError[] = [];
  relations.forEach((rel, i) => {
    if (!rel || typeof rel !== "object") return;
    const r = rel as { source?: unknown; target?: unknown; type?: unknown };
    if (typeof r.source !== "string" || typeof r.target !== "string" || typeof r.type !== "string") {
      return; // structural problem — ajv already reported it
    }
    const sourceKind = kindById.get(r.source);
    const targetKind = kindById.get(r.target);
    if (!sourceKind || !targetKind) return; // cross-producer; defer to collector
    if (!bundle.allowedTriples.has(sourceKind, r.type, targetKind)) {
      errors.push({
        path: `/relations/${i}`,
        keyword: "x-allowedTriples",
        message: `relation type '${r.type}' is not allowed between ${sourceKind} (source) and ${targetKind} (target)`,
        value: { source: r.source, type: r.type, target: r.target },
        schemaUrl:
          "https://architecture.webathome.org/schema/v0.1/generated/relations.schema.json",
        hint: "see x-allowedTriples in relations.schema.yaml for the permitted matrix",
      });
    }
  });
  return errors;
}
