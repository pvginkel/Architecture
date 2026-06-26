# Refactor Audit

Analyze the codebase for structural health issues and recommend refactoring slices. Uses the `code-health` tool output as a starting point, then does targeted code review to produce grounded, grouped recommendations.

## Procedure

You are the orchestrator. You do not write application code — you produce a prioritized refactoring plan that can feed into slice creation.

### Phase 1: Run the health report

**1a. Run the code health grader** to get the current state:

```bash
poetry run code-health --json
```

Parse the JSON output. Note the flagged files, their scores, ratings, and findings. The tool reports structural metrics (SLOC, function length, cyclomatic complexity, nesting depth, parameter count, class method count, inline imports) and cognitive complexity (via a TypeScript sub-tool in `tools/code_health/cognitive/`). Both metric types are combined into a single composite score per file.

**1b. Present a quick summary** to the user: how many files have findings, score distribution, dominant rule categories. This gives context before the deep dive.

### Phase 2: Spot-check the top files

**2a. Read the flagged files.** For each of the flagged files, read the actual source code. You're looking for:

- **Is the score justified?** Some files are legitimately complex (state machines, protocol handlers). Others are just poorly structured. Note which is which.
- **What are the actual problems?** The health report flags symptoms (long functions, high complexity). You need to diagnose the disease: mixed concerns, missing abstractions, duplicated logic, wrong responsibility boundaries.
- **What would the refactoring actually look like?** For each file, form a concrete opinion: extract class X, split into modules Y and Z, introduce abstraction A, etc.

**2b. Look for relationships.** This is the critical step. Don't treat files in isolation. Investigate:

- **Import graphs** — which flagged files import from each other? Files that are tightly coupled should be refactored together.
- **Shared domain concepts** — do multiple flagged files operate on the same models or services? They may share the same structural problem (e.g., a missing service that both are compensating for).
- **Duplicated patterns** — the health report may flag the same pattern in multiple files (e.g., inline imports, duplicate trigger resolution). These are a single fix, not N fixes.
- **Sibling-subproject mirrors** — files that exist in multiple subprojects (e.g., `frontend/` and `portal/`) with identical or near-identical code. These may indicate missing shared abstractions (check whether a shared package exists, e.g., `packages/shared-ui/`).
- **Caller/callee chains** — a long function may be long because the service it calls has the wrong API. The fix is in the callee, not the caller.

Use Explore agents in parallel to investigate import relationships and shared patterns across the flagged files.

### Phase 3: Group into refactoring themes

**3a. Cluster the files into refactoring groups.** Each group is a set of related files that should be refactored together. Examples of typical groups:

- "Decompose <handler>" — one file, but large enough to be its own slice.
- "Extract <cross-cutting concern>" — N files that all have inline logic that should be centralized.
- "Split <service-cluster>" — 2–3 services that are each too large and share tangled responsibilities.

For each group, document:

- **Files involved** (with current ratings)
- **The structural problem** (what's wrong, grounded in code)
- **The refactoring approach** (what to extract, split, or restructure)
- **Expected impact** (which health metrics improve, rough magnitude)
- **Risk level** (low = internal restructuring with good test coverage; medium = changes to service interfaces; high = changes to data flow or concurrency)
- **Dependencies** (does this group need to be done before or after another?)

**3b. Identify false positives.** Some flagged files may not warrant refactoring:

- Test utilities that are large by design.
- Configuration/factory files with legitimate inline imports.
- Files that are complex because the domain is complex, and splitting would hurt readability.

Call these out explicitly so they can be suppressed. Preferred approaches, in order:

1. Add a `# health: ignore <rule> — <reason>` comment in the first 10 lines of the file (per-file suppressions).
2. Add a pattern to `.codehealthignore` at the repo root (entire directories or file patterns; uses gitignore syntax).

### Phase 4: Prioritize

**4a. Rank the groups** by a combination of:

1. **Impact** — how much does this improve the codebase? Prioritize groups that touch multiple files or fix systemic patterns over single-file cleanups.
2. **Risk** — lower risk first. Internal decompositions with good test coverage are safer than interface changes.
3. **Effort** — smaller groups that deliver clear wins should go before large uncertain restructurings.
4. **Coupling** — groups that unblock other groups (by reducing coupling or clarifying interfaces) should go first.

**4b. Suggest an execution order.** Group the recommendations into waves of 2–3 slices that can run in parallel. Note dependencies between waves.

### Phase 5: Write the report

**5a. Write the audit report** to `docs/refactor_audit_YYYY-MM-DD.md` with these sections:

1. **Summary** — health score distribution, key patterns, number of recommendations.
2. **Refactoring groups** — the grouped recommendations from Phase 3, in priority order.
3. **False positives & exclusions** — files to add to the exclusion list.
4. **Suggested execution order** — waves with dependencies.
5. **Thresholds & rules review** — based on what you saw, should any thresholds or weights in `tools/code_health/config.py` be adjusted? Should the cognitive complexity threshold or weight in `tools/code_health/cognitive_analyzer.py` change? Recommend specific changes if so.

**5b. Present the report to the user.** Walk through the top 3–5 recommendations, explain why they're grouped that way, and ask for feedback before finalizing.

## Key principles

- **Ground everything in code.** Don't recommend "split this file" without reading it and explaining what the split looks like. File paths, line numbers, and concrete descriptions of what moves where.
- **Group over individual.** The value of this audit is finding _related_ problems, not listing files. A group of 4 related files at 5/10 is more valuable to fix than one file at 2/10 in isolation.
- **Don't recommend what isn't broken.** A file can be long and healthy if it has a single clear responsibility. Complexity is only a problem when it hurts readability or maintainability.
- **Think about the refactoring, not the slice.** Your job here is the analysis and grouping. The user will decide which groups become slices and when to run them.
- **Use agents for parallel investigation.** The spot-check phase involves reading 20+ files — batch the reads and use Explore agents for import graph analysis.
