/**
 * Cognitive complexity analyzer for Python files.
 *
 * Uses indentation-based parsing — reliable for Python since whitespace
 * is syntactically significant. Implements the SonarSource cognitive
 * complexity algorithm:
 *
 *   - Structural increment (+1):        if, elif, else, for, while,
 *                                        except, match, case, break, continue
 *   - Nesting increment (+nesting):     if, for, while, except, match
 *                                        (NOT elif, else, case, finally)
 *   - Nesting increases for bodies of:  if, elif, else, for, while,
 *                                        except, try, match, case, nested def
 *   - Logical operator sequences:       +1 per type change in and/or chains
 */

import { readFileSync } from "node:fs";
import type { FunctionComplexity } from "./types.js";

// ── Pattern detection ───────────────────────────────────────────────────

const DEF_RE = /^(\s*)(async\s+)?def\s+(\w+)\s*\(/;

/** Keywords that get +1 AND +nesting (full increment). */
const FULL_INCREMENT = new Set(["if", "for", "while", "except", "match"]);

/** Keywords that get +1 only (structural, no nesting penalty). */
const STRUCT_ONLY = new Set(["elif", "else", "case"]);

/** Keywords whose body increases nesting but that get no complexity increment. */
const NESTING_ONLY = new Set(["try"]);

/** Keywords that get no increment and don't change nesting. */
const NO_INCREMENT = new Set(["finally"]);

/**
 * Extract the leading keyword from a line (after indentation).
 * Returns [indent, keyword] or null.
 */
function detectKeyword(
  line: string,
): { indent: number; keyword: string } | null {
  const m = line.match(
    /^(\s*)(if|elif|else|for|while|try|except|finally|match|case|with|async\s+for|async\s+with)\b/,
  );
  if (!m) return null;

  let keyword = m[2];
  // Normalize async variants
  if (keyword === "async for") keyword = "for";
  if (keyword === "async with") keyword = "with";

  // `with` is a context manager, not control flow — skip it
  if (keyword === "with") return null;

  // Verify the line ends with `:` (possibly after a comment) for block starters.
  // This avoids matching `if` in `x = value if cond else other` (inline if).
  if (["if", "for", "while", "match"].includes(keyword)) {
    const stripped = line.replace(/#.*$/, "").trimEnd();
    if (!stripped.endsWith(":") && !stripped.endsWith(":\\")) return null;
  }

  return { indent: m[1].length, keyword };
}

/**
 * Count logical operator complexity on a single line.
 * +1 for each switch between `and`/`or` operator types.
 */
function countLogicalOperators(line: string): number {
  // Strip string literals (rough) to avoid matching inside strings
  const cleaned = line
    .replace(/"""[\s\S]*?"""/g, '""')
    .replace(/'''[\s\S]*?'''/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''");

  let complexity = 0;
  let lastOp: string | null = null;

  // Match word-boundary `and` / `or`
  const re = /\b(and|or)\b/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(cleaned)) !== null) {
    const op = match[1];
    if (op !== lastOp) {
      complexity++;
      lastOp = op;
    }
  }
  return complexity;
}

// ── Function boundary detection ─────────────────────────────────────────

interface FunctionRange {
  name: string;
  line: number; // 1-indexed
  defIndent: number;
  bodyStart: number; // 0-indexed, inclusive
  bodyEnd: number; // 0-indexed, exclusive
  childSpans: [number, number][]; // nested function body spans to skip
}

function isBlankOrComment(line: string): boolean {
  const t = line.trim();
  return t === "" || t.startsWith("#");
}

function getIndent(line: string): number {
  const m = line.match(/^(\s*)/);
  return m ? m[1].length : 0;
}

function findFunctions(lines: string[]): FunctionRange[] {
  // Pass 1: find all def/async def declarations
  const defs: { name: string; line: number; indent: number }[] = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(DEF_RE);
    if (m) {
      defs.push({ name: m[3], line: i, indent: m[1].length });
    }
  }

  // Pass 2: determine body ranges
  const functions: FunctionRange[] = [];

  for (const def of defs) {
    // Skip past the function signature (may span multiple lines).
    // The signature ends at the line containing the closing `:`.
    let sigEnd = def.line;
    const defLine = lines[def.line];
    // Check if signature is complete on the def line itself
    const sigComplete = /:\s*(#.*)?$/.test(defLine.replace(/#.*$/, "").trimEnd());
    if (!sigComplete) {
      // Multi-line signature — scan forward for the closing `)...:`
      sigEnd++;
      while (sigEnd < lines.length) {
        const stripped = lines[sigEnd].replace(/#.*$/, "").trimEnd();
        if (stripped.endsWith(":")) break;
        sigEnd++;
      }
    }

    // Body starts at the first non-blank line after the signature with
    // indentation greater than the def line
    let bodyStart = sigEnd + 1;
    while (bodyStart < lines.length) {
      if (
        !isBlankOrComment(lines[bodyStart]) &&
        getIndent(lines[bodyStart]) > def.indent
      ) {
        break;
      }
      if (
        !isBlankOrComment(lines[bodyStart]) &&
        getIndent(lines[bodyStart]) <= def.indent
      ) {
        bodyStart = sigEnd + 1; // empty body
        break;
      }
      bodyStart++;
    }

    // Find body end: first non-blank line with indent <= def.indent after body
    let bodyEnd = bodyStart;
    while (bodyEnd < lines.length) {
      if (
        !isBlankOrComment(lines[bodyEnd]) &&
        getIndent(lines[bodyEnd]) <= def.indent
      ) {
        break;
      }
      bodyEnd++;
    }

    functions.push({
      name: def.name,
      line: def.line + 1,
      defIndent: def.indent,
      bodyStart,
      bodyEnd,
      childSpans: [],
    });
  }

  // Pass 3: mark nested function body spans on parents
  for (let i = 0; i < functions.length; i++) {
    const parent = functions[i];
    for (let j = i + 1; j < functions.length; j++) {
      const child = functions[j];
      if (
        child.bodyStart >= parent.bodyStart &&
        child.bodyEnd <= parent.bodyEnd &&
        child.defIndent > parent.defIndent
      ) {
        // child.line - 1 = 0-indexed def line; include the def line in the skip span
        // so we don't process the nested def as a keyword
        parent.childSpans.push([child.bodyStart, child.bodyEnd]);
      }
    }
  }

  return functions;
}

// ── Complexity computation ──────────────────────────────────────────────

interface NestingEntry {
  indent: number;
  contributesNesting: boolean;
}

function computeComplexity(lines: string[], fn: FunctionRange): number {
  let complexity = 0;
  const stack: NestingEntry[] = [];

  // Build a set of line indices to skip (nested function bodies)
  const skipLines = new Set<number>();
  for (const [start, end] of fn.childSpans) {
    for (let i = start; i < end; i++) {
      skipLines.add(i);
    }
  }

  for (let i = fn.bodyStart; i < fn.bodyEnd; i++) {
    if (skipLines.has(i)) continue;

    const line = lines[i];
    if (isBlankOrComment(line)) continue;

    const lineIndent = getIndent(line);

    // Pop closed blocks: any stack entry at indent >= current line
    while (stack.length > 0 && stack[stack.length - 1].indent >= lineIndent) {
      stack.pop();
    }

    // Current nesting depth = count of nesting-contributing entries
    const nesting = stack.filter((e) => e.contributesNesting).length;

    // Check for nested def (increases nesting, no complexity)
    const defMatch = line.match(DEF_RE);
    if (defMatch) {
      stack.push({ indent: lineIndent, contributesNesting: true });
      // The body of the nested def is already in skipLines
      continue;
    }

    // Check for control flow keyword
    const kw = detectKeyword(line);
    if (kw) {
      if (FULL_INCREMENT.has(kw.keyword)) {
        // +1 structural + nesting penalty
        complexity += 1 + nesting;
        stack.push({ indent: kw.indent, contributesNesting: true });
      } else if (STRUCT_ONLY.has(kw.keyword)) {
        // +1 structural only
        complexity += 1;
        stack.push({ indent: kw.indent, contributesNesting: true });
      } else if (NESTING_ONLY.has(kw.keyword)) {
        // No complexity, but body has increased nesting
        stack.push({ indent: kw.indent, contributesNesting: true });
      } else if (NO_INCREMENT.has(kw.keyword)) {
        // No complexity, no nesting contribution
        stack.push({ indent: kw.indent, contributesNesting: false });
      }
    }

    // Logical operator sequences
    complexity += countLogicalOperators(line);
  }

  return complexity;
}

// ── Public API ──────────────────────────────────────────────────────────

export function analyzePythonFile(filePath: string): FunctionComplexity[] {
  let content: string;
  try {
    content = readFileSync(filePath, "utf-8");
  } catch {
    return [];
  }

  const lines = content.split("\n");
  const functions = findFunctions(lines);

  return functions
    .map((fn) => ({
      name: fn.name,
      line: fn.line,
      complexity: computeComplexity(lines, fn),
    }))
    .filter((f) => f.complexity > 0);
}
