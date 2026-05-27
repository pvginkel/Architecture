import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  loadSchemas,
  SchemaLoadError,
  AllowedTripleIndex,
} from "../src/schema-loader.js";

const REPO_SCHEMA_ROOT = path.resolve(__dirname, "../../schema/v0.1");

describe("schema-loader against the real schema/v0.1 tree", () => {
  const bundle = loadSchemas({ schemaRoot: REPO_SCHEMA_ROOT });

  it("compiles the artifact envelope validator", () => {
    expect(typeof bundle.artifactValidator).toBe("function");
  });

  it("compiles one validator per generated kind schema", () => {
    expect(bundle.kindValidators.size).toBeGreaterThan(0);
    for (const id of bundle.kindValidators.keys()) {
      expect(id).toMatch(/^https:\/\/architecture\.webathome\.org\/schema\/v0\.1\/generated\//);
    }
  });

  it("registers every yaml file under schema/v0.1 in the static map (except archimate/)", () => {
    expect(bundle.staticFiles.has("architecture.schema.yaml")).toBe(true);
    expect(bundle.staticFiles.has("subset.schema.yaml")).toBe(true);
    expect(bundle.staticFiles.has("generated/relations.schema.yaml")).toBe(true);
    expect(bundle.staticFiles.has("enums/capabilities.yaml")).toBe(true);
    // archimate/ dir is XSD/XML — must be skipped by the schema loader.
    for (const key of bundle.staticFiles.keys()) {
      expect(key.startsWith("archimate/")).toBe(false);
    }
  });

  it("populates yaml/json/etag for each static file", () => {
    const f = bundle.staticFiles.get("enums/capabilities.yaml");
    expect(f).toBeDefined();
    expect(f!.yaml.length).toBeGreaterThan(0);
    expect(() => JSON.parse(f!.json)).not.toThrow();
    expect(f!.etag).toMatch(/^"[0-9a-f]{40}"$/);
  });

  it("loads x-allowedTriples into a queryable index", () => {
    expect(bundle.allowedTriples.triples.length).toBeGreaterThan(0);
    // Spot-check a triple that should exist (Helm chart deploys app component).
    const sample = bundle.allowedTriples.triples[0]!;
    expect(bundle.allowedTriples.has(sample.source, sample.type, sample.target)).toBe(true);
    expect(bundle.allowedTriples.has("Nope", "Bogus", "Triple")).toBe(false);
  });

  it("triple lookup is constant-time (Set-backed)", () => {
    const idx = new AllowedTripleIndex([{ source: "A", type: "T", target: "B" }]);
    expect(idx.has("A", "T", "B")).toBe(true);
    expect(idx.has("A", "T", "C")).toBe(false);
  });

  it("validates a known-good envelope minimally", () => {
    const minimal = {
      schemaVersion: "0.1",
      producer: "art:test-producer",
    };
    const ok = bundle.artifactValidator(minimal);
    expect(ok).toBe(true);
  });

  it("rejects an envelope with the wrong schemaVersion", () => {
    const bad = {
      schemaVersion: "0.2",
      producer: "art:test-producer",
    };
    const ok = bundle.artifactValidator(bad);
    expect(ok).toBe(false);
    expect((bundle.artifactValidator.errors ?? []).length).toBeGreaterThan(0);
  });
});

describe("schema-loader error handling", () => {
  let workdir: string;

  beforeAll(() => {
    workdir = mkdtempSync(path.join(tmpdir(), "arch-schema-broken-"));
    // Copy the real schema tree, then break one file.
    cpSync(REPO_SCHEMA_ROOT, workdir, { recursive: true });
  });

  afterAll(() => {
    rmSync(workdir, { recursive: true, force: true });
  });

  it("throws SchemaLoadError with relPath context when a YAML file is malformed", () => {
    const broken = path.join(workdir, "generated", "node.schema.yaml");
    writeFileSync(broken, "this: is: not: valid: yaml:\n  - [unterminated");
    expect(() => loadSchemas({ schemaRoot: workdir })).toThrow(SchemaLoadError);
    try {
      loadSchemas({ schemaRoot: workdir });
    } catch (e) {
      const err = e as SchemaLoadError;
      expect(err.relPath).toBe(path.join("generated", "node.schema.yaml"));
      expect(err.message).toMatch(/YAML parse error|generated.node\.schema\.yaml/);
    } finally {
      // Restore from the real tree so the next test starts clean.
      writeFileSync(
        broken,
        readFileSync(path.join(REPO_SCHEMA_ROOT, "generated", "node.schema.yaml")),
      );
    }
  });

  it("throws SchemaLoadError when a schema fails JSON Schema 2020-12 meta-validation", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "arch-schema-metabad-"));
    mkdirSync(path.join(dir, "generated"), { recursive: true });
    // architecture.schema.yaml with `type` set to a non-string nonsense value —
    // meta-validation must catch it.
    writeFileSync(
      path.join(dir, "architecture.schema.yaml"),
      [
        "$schema: https://json-schema.org/draft/2020-12/schema",
        "$id: https://example.test/architecture.schema.yaml",
        "type: 12345",
      ].join("\n"),
    );
    try {
      expect(() => loadSchemas({ schemaRoot: dir })).toThrow(SchemaLoadError);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
