# Write Slice

Author an implementation slice. **Required input: a change-request bundle** produced by `/triage`,
under `../ArchitectureSpecs/change_requests/<slug>/`. Argument: the path to that bundle (or its slug).

A slice is never authored from a bare request — it is authored from a bundle. If you were handed a
raw request with no bundle, stop and run `/triage` first (the only exception is the narrow
interactive minimal-change path described in `/triage`, which still produces the bundle).

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in the slice's acceptance
criteria, briefs, and overview carry their RFC 2119 / BCP 14 meaning. Use them deliberately when
stating requirements.

## What you produce

A complete slice directory under `../ArchitectureSpecs/slices/<NUMBER>_<snake_case_name>/` with the following layout:

```
<NUMBER>_<snake_case_name>/
  overview.md                 — summary of what the slice delivers, why, dependencies
  acceptance_criteria.json    — testable conditions confirming the slice is done
  api_contract.json           — structured API specification
  authoring_notes.md          — authoring decision log + open questions (kept as a record)
  grounding_check.md          — per-brief record of verified file:line citations
                                (always required when any brief is produced)
  ux_design.md                — designer-driven UX exploration (optional)
  <subproject>/brief.md       — scoped brief for that subproject's dev agent
  (one folder per subproject the slice actually touches)
```

Only create the subproject folder for surfaces the slice actually touches — a backend-only slice has only a `backend/` folder. Orchestrator-owned files (everything listed above the subproject folders) stay at the slice root; the `<subproject>/` subfolders are the dev agent's own working directory and hold both the brief and the dev-agent artifacts (plan, change brief, code reviews, etc.) produced during `/run-slice`.

`ux_design.md` is optional — see Step 8 for when to produce one.

Add the slice to the **Pending** section of `../ArchitectureSpecs/README.md` as a **single
line** matching the existing entries — `- **NNN** — <short title>: <one-clause summary>
(#refs; DNNN)`. No status blob: the slice's `overview.md` is where the detail lives. The
README slice index is a lean catalogue (mirroring the thin `decisions.md` index), not a
narrative.

## Procedure

### Step 1: Read the change-request bundle

Read every file in the bundle — `change_request.md` and any attachments. The bundle is your source
of truth: triage has already absorbed the findings, the issue-tracker cards, the Q&A, and any prior
design work into it. You need to understand:

- **What problem** is being solved or what capability is being added.
- **Which surfaces** are likely affected (backend, frontend, portal, or a combination).
- **What the operator expects** to see when the slice is done.

**Capture every explicit request.** If the bundle (or the operator) says "I want X," X MUST become an acceptance criterion — not a suggestion, not a nice-to-have, not something softened into a different approach because it seems easier. If you think X is problematic or infeasible, say so and discuss it. Do not silently substitute a different approach.

Check the issue tracker (the `Architecture` cards the bundle references, now in the Triage board's **Accepted** list) for any context the bundle didn't capture.

### Step 1b: Reconcile with the bundle and challenge — return to the operator only on a delta

The bundle is the **authoritative statement of intent** — triage already clarified it with the operator and absorbed that Q&A. Do **not** re-interview the operator or re-derive what the bundle already settles; that just spends the same touchpoint twice. Instead:

1. **Take the bundle's understanding as your baseline.** Read it as authoritative and record your reading in `authoring_notes.md`. You do not need a confirm-back round for anything the bundle already answers.
2. **Challenge when the request cuts against an established pattern** — project or general (style, architecture, infrastructure, security; `CLAUDE.md`; `../ArchitectureSpecs/decisions.md`; the API contracts). This is what deeper grounding newly surfaces, so it is the part worth raising. The sole purpose is to ensure you do not deviate from the request without the operator being aware. Likely outcomes:
   - The operator changes their mind → the request improves.
   - The operator overrules your objection → you MUST capture *why*, so the direction is explicit.
   - You learn context you were missing → it is critical to a correct end product.
3. **Return to the operator only on a genuine delta** — a pattern conflict, an ambiguity the bundle did not resolve, or something your grounding revealed that changes the shape. If the bundle is clear and grounding surfaces nothing to raise, proceed without a round; the operator still reviews everything at Step 9.
4. **Record the outcome in the slice** (the working document below, and the overview's Constraints/Decisions). Writing it down is what stops a later agent — which will share your instinct — from accidentally re-deviating.

### Step 1c: Keep an authoring working document (`authoring_notes.md`)

While you write the slice, maintain `authoring_notes.md` in the slice folder. It carries two logs and stays in the slice as a permanent record — distinct from `qa_log.md`, which `/run-slice` keeps for the dev-agent Q&A.

- **Decision Log — genuine A/B decisions only.** Log a point **only** when you weighed real alternatives and the choice could reasonably have gone the other way (e.g. *which framework*, *what the exit codes are*, *whether to split the bundle*). Do **not** log requirements, restatements of the brief, natural or forced outcomes, or administrative bookkeeping — these are not decisions and they bury the ones that matter. Things that do **not** belong: "no behaviour change to X" (a requirement); "no wire-contract / config / regen impact" (a natural outcome); "decision id = DNNN" or "design doc placed at …" (administrative); "called out the edge cases" (a requirement). If an item has no plausible alternative, leave it out. Aim for a short log of real decisions, not a diary. Use this **exact format**, one entry per decision (headings and bullets, **no tables**):

  ```
  - <short description of the decision>
    - <the options / alternatives that were on the table>
    - <the choice> — <the reasoning, citing a DNNN or a rule where one applies>
  ```

- **Open Questions.** Questions for the operator that the bundle did not settle. Use this format, with the answer slot written as `_Unanswered_` until the operator fills it in:

  ```
  - <the question>
    - _Unanswered_
  ```

  When a question is answered, replace `_Unanswered_` with the answer; if it was a real A/B, also fold the resolved choice into the Decision Log.

**Write the slice iteratively** when it is non-trivial: make some progress, log your decisions and questions, ask the operator to answer the open questions, then continue. Repeat until the slice is done. When the operator reviews the decisions and asks you to change one, treat it exactly as if they had answered an open question — go back into the loop and revise. That is a *good* outcome: without it the slice would likely have shipped something the operator didn't want.

### Step 2: Research the codebase

Before writing anything, understand the current state:

- Read relevant conventions and architecture decisions.
- Read the code areas that will be affected (models, services, API endpoints, components).
- Check recent slices in the same area for patterns and context.
- Identify dependencies on other slices.

Do not write briefs based on assumptions about what the code looks like. Read it.

**Adjust research to fit the request.** A feature adding a new API endpoint needs you to understand models, services, and existing patterns. A mechanical change like "normalize every version pin" does not — it needs a clear rule and broad scope. Match the depth of your research to what the user actually asked for, and carry that through to the briefs: if the request is rule-based, the brief should state the rule and let the agent apply it, not enumerate every individual change (which agents misread as a closed set).

### Step 2b: Decide whether to split the bundle

One bundle usually becomes one slice. Dev agents do significant work in one sitting, and bundling keeps cycle time down — so the default is a single slice. Split the bundle into multiple slices only when there is a **clear** need (a genuine blocking dependency between parts, or work too large to stay coherent in one slice). When you split, record the split and its reason in `authoring_notes.md`. Prefer one slice; do not split for tidiness.

### Step 3: Assign a slice number

Slice numbers come from a **shared lock-guarded counter** so concurrent `/write-slice` sessions never
collide — several may run at once against the same `../ArchitectureSpecs` working tree, and reading the
README (or scanning `slices/`) for "the next number" races: two sessions pick the same one. Allocate
with the helper script and use what it prints:

```bash
N=$(../ArchitectureSpecs/scripts/allocate-next-slice.sh)   # prints e.g. 044
```

The script `flock`-serializes concurrent callers and persists the reservation to `slices/.next-slice`
**before** your slice folder is created, so a parallel session sees the bump immediately. `.next-slice`
and `.slice-alloc.lock` are host-local coordination, **git-ignored** (not spec artifacts);
`.next-slice` self-seeds from the highest `NNN_` on disk if it is ever missing. A burned number
(allocate, then abandon the slice) leaves a harmless gap — the accepted cost of collision-safety. The
README slice index is no longer the number oracle; you still add the slice to it (Step 10), but the
counter decides the number.

**Follow-up work** to an existing slice does **not** use the allocator — pick a letter suffix tied to
that slice (e.g. `087b`), since the number deliberately follows slice 087 rather than being freshly
sequenced.

### Step 4: Write the overview

The overview is for the orchestrator and reviewers. It explains **what** and **why** — not implementation details.

Structure:

1. **What this slice delivers** — 1–3 sentences describing the outcome.
2. **Why** — the problem being solved or capability being added.
3. **Requirements** — numbered list of concrete requirements (R1, R2, ...).
4. **Current state** — what exists today (if relevant).
5. **Dependencies** — which prior slices must be complete.
6. **Scope** — what surfaces are affected; explicitly note what's out of scope.

**Keep the overview at summary level.** The overview orients a reader — it is not where the working detail lives. The per-subproject **briefs carry the detail** (current-state `file:line` citations, task specifics, edge cases); the overview summarizes. Do not restate a brief's contents in the overview — state the outcome and the requirements at a glance and let the brief hold the rest. A reader should grasp the slice from the overview and reach for a brief when they need one subproject's specifics. This is deliberate: keeping detail in one place avoids the overview/brief duplication that otherwise drifts out of sync.

### Step 5: Write acceptance criteria

**This is the most important file in the slice.** The acceptance criteria are the contract between the user and the implementation. Everything else — briefs, API contracts, overviews — serves the criteria. If a requirement isn't in the acceptance criteria, it won't be verified, and if it's not verified, it may not be delivered.

Write `acceptance_criteria.json` with specific, testable conditions. Each criterion should be verifiable by a test, code review, or spec inspection.

```json
{
  "criteria": [
    {
      "id": "BE-01",
      "area": "viewer",
      "description": "One specific, testable outcome"
    }
  ]
}
```

**ID prefixes:** use subproject-specific prefixes for clarity (e.g., `BE-` backend, `FE-` frontend, `PO-` portal, `RE-` regression).

`acceptance_criteria.json` carries the criteria definition only. Verdicts live in `verification.json` (created and maintained by `/run-slice`) — do not add a `status` field here.

**Good criteria:** "Customer create endpoint returns 201 with id, name, description fields"
**Bad criteria:** "Customer creation works correctly"

**The completeness rule:** Go back through the user's request, the issue-log cards, and the overview requirements. For every explicit ask, there must be a matching acceptance criterion. If the user said "send an event when bindings are complete," there must be a criterion that says exactly that — not a criterion about a polling endpoint that achieves something similar. If you can't write a criterion that matches the request, that's a signal to discuss feasibility, not to quietly substitute.

### Step 6: Write the API contract

Write `api_contract.json` for any API changes. For non-API slices, use:

```json
{
  "changes": [],
  "notes": "No API changes. <context>."
}
```

For slices with API changes:

```json
{
  "endpoints": [
    {
      "id": "EP-01",
      "method": "POST",
      "path": "/api/resource",
      "description": "What this endpoint does",
      "status_codes": [201, 422],
      "key_request_fields": ["name", "description"],
      "key_response_fields": ["id", "name", "created_at"],
      "verified": null
    }
  ],
  "schema_changes": [],
  "removals": []
}
```

### Step 7: Write the briefs

Write one brief per agent that will work on the slice, placed at `../ArchitectureSpecs/slices/<SLICE_DIR>/<subproject>/brief.md` (e.g., `backend/brief.md`). Briefs are the most important part — they're what the dev agent reads to understand its task.

#### The cardinal rule: describe outcomes, not implementations

Briefs describe **what** needs to change and **why**. They do NOT prescribe **how**. The dev agent reads the code and writes the implementation; it knows the context the orchestrator doesn't.

**Good:** "The undo endpoint must detect when an edit has already been undone and return 409."
**Bad:** "Add a query `select(ContentEdit).where(ContentEdit.original_edit_id == edit_id)` and if it returns a result, raise `InvalidOperationException`."

**Good:** "Editor users should see the lock screen when another user holds the session, just like portal users."
**Bad:** "Modify `verify_session_lock()` to remove the early return when `contact_id is None`."

#### Forbidden patterns

If a draft line matches any of these, rewrite it — don't soften, don't caveat.

1. **Code or pseudocode**, even one-liners or "shape" hints. No `select(...)`, no `if x: return 409`, no JSX fragments.

2. **Algorithm or step lists.** "First check Y, then do W" is procedure; describe the outcome and let the agent derive it. This includes task decompositions like "Task 1: add field. Task 2: backfill. Task 3: update endpoint" — that's an algorithm wearing a task list. A task is a unit of outcome, not an implementation step.

3. **Named symbols to create.** Don't name methods, classes, helpers, hooks, or files the agent should produce.
   - **Bad:** "Add a method `_check_lock_owner` and a helper class `LockGuard`."
   - **Good:** "The system must determine whether the requesting user owns the lock and reject the action otherwise."

4. **Target-state `file:line` citations.** Citations describe what the code is today, never what it should become. "Today, X happens in `file:142`" is fine; "Modify `file:142` to do Z" or "Add a function near `file:142`" is not — the agent picks the location.
   - **Bad:** "Modify `app/services/lock.py:142` by hoisting the owner check."
   - **Good:** "The lock owner check today lives in `app/services/lock.py:142`. It must be reachable from both the portal and the editor session paths."

5. **Exact CSS / Tailwind / class strings.** Visual prescription is still prescription. Describe the layout intent in prose and say "match the styling of the surrounding detail view."

6. **Forbiddances without a stated requirement.** If you have to forbid a path, you've imagined the implementation. State the positive requirement instead.
   - **Bad:** "Do not place the `key` prop on the wrapper element."
   - **Good:** "List items must remount when their underlying entity id changes." (The agent figures out where the key goes.)

Precedent references are the one allowed form of pointing at code: "follow the pattern in `<file>`" — no line numbers, no symbol names.

#### Final pass: classify every line

Before freezing, re-read the brief. Every non-trivial line is one of:

- **(a)** Fact about current state with a `file:line` citation — keep.
- **(b)** Outcome, requirement, constraint, or behavioral rule about target behavior — keep.
- **(c)** Prescription about how to get from (a) to (b) — move it: into `acceptance_criteria.json` if it's a requirement in disguise, into the overview's Constraints section if the user explicitly demanded the implementation choice, otherwise delete it.

#### Length ceilings

Past the ceiling, the brief is doing a plan's job and the work belongs in the major workflow:

- **Routine maintenance** (rule-based, dep bumps, sweeps): ≤ 400 words.
- **Pattern-following / bug fix with reproduction**: ≤ 600 words.
- **Any minor brief**: ≤ 1,000 words hard ceiling.
- **Major-workflow briefs**: no ceiling — they go through plan-writer + plan-reviewer.

#### Rule-based briefs (routine maintenance)

When the user's request is a rule applied broadly (dependency updates, bulk renames, config normalization, lint sweeps, dead-code removal, doc fixes), the brief should describe the **rule** and its scope, not enumerate every individual change. Include:

1. The rule (e.g., "normalize every version pin to `^N` based on the latest available version").
2. How to determine inputs (e.g., "run `poetry show --latest` to find the latest version").
3. A few illustrative examples.
4. Explicit scope — "every dependency in the file" vs. "only these specific packages."

Exhaustive tables get misread as a closed set.

**Routine briefs go to the minor workflow regardless of file count.** Each touch is mechanical and the dev coordinator does not need a written plan. Note this in the overview's Scope section ("Routine maintenance — minor workflow expected") so `/run-slice`'s brief-shape check exempts it from the plan-shaped-brief warning.

If a routine brief grows past 400 words, the work is probably no longer routine — design decisions are hidden inside the rule. Surface them to the user before freezing.

#### Brief structure

Each brief should include:

1. **Context** — 1–2 sentences on what the agent is building (point to the overview for background).
2. **Tasks** — numbered, scoped units of work. Each task describes:
   - What needs to change (a new endpoint, a schema modification, a UI screen).
   - Why it needs to change (the problem or requirement it addresses).
   - Constraints and edge cases (validation rules, error conditions, behavioral rules).
   - Which acceptance criteria it covers (reference the IDs).
3. **Testing requirements** — what must be tested.
4. **Code quality** — pointer to the subproject's `CLAUDE.md` for how to verify lint/type/format compliance.

#### Allowed content

The forbidden patterns say what to leave out. Positively, briefs carry:

- **Schema details** — field names, types, constraints (required/optional, nullable, enums, length limits). Facts about the contract, not implementation.
- **Behavioral rules** — "if X, the system must Y." Business logic as requirements.
- **Error conditions** — what can go wrong, status codes, user-facing messages.
- **Constraints** — "must work for both portal and editor users," "must handle concurrent access," "events must use explicit targets."
- **Precedent references** — "follow the pattern in the customers list." Point at the file; no line numbers, no symbol names.
- **Acceptance criterion IDs** — every task references the criteria it satisfies.

#### External dependency updates — verify the bump landed

If the slice depends on a new version of an external dependency (sidecar package, generated SDK, vendor lib pin), the brief must require the dev agent to verify the lockfile is on the new version before relying on the new behavior.

#### Doc-first slices — require a checkpoint between Task 1 and Task 2

When a slice is structured as "Task 1: write a contract/architecture document; Task 2: implement the fix whose direction depends on Task 1's contract" (e.g. an architecture doc that determines which subproject owns a follow-up fix), the brief must explicitly require the agent to stop after Task 1, commit the doc, and wait for user review before starting Task 2.

**Why:** The doc itself is the architectural decision the user wants to vet before code lands. If Task 2 starts immediately based on the agent's reading of the doc it just wrote, the user loses the chance to challenge the contract before implementation.

**How to apply:**
- In the brief's Task 1, include a terminal instruction: *"After committing Task 1, stop and wait for the orchestrator to resume you. Do not start Task 2."*
- In Task 2, note that the task is gated on user review of Task 1.
- Flag the checkpoint in the overview so `/run-slice` knows to pause and hand off to the user between tasks.

This applies to any slice where a planning artifact drives a downstream implementation choice — not just architecture docs (API contracts, schema docs, state-machine specs).

### Step 7b: Grounding pass

**Mandatory — do not skip, do not soften to "consider".** Before any brief in this slice is considered frozen, you must re-ground every codebase claim it contains against the current code. Briefs written from your short-term mental model rather than from a fresh read of the files are the leading cause of Round 1 Q&A corrections. This step exists to catch those misses before the brief is handed to a dev agent.

For every brief produced in this slice (one `<subproject>/brief.md` per subproject the slice touches), you must:

- **(a) Open every `file:line` citation** in the brief and confirm the cited code matches the claim the brief is making about it. A stale line number, a renamed symbol, a moved block — any mismatch gets corrected in the brief before the brief is frozen.
- **(b) Re-grep or re-read the code behind every "the system does X today" / "the current behavior is Y" / "there is no Z today" assertion.** Do not assert current behavior from memory. If the claim is "feature F does not exist yet," grep for it; if it is "endpoint E returns 201 on success today," open the handler.
- **(c) Check every "add Y" / "introduce Y" / "create Y" task against the current codebase** to confirm Y is not already present. Partial implementations count — if a half-built version of Y exists, record what is present so the brief directs the agent to complete rather than duplicate.

You must write a sibling grounding self-check artifact at `../ArchitectureSpecs/slices/<SLICE_DIR>/grounding_check.md`. This file is a dedicated artifact, not inlined into each brief. Its minimum contents:

- One section per brief (`## <subproject>/brief.md` for each subproject the slice touches).
- Under each section, a bulleted list of every claim you checked, each with a `file_path:line_number` citation where relevant and a verdict of **confirmed**, **corrected** (with a short note on what was changed in the brief), or **not applicable** (with a reason).
- A final "Summary" bullet per section stating "all file:line citations verified" — or, if any corrections were applied, listing them.

The artifact lets the orchestrator and reviewers see the grounding pass actually happened. A brief without a matching `grounding_check.md` section is not frozen.

### Step 8: Consider UX design

If the slice involves new screens, novel interactions, complex state management, or ambiguous UI behavior, note in the overview that a UX design is needed. The operator can generate one via the `/ux-design` skill before the frontend/portal briefs are written. The briefs then reference the UX design.

### Step 8b: Consider architecture design

Most slices follow an existing pattern and do not need a separate `/arch-design` run. The dev agent's own planning phase during `/run-slice` surfaces the same implementation subtleties (timing, callback threading, field population, dispatch wiring) that an upfront arch-design would — running both is redundant and the arch-design output tends to re-discover what the dev agent would find anyway.

**Reserve `/arch-design` for slices where:**
- The decision spans multiple agents and affects how they coordinate.
- The decision changes the slice structure (splitting into sub-slices, introducing blocking dependencies).
- There are genuinely competing approaches and the user needs to choose before implementation starts.
- A new cross-cutting pattern is being introduced that future slices will follow.

For "follow the existing pattern" slices, the brief plus the dev agent's own planning is sufficient. Do not default to running arch-design as a safety net.

### Step 9: Present to the operator

Show the operator a summary of what you've written:

- Which agents will run.
- Key requirements and acceptance criteria.
- The **Decision Log and any Open Questions** in `authoring_notes.md` — present the working document alongside the slice so the operator can review the decisions and push back.
- Any design decisions or trade-offs you made, and any ambiguities still open.

Wait for the operator to review and approve. If they challenge a decision or answer an open question, go back into the authoring loop (Step 1c) and revise before considering the slice complete.

### Step 10: Absorb the bundle and update the tracker

Once the slice is approved:

1. **Absorb all source material into the slice.** Everything in the bundle — the `change_request.md` content, the Q&A, the referenced issue-tracker items, and any attachment — MUST be reflected in the slice (overview, acceptance criteria, briefs, `authoring_notes.md`). Only a *substantial* attachment worth keeping verbatim (a long prior design doc, e.g. an arch-design) lives **inside the slice directory** and is linked from the overview; everything else is absorbed in place. **Slice-owned documents — including any design doc — stay with the slice; never park them in `handovers/`** (that folder is for transient cross-session handoffs and accrues cruft). For a design that spans a multi-slice program, keep it in the **keystone slice's** directory and reference it from the program's other slices — it survives there (the slice moves to `completed/`) after the change-request bundle is deleted.
2. **Delete the bundle.** When the slice is complete and self-contained, delete the `change_requests/<slug>/` folder — the operator should be able to delete it with nothing lost. The issue-tracker items are **kept** (they track the work; their content lives in the slice now).
3. **Replace the source cards with a slice card.** The source cards (`Architecture`-tagged, in the Triage board's **Accepted** list) were just collected thoughts and ideas — they have no standalone value now that the slice exists. Create **one new card on the Kanban board in the To Do list that represents the slice** (title = `[NNN] <slice title>` — the slice number in brackets so the card shows which slice it is; the `Architecture` owner tag and no other labels; a short description that gives the highlights — not a restatement of the slice — points to the slice folder, and **lists the source-card ids it subsumes** so the thread from raw idea to slice survives the archive). Then **archive the source cards** that fed this slice. If you split the bundle into multiple slices, create one Kanban card per slice — each listing the source ids it subsumes — and archive the source cards across them. From here that single slice card is what flows **To Do → In Progress → Done**.

### Step 11: Lodge the slice's decisions in the docs

The decisions and conventions this slice establishes are project documentation, not just a slice artifact — and you, the slice author, are the one to lodge them (per [`docs/documentation-model.md`](docs/documentation-model.md)). You already recorded them in `authoring_notes.md` and the overview; now give them their durable home:

- For each decision or convention the slice establishes or changes, write its rationale into the owning `docs/` topic doc — this subproject's, or the **root** `docs/` for cross-cutting design — splitting or adding a small topic doc rather than growing one. State it as the design, not as a dated log entry.
- Add or update its row in the thin decision index (`../ArchitectureSpecs/decisions.md`): `ID | decision | where`, ≤100-character lines, linking to the doc. Mint the next `DNNN` for a new standing decision; keep existing ids stable.
- Leave **how-it-works detail that depends on the final implementation** to `/run-slice`'s close-out reconcile or a later `/update-docs` sweep — at authoring time you document the *decision*, not the finished code.

Commit the doc changes with the rest of the slice's specs artifacts.

## Your role

You are a **work coordinator and validator**, not a technical architect. Your value is in:

1. **Faithfully capturing requirements** — every user request becomes a tracked criterion.
2. **Ensuring completeness** — nothing falls through the cracks between overview, criteria, and briefs.
3. **Pushing back** — raising feasibility concerns before work starts, not silently substituting.
4. **Validating delivery** — verifying at the end that what was asked for is what was built.

You are NOT responsible for designing the implementation. The dev agents read the code, write plans, and make technical decisions. When you spend attention on implementation details, you take it away from coordination and validation — which is where requirements get dropped.

## Quality checklist

Before presenting the slice to the user, verify:

- [ ] Overview explains *what* and *why*, not *how*.
- [ ] **Every explicit user request** has a matching acceptance criterion.
- [ ] **Every issue-log card** scoped into this slice has matching acceptance criteria.
- [ ] No user request was silently substituted with a different approach.
- [ ] Every acceptance criterion is specific and testable.
- [ ] Briefs contain zero code snippets or pseudocode.
- [ ] Briefs describe outcomes and constraints, not implementation steps.
- [ ] API contract lists all new/changed/removed endpoints and fields.
- [ ] Error conditions and edge cases are documented as requirements.
- [ ] Dependencies on other slices are listed.
- [ ] Scope is clear — "out of scope" is stated where relevant.
- [ ] Each brief references which acceptance criteria IDs it covers.
- [ ] Briefs live under `<SLICE_DIR>/<subproject>/brief.md`, not at the slice root.
- [ ] Grounding pass has been run and `grounding_check.md` exists in the slice directory with every `file:line` citation verified and zero unchecked claims.
- [ ] Overview is summary-level — it does not restate brief detail.
- [ ] `authoring_notes.md` exists with the Decision Log (options + grounds) and any Open Questions.
- [ ] The change-request bundle's material is fully absorbed, and the bundle is deleted once the slice is complete.
- [ ] Source cards are archived and replaced by a single Kanban **To Do** card per slice (title prefixed `[NNN]` with the slice number; `Architecture` tag, a short highlights summary, a pointer to the slice, and the list of subsumed source-card ids).
- [ ] Slice is added to the **Pending** section of `../ArchitectureSpecs/README.md` as a single one-line entry (no status blob).
- [ ] Each decision or convention the slice establishes is lodged in the owning `docs/` topic doc and in the thin `DNNN` index (per the documentation model).
</content>
</invoke>
