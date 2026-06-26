#!/usr/bin/env tsx
/**
 * Cognitive complexity analyzer CLI.
 *
 * Scans Python and TypeScript files, computes per-function cognitive
 * complexity using the SonarSource algorithm, and outputs JSON.
 *
 * Usage:
 *   npx tsx index.ts <paths...> [--threshold N]
 *
 * Paths can be files or directories. Directories are scanned recursively
 * for .py, .ts, and .tsx files.
 */

import { readdirSync, statSync } from "node:fs";
import { extname, resolve } from "node:path";
import { analyzePythonFile } from "./python.js";
import { analyzeTypeScriptFile } from "./typescript.js";
import type { FileResult } from "./types.js";

// ── File collection ─────────────────────────────────────────────────────

const PYTHON_EXTS = new Set([".py"]);
const TS_EXTS = new Set([".ts", ".tsx"]);
const ALL_EXTS = new Set([...PYTHON_EXTS, ...TS_EXTS]);

function collectFiles(paths: string[]): string[] {
  const files: string[] = [];

  for (const p of paths) {
    const abs = resolve(p);
    const stat = statSync(abs, { throwIfNoEntry: false });
    if (!stat) continue;

    if (stat.isFile() && ALL_EXTS.has(extname(abs))) {
      files.push(abs);
    } else if (stat.isDirectory()) {
      walkDir(abs, files);
    }
  }

  return files.sort();
}

function walkDir(dir: string, out: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    // Skip common non-source directories
    if (
      entry.name === "node_modules" ||
      entry.name === "__pycache__" ||
      entry.name === ".git" ||
      entry.name === "dist" ||
      entry.name === "coverage" ||
      entry.name === ".venv" ||
      entry.name === "alembic"
    ) {
      continue;
    }

    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      walkDir(full, out);
    } else if (entry.isFile() && ALL_EXTS.has(extname(entry.name))) {
      // Skip generated files
      if (entry.name.includes(".gen.") || full.includes("/generated/")) {
        continue;
      }
      out.push(full);
    }
  }
}

// ── Main ────────────────────────────────────────────────────────────────

function main(): void {
  const args = process.argv.slice(2);
  let threshold = 0;
  const paths: string[] = [];

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--threshold" && i + 1 < args.length) {
      threshold = parseInt(args[++i], 10);
    } else if (args[i] === "--help" || args[i] === "-h") {
      console.error(
        "Usage: npx tsx index.ts <paths...> [--threshold N]",
      );
      process.exit(0);
    } else {
      paths.push(args[i]);
    }
  }

  if (paths.length === 0) {
    console.error("Error: no paths provided");
    process.exit(1);
  }

  const files = collectFiles(paths);
  const results: FileResult[] = [];

  for (const filePath of files) {
    const ext = extname(filePath);
    const isPython = PYTHON_EXTS.has(ext);
    const isTs = TS_EXTS.has(ext);

    const functions = isPython
      ? analyzePythonFile(filePath)
      : isTs
        ? analyzeTypeScriptFile(filePath)
        : [];

    // Apply threshold filter
    const filtered = threshold > 0
      ? functions.filter((f) => f.complexity >= threshold)
      : functions;

    if (filtered.length > 0) {
      results.push({
        file: filePath,
        language: isPython ? "python" : "typescript",
        functions: filtered,
      });
    }
  }

  console.log(JSON.stringify(results, null, 2));
}

main();
