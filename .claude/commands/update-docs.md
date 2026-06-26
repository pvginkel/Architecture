---
description: Bring the project documentation set into line with reality — small, discoverable topic docs plus a thin decision index. Seeds a scope from nothing or reconciles drift. Argument (optional): a hint to focus on (a subproject, an area, or "absorb decision DNNN").
---

# Update Docs

Get the docs current. One job: make every scope's `docs/` reflect how the code actually works and
why, organized so the right doc can be found and pulled into a per-change reading list. There are
**no modes** — if a scope has no docs yet, that is simply more work (you are seeding); if it has
them, you reconcile drift. An optional **hint** narrows the focus: a subproject (`viewer`),
an area (`the viewer's public API`), or a decision to absorb (`absorb D094`). With no hint,
the whole set is in scope.

## Why this is a skill, not an agent

Seeding or sweeping a scope means surveying it whole — best done by fanning out several **Explore
sub-agents in parallel**, keeping their conclusions and not the file dumps. A sub-agent can't spawn
sub-agents, so this can't live in an agent; it runs in the **main conversation**, where it can fan
out. Run it from the main loop.

## Read first

1. **`docs/documentation-model.md`** (repo root) — the model you enforce: the layout rules, the thin
   decision index, and who maintains what. Everything below is in service of it.
2. The target scope's existing `docs/` and its `index.md` — what is already documented.
3. The sources of truth, for the scope in question:
   - the **code** (ground every claim in it);
   - `../ArchitectureSpecs/decisions.md` (the `DNNN` rationale, until it is fully absorbed);
   - `../ArchitectureSpecs/slices/**` overviews + acceptance criteria (the design intent behind changes);
   - recent `git log` for the scope (what changed since the docs were last touched).

## Steps

1. **Scope it.** From the hint (or the whole set by default) pick the scopes to work: the root and/or
   one or more subprojects (`viewer`, …).

2. **Survey — fan out Explore agents.** Launch Explore agents in parallel (one per scope or area).
   Give each the documentation model and ask it to return, with `file:line` evidence:
   - the real design, conventions, and behaviours of the scope (what an implementer would need to
     know);
   - what is already documented, and where the docs have **drifted** from the code;
   - **gaps** — design that lives only in code, slices, or `decisions.md` with no doc home;
   - which `DNNN` decisions pertain to this scope and are not yet absorbed into a topic doc.
   Conclusions, not file contents.

3. **Triage the non-obvious with the operator.** Where the call isn't clear — is this a real standing
   convention or a one-off? is this rule still true? how should a fat topic be split? — surface it and
   let the operator decide. Don't invent rules and don't preserve stale ones unilaterally. Routine,
   well-grounded updates need no checkpoint; this is maintenance, not a design review.

4. **Author / update.** Apply the model:
   - Write **small, single-topic** docs; split a doc that is growing two subjects and index both.
   - Keep each scope's `index.md` current, with a crisp one-line description per doc so the right one
     surfaces without being opened.
   - **Absorb decision rationale** into the topic doc that owns the design, and update that decision's
     row in the thin index (`ID | decision | where`, ≤100-char lines) to point at it. The `DNNN` id
     stays stable; only the content moves.
   - State the design as it is — no chronological logs, no tombstones. Match the voice of the
     surrounding docs.

5. **Validate.** Every claim grounded in code or spec. No invented or aspirational conventions. Links
   resolve. The index matches the docs on disk (no orphan entries, no undocumented docs). Decision
   rows fit in 100 characters.

6. **Commit.** Per the repo's commit-as-you-go rule, in the repo each file lives in (docs in the main
   repo, the decision index in `../ArchitectureSpecs`). Stage only the files you touched.

## Constraints

- **Ground everything.** If a "rule" isn't real in the code or specs, it doesn't go in a doc. When a
  source contradicts a doc, the code wins — fix the doc and say so.
- **Small + discoverable beats complete-but-bulky.** A reading list pays for every line it loads.
- **Don't restate** `CLAUDE.md` or the code. Document the design and conventions; link the rest.
- **Keep the decision index thin.** Rationale lives in the doc, never in the table. Never drop or
  renumber a `DNNN` — slices, the API contracts, and code cite it.
- **No tombstones in docs.** A superseded convention is a rewrite, not an appended changelog.
- **The hint focuses; it doesn't widen.** No hint means the whole set; a hint means just that slice
  of it.
