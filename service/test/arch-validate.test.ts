import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { createServer, type Server } from "node:http";
import { createApp } from "../src/app.js";
import { loadSchemas } from "../src/schema-loader.js";

const exec = promisify(execFile);

const REPO_ROOT = path.resolve(__dirname, "../..");
const SCRIPT = path.join(REPO_ROOT, "scripts", "arch-validate");
const EXAMPLES = path.join(REPO_ROOT, "schema", "v0.1", "examples");

let server: Server;
let url: string;

beforeAll(async () => {
  const app = createApp({
    bundle: loadSchemas({ schemaRoot: path.join(REPO_ROOT, "schema", "v0.1") }),
    viewerRoot: "/nonexistent",
  });
  server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const addr = server.address();
  if (!addr || typeof addr === "string") throw new Error("listen() returned unexpected address");
  url = `http://127.0.0.1:${addr.port}/api/validate`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

async function run(args: string[], opts: { input?: string } = {}) {
  if (opts.input !== undefined) {
    return runWithStdin(args, opts.input, url);
  }
  try {
    const { stdout, stderr } = await exec(SCRIPT, args, {
      env: { ...process.env, ARCHITECTURE_VALIDATE_URL: url, NO_COLOR: "1" },
    });
    return { code: 0, stdout, stderr };
  } catch (e) {
    const err = e as { code?: number; stdout?: string; stderr?: string };
    return { code: err.code ?? -1, stdout: err.stdout ?? "", stderr: err.stderr ?? "" };
  }
}

function runWithStdin(args: string[], input: string, endpoint: string): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(SCRIPT, args, {
      env: { ...process.env, ARCHITECTURE_VALIDATE_URL: endpoint, NO_COLOR: "1" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (b) => (stdout += b.toString()));
    child.stderr.on("data", (b) => (stderr += b.toString()));
    child.on("close", (code) => resolve({ code: code ?? -1, stdout, stderr }));
    child.stdin.end(input);
  });
}

describe("scripts/arch-validate", () => {
  it("exits 0 on a valid YAML artifact", async () => {
    const r = await run([path.join(EXAMPLES, "valid-minimal.yaml")]);
    expect(r.code).toBe(0);
    expect(r.stderr).toMatch(/✓.*valid-minimal\.yaml/);
  });

  it("exits 1 on an invalid YAML artifact and prints the JSON pointer", async () => {
    const r = await run([path.join(EXAMPLES, "invalid-malformed-id.yaml")]);
    expect(r.code).toBe(1);
    expect(r.stderr).toContain("/nodes/0/id");
    expect(r.stderr).toMatch(/✗/);
  });

  it("validates JSON when extension is .json", async () => {
    // Minimal valid JSON artifact (date as 'YYYY-MM-DD' string, matching the
    // `format: date` constraint without going through js-yaml's Date parsing).
    const doc = { schemaVersion: "0.1", producer: "art:x" };
    const tmp = path.join(REPO_ROOT, "service", `.tmp-${Date.now()}.json`);
    const fs = await import("node:fs/promises");
    await fs.writeFile(tmp, JSON.stringify(doc));
    try {
      const r = await run([tmp]);
      expect(r.code).toBe(0);
    } finally {
      await fs.unlink(tmp);
    }
  });

  it("aggregates multi-file failures: exit 1 if any one is invalid", async () => {
    const r = await run([
      path.join(EXAMPLES, "valid-minimal.yaml"),
      path.join(EXAMPLES, "invalid-additional-property.yaml"),
    ]);
    expect(r.code).toBe(1);
    expect(r.stderr).toMatch(/✓.*valid-minimal/);
    expect(r.stderr).toMatch(/✗.*invalid-additional-property/);
  });

  it("reads from stdin with '-'", async () => {
    const valid = await import("node:fs/promises").then((m) =>
      m.readFile(path.join(EXAMPLES, "valid-minimal.yaml"), "utf8"),
    );
    const r = await run(["-"], { input: valid });
    expect(r.code).toBe(0);
    expect(r.stderr).toMatch(/<stdin>/);
  });

  it("--json emits the raw endpoint response on stdout", async () => {
    const r = await run(["--json", path.join(EXAMPLES, "invalid-malformed-id.yaml")]);
    expect(r.code).toBe(1);
    const doc = JSON.parse(r.stdout);
    expect(doc.valid).toBe(false);
    expect(doc.errors[0].path).toBe("/nodes/0/id");
  });

  it("--quiet suppresses OK lines but still prints failures", async () => {
    const r = await run([
      "--quiet",
      path.join(EXAMPLES, "valid-minimal.yaml"),
      path.join(EXAMPLES, "invalid-additional-property.yaml"),
    ]);
    expect(r.code).toBe(1);
    expect(r.stderr).not.toMatch(/✓/);
    expect(r.stderr).toMatch(/✗/);
  });

  it("--format yaml overrides extension detection", async () => {
    // Send YAML body with a misleading .json extension but format override.
    const valid = await import("node:fs/promises").then((m) =>
      m.readFile(path.join(EXAMPLES, "valid-minimal.yaml"), "utf8"),
    );
    const tmp = path.join(REPO_ROOT, "service", `.tmp-${Date.now()}.json`);
    const fs = await import("node:fs/promises");
    await fs.writeFile(tmp, valid);
    try {
      const r = await run(["--format", "yaml", tmp]);
      expect(r.code).toBe(0);
    } finally {
      await fs.unlink(tmp);
    }
  });

  it("exits 2 on transport error (endpoint unreachable)", async () => {
    const r = await runWithUrl("http://127.0.0.1:1/api/validate", [
      path.join(EXAMPLES, "valid-minimal.yaml"),
    ]);
    expect(r.code).toBe(2);
    expect(r.stderr).toMatch(/transport error/);
  });
});

async function runWithUrl(altUrl: string, args: string[]) {
  try {
    const { stdout, stderr } = await exec(SCRIPT, args, {
      env: { ...process.env, ARCHITECTURE_VALIDATE_URL: altUrl, NO_COLOR: "1" },
    });
    return { code: 0, stdout, stderr };
  } catch (e) {
    const err = e as { code?: number; stdout?: string; stderr?: string };
    return { code: err.code ?? -1, stdout: err.stdout ?? "", stderr: err.stderr ?? "" };
  }
}
