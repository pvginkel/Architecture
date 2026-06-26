/**
 * Cognitive complexity analyzer for TypeScript/TSX files.
 *
 * Uses the TypeScript compiler API for accurate AST parsing.
 * Implements the SonarSource cognitive complexity algorithm:
 *
 *   - Structural increment (+1):        if, else, else-if, for, while,
 *                                        do-while, switch, catch, ternary,
 *                                        logical operator sequences
 *   - Nesting increment (+nesting):     if, for, while, do-while, switch,
 *                                        catch, ternary (NOT else, else-if)
 *   - Nesting increases for bodies of:  if, else, for, while, do-while,
 *                                        switch, catch, nested functions
 */

import { readFileSync } from "node:fs";
import ts from "typescript";
import type { FunctionComplexity } from "./types.js";

// ── Helpers ─────────────────────────────────────────────────────────────

/** Get the name of a function-like declaration. */
function getFunctionName(node: ts.Node): string {
  if (ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node)) {
    return node.name?.text ?? "(anonymous)";
  }
  if (ts.isMethodDeclaration(node) || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) {
    return ts.isIdentifier(node.name) ? node.name.text : node.name.getText();
  }
  if (ts.isConstructorDeclaration(node)) {
    return "constructor";
  }
  if (ts.isArrowFunction(node)) {
    // Try to get name from parent variable declaration
    if (ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name)) {
      return node.parent.name.text;
    }
    if (ts.isPropertyAssignment(node.parent) && ts.isIdentifier(node.parent.name)) {
      return node.parent.name.text;
    }
    return "(arrow)";
  }
  return "(unknown)";
}

function isFunctionLike(node: ts.Node): boolean {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isConstructorDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node)
  );
}

// ── Logical operator complexity ─────────────────────────────────────────

type LogicalOp = "&&" | "||" | "??";

/**
 * Count complexity from sequences of logical operators in a binary expression.
 * +1 for each switch between operator types.
 */
function countLogicalSequence(node: ts.BinaryExpression): number {
  const ops: LogicalOp[] = [];
  collectLogicalOps(node, ops);

  if (ops.length === 0) return 0;

  let complexity = 1; // first operator type
  for (let i = 1; i < ops.length; i++) {
    if (ops[i] !== ops[i - 1]) {
      complexity++;
    }
  }
  return complexity;
}

function collectLogicalOps(node: ts.Node, ops: LogicalOp[]): void {
  if (!ts.isBinaryExpression(node)) return;

  const op = node.operatorToken.kind;
  const isLogical =
    op === ts.SyntaxKind.AmpersandAmpersandToken ||
    op === ts.SyntaxKind.BarBarToken ||
    op === ts.SyntaxKind.QuestionQuestionToken;

  if (!isLogical) return;

  // Recurse left first (left-to-right order)
  collectLogicalOps(node.left, ops);

  const opStr: LogicalOp =
    op === ts.SyntaxKind.AmpersandAmpersandToken ? "&&" :
    op === ts.SyntaxKind.BarBarToken ? "||" : "??";
  ops.push(opStr);

  collectLogicalOps(node.right, ops);
}

/** Check if a binary expression is the root of a logical sequence (not a child). */
function isLogicalRoot(node: ts.BinaryExpression): boolean {
  const op = node.operatorToken.kind;
  const isLogical =
    op === ts.SyntaxKind.AmpersandAmpersandToken ||
    op === ts.SyntaxKind.BarBarToken ||
    op === ts.SyntaxKind.QuestionQuestionToken;
  if (!isLogical) return false;

  // If parent is also a logical binary expression, this is not the root
  if (ts.isBinaryExpression(node.parent)) {
    const parentOp = node.parent.operatorToken.kind;
    if (
      parentOp === ts.SyntaxKind.AmpersandAmpersandToken ||
      parentOp === ts.SyntaxKind.BarBarToken ||
      parentOp === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return false;
    }
  }
  return true;
}

// ── Core algorithm ──────────────────────────────────────────────────────

interface FunctionContext {
  name: string;
  line: number;
  complexity: number;
}

function computeComplexity(
  sourceFile: ts.SourceFile,
): FunctionComplexity[] {
  const results: FunctionComplexity[] = [];

  function visitFunction(node: ts.Node): void {
    if (!isFunctionLike(node)) {
      ts.forEachChild(node, visitFunction);
      return;
    }

    const ctx: FunctionContext = {
      name: getFunctionName(node),
      line: sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1,
      complexity: 0,
    };

    // Walk the function body
    const body = (node as any).body as ts.Node | undefined;
    if (body) {
      walkBody(body, 0, ctx, /* isElseIf */ false);
    }

    if (ctx.complexity > 0) {
      results.push({
        name: ctx.name,
        line: ctx.line,
        complexity: ctx.complexity,
      });
    }

    // Don't recurse into nested functions here — they're handled
    // when walkBody encounters them
  }

  function walkBody(
    node: ts.Node,
    nesting: number,
    ctx: FunctionContext,
    isElseIf: boolean,
  ): void {
    // Nested function: increases nesting, reported separately
    if (isFunctionLike(node)) {
      // Report this nested function as its own entry
      const nested: FunctionContext = {
        name: getFunctionName(node),
        line: sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1,
        complexity: 0,
      };
      const body = (node as any).body as ts.Node | undefined;
      if (body) {
        walkBody(body, 0, nested, false);
      }
      if (nested.complexity > 0) {
        results.push({
          name: nested.name,
          line: nested.line,
          complexity: nested.complexity,
        });
      }
      // Nesting increment for the parent (the enclosing function sees
      // the nested function definition as adding nesting complexity)
      // No structural increment for the def itself
      return;
    }

    // ── IfStatement ───────────────────────────────────────────────────
    if (ts.isIfStatement(node)) {
      if (isElseIf) {
        // Continuation: +1 structural, no nesting penalty
        ctx.complexity += 1;
      } else {
        // New if: +1 structural + nesting
        ctx.complexity += 1 + nesting;
      }

      // Walk condition for logical operators
      walkExpression(node.expression, ctx);

      // Then branch at increased nesting
      walkBody(node.thenStatement, nesting + 1, ctx, false);

      // Else branch
      if (node.elseStatement) {
        if (ts.isIfStatement(node.elseStatement)) {
          // else if — continuation, same nesting level
          walkBody(node.elseStatement, nesting, ctx, /* isElseIf */ true);
        } else {
          // else — +1 structural, no nesting penalty
          ctx.complexity += 1;
          walkBody(node.elseStatement, nesting + 1, ctx, false);
        }
      }
      return;
    }

    // ── ForStatement, ForInStatement, ForOfStatement ─────────────────
    if (
      ts.isForStatement(node) ||
      ts.isForInStatement(node) ||
      ts.isForOfStatement(node)
    ) {
      ctx.complexity += 1 + nesting;
      ts.forEachChild(node, (child) => {
        if (child === (node as ts.ForStatement).statement ||
            child === (node as ts.ForInStatement).statement ||
            child === (node as ts.ForOfStatement).statement) {
          walkBody(child, nesting + 1, ctx, false);
        } else {
          walkExpression(child, ctx);
        }
      });
      return;
    }

    // ── WhileStatement ──────────────────────────────────────────────
    if (ts.isWhileStatement(node)) {
      ctx.complexity += 1 + nesting;
      walkExpression(node.expression, ctx);
      walkBody(node.statement, nesting + 1, ctx, false);
      return;
    }

    // ── DoStatement ─────────────────────────────────────────────────
    if (ts.isDoStatement(node)) {
      ctx.complexity += 1 + nesting;
      walkBody(node.statement, nesting + 1, ctx, false);
      walkExpression(node.expression, ctx);
      return;
    }

    // ── SwitchStatement ─────────────────────────────────────────────
    if (ts.isSwitchStatement(node)) {
      ctx.complexity += 1 + nesting;
      walkExpression(node.expression, ctx);
      for (const clause of node.caseBlock.clauses) {
        for (const stmt of clause.statements) {
          walkBody(stmt, nesting + 1, ctx, false);
        }
      }
      return;
    }

    // ── TryStatement ────────────────────────────────────────────────
    if (ts.isTryStatement(node)) {
      // try block: increases nesting, no increment
      walkBody(node.tryBlock, nesting + 1, ctx, false);

      if (node.catchClause) {
        // catch: +1 + nesting
        ctx.complexity += 1 + nesting;
        walkBody(node.catchClause.block, nesting + 1, ctx, false);
      }

      if (node.finallyBlock) {
        // finally: no increment, no extra nesting
        walkBody(node.finallyBlock, nesting, ctx, false);
      }
      return;
    }

    // ── ConditionalExpression (ternary) ─────────────────────────────
    if (ts.isConditionalExpression(node)) {
      ctx.complexity += 1 + nesting;
      walkExpression(node.condition, ctx);
      walkBody(node.whenTrue, nesting + 1, ctx, false);
      walkBody(node.whenFalse, nesting + 1, ctx, false);
      return;
    }

    // ── Logical operator sequences ──────────────────────────────────
    if (ts.isBinaryExpression(node) && isLogicalRoot(node)) {
      ctx.complexity += countLogicalSequence(node);
      // Don't recurse into children — countLogicalSequence already handled them
      // But we should still visit non-logical children (function args, etc.)
      visitNonLogicalChildren(node, nesting, ctx);
      return;
    }

    // ── Default: recurse into children ──────────────────────────────
    ts.forEachChild(node, (child) => walkBody(child, nesting, ctx, false));
  }

  /** Walk an expression subtree, only looking for logical operators and nested functions. */
  function walkExpression(node: ts.Node, ctx: FunctionContext): void {
    if (isFunctionLike(node)) {
      // Nested function in an expression (callback, etc.)
      walkBody(node, 0, ctx, false);
      return;
    }
    if (ts.isBinaryExpression(node) && isLogicalRoot(node)) {
      ctx.complexity += countLogicalSequence(node);
      visitNonLogicalChildren(node, 0, ctx);
      return;
    }
    if (ts.isConditionalExpression(node)) {
      ctx.complexity += 1;
      walkExpression(node.condition, ctx);
      walkExpression(node.whenTrue, ctx);
      walkExpression(node.whenFalse, ctx);
      return;
    }
    ts.forEachChild(node, (child) => walkExpression(child, ctx));
  }

  /** Visit children of a logical expression that aren't part of the logical chain. */
  function visitNonLogicalChildren(
    node: ts.BinaryExpression,
    nesting: number,
    ctx: FunctionContext,
  ): void {
    const visit = (n: ts.Node) => {
      if (ts.isBinaryExpression(n)) {
        const op = n.operatorToken.kind;
        const isLogical =
          op === ts.SyntaxKind.AmpersandAmpersandToken ||
          op === ts.SyntaxKind.BarBarToken ||
          op === ts.SyntaxKind.QuestionQuestionToken;
        if (isLogical) {
          // Continue down the logical chain
          visit(n.left);
          visit(n.right);
          return;
        }
      }
      // Not a logical node — walk normally
      walkBody(n, nesting, ctx, false);
    };
    visit(node.left);
    visit(node.right);
  }

  ts.forEachChild(sourceFile, visitFunction);
  return results;
}

// ── Public API ──────────────────────────────────────────────────────────

export function analyzeTypeScriptFile(filePath: string): FunctionComplexity[] {
  let content: string;
  try {
    content = readFileSync(filePath, "utf-8");
  } catch {
    return [];
  }

  const sourceFile = ts.createSourceFile(
    filePath,
    content,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
  );

  return computeComplexity(sourceFile);
}
