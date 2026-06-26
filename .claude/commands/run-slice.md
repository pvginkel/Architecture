# Run Slice

Run the implementation workflow for a slice. Argument: the slice number (e.g., `001`).

## What this skill does

You are the orchestrator. You drive per-subproject dev agents through the slice workflow by invoking `claude` via the session manager script. The session manager handles environment setup, session tracking, and state persistence automatically.

**Session manager:** All `claude` invocations go through `python3 tools/ai_workflow/claude_session.py`. No need to manually `unset CLAUDECODE` or `cd` into project directories. The session manager takes a `--project` parameter; supported values include `root` for the orchestrator working tree plus one entry per subproject (e.g., `<subproject>`).

**Prompt delivery:** Prompts are delivered via file or stdin — never as inline shell arguments (to avoid shell escaping issues with backticks, quotes, and special characters).

```bash
# Preferred for long/complex prompts: write a file, pass it with --prompt-file
python3 tools/ai_workflow/claude_session.py start --project <subproject> --timeout 7200 --prompt-file /tmp/prompt.txt --response-file /tmp/response.txt

# Fine for short prompts: heredoc via stdin
python3 tools/ai_workflow/claude_session.py start --project <subproject> --timeout 7200 <<'EOF'
Please read the brief and come back with informed questions.
EOF
```

**Response handling:** The session manager streams progress to stderr and writes the agent's final response to stdout (or to a file via `--response-file`). Use `--response-file` when running in the background so you can read the response after completion.

**Push notifications:** Use `python3 tools/ai_workflow/send_message.py --title "Slice <NUMBER>" "<message>"` to notify the user. Send a notification when:
- The slice completes successfully.
- The slice is blocked and needs user attention (agent failure, test failures requiring user input, missing work reported by a downstream agent, significant API contract gaps).

Do **not** notify for routine progress. Only notify when the user needs to act or when the workflow has reached its end.

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in a slice's acceptance criteria, briefs, and overview carry their RFC 2119 / BCP 14 meaning — read them as binding requirements when answering agent questions and seeding the verification log.

## Slice file formats

Slices are authored by the `/write-slice` skill. The layout:

```
slices/<SLICE_DIR>/
  overview.md, acceptance_criteria.json, api_contract.json,
  grounding_check.md, ux_design.md, verification.json  ← orchestrator-owned
  <subproject>/brief.md                            ← dev-agent-owned folders
  (one folder per subproject that has work in this slice)
```

The files the runner reads:

- **`acceptance_criteria.json`** — testable conditions with `id` (prefixed by subproject — e.g., `TL-`/`VW-`/`SV-`), `area`, and `description`. The criteria definition is immutable here; verdicts live exclusively in `verification.json` (Step 0c onward) so AC state is tracked in one place.
- **`api_contract.json`** — structured API spec with `endpoints` (id, method, path, status_codes, key fields, `verified` flag), `schema_changes`, and `removals`.
- **`<subproject>/brief.md`** — scoped task descriptions for each dev agent. Determine which agents need to run based on which of these files exist.
- **`overview.md`** — what the slice delivers, dependencies, scope.
- **`ux_design.md`** (optional) — UX guidance for slices with non-trivial UI work.
- **`grounding_check.md`** — per-brief record of verified `file:line` citations and "current state" claims produced by `/write-slice`'s grounding pass.

When sending briefs to agents, reference the relevant acceptance criteria and API contract IDs so the agent knows exactly which conditions and endpoints its work must satisfy.

## Procedure

### Step 0: Identify the slice and verify build/test infrastructure

Resolve the argument to the slice directory under `../ArchitectureSpecs/slices/`. For example, argument `001` resolves to `../ArchitectureSpecs/slices/001_<name>/`.

Read all documents in the slice directory. Determine which agents need to run based on which `<subproject>/brief.md` files exist.

**Pre-flight: verify build and test infrastructure.** Before starting any agent, confirm the environment is in a clean buildable state AND that tests can actually run. Code that hasn't been tested is not done, and agents inherit whatever broken environment you hand them — so catch environment drift before they start, not after.

`scripts/preflight.py` runs the full repo build + test (root + `tooling` install, ruff/mypy on `tooling`, `tsc`/vite build + vitest on `viewer` and `service`) and stays silent on success — run it before dispatching any dev agent. Also confirm the working tree is clean under `tooling/`, `viewer/`, and `service/`: leftover changes from an aborted prior run would pollute the slice's commit range.

```bash
python3 /work/Architecture/scripts/preflight.py
```

**If any pre-flight check fails:** do **not** try to work around it — fix the root cause. Notify the user (include the pre-flight output so they can act) and **stop immediately**. Do not start any dev agent. Unverified code is worse than no code.

### Step 0b: Pre-flight review with user

After reading all slice documents and passing infrastructure checks, present a pre-flight summary to the user before starting any agent work.

1. **Work rundown.** Summarize which agents will run based on which briefs exist, with a brief description of what each will deliver (1–3 sentences per agent). Reference the slice's card on the Kanban board (in **To Do**) — `/write-slice` created it, titled `[NNN]` with the slice number.
2. **High-impact decisions.** Flag decisions with significant architectural, data-model, or cross-slice implications (new persistent objects, new API patterns, cross-subproject changes, wire-contract or schema changes). Skip this section if the slice is primarily low-impact work.
3. **Clarifications.** If anything is ambiguous, contradictory, or could go multiple ways, ask the user now — before any agent starts.
4. **Notify and wait.** Send a push notification and wait for the user to respond before proceeding. Do not start Step 0c until the user confirms (e.g., "go", "looks good", "proceed").

### Step 0c: Seed the verification log

Once the user confirms the pre-flight, move the slice's Kanban card from **To Do → In Progress**, then create `../ArchitectureSpecs/slices/<SLICE_DIR>/verification.json` and seed it from `acceptance_criteria.json`. The verification log is the single source of truth for what the slice's independent verifier checks at Step 8c — items only get verified if they're in the log.

Schema (one entry per item):

```json
{
  "items": [
    {
      "id": "V01",
      "source": "ac",
      "area": "<subproject>",
      "description": "VW-1: <verbatim AC description>",
      "verdict": null,
      "rationale": "",
      "evidence": []
    }
  ]
}
```

- `id` — sequential `V01`, `V02`, … in entry order.
- `source` — `ac` (seeded from acceptance criteria) or `qa_correction` (added in Step 1+ when you override an agent's stated direction).
- `area` — the subproject a failure routes back to. For AC entries, copy the AC's `area`.
- `description` — what must be true in the implementation. For AC entries, prefix with the AC id (e.g., `VW-1: …`) so Step 10 can map verdicts back. State the *what*, not the *why* — no opinions.
- `verdict`, `rationale`, `evidence` — left empty; the verifier fills these in.

Seed one item per AC, in order. Commit `verification.json` to the specs repo before starting Step 1.

### Step 1: Run the "leading" subproject

`tooling` leads when a slice touches the schema or the merge pipeline: it defines the metaschema and emits the published dataset plus `viewer/src/generated/vocab.ts`, which `viewer` and `service` consume — dispatch it first in that case. Otherwise dispatch the dev agents in any order.

Start a new session in the leading subproject:

```bash
python3 tools/ai_workflow/claude_session.py start --project <subproject> --timeout 7200 --response-file /tmp/<subproject>_response.txt <<'EOF'
I'm the orchestrator coordinating slice <SLICE_NUMBER>. You are the <subproject> dev agent — your job is to implement the <subproject> part of this slice per the brief. I'll handle everything outside the <subproject> subproject: cross-project test suite, release notes, acceptance criteria, issue tracker, and moving the slice to completed.

IMPORTANT — do not start implementing yet, and do not skip the change workflow. For this first round: read the brief and the code it cites, then come back with informed questions ONLY. After I answer, you will run `/minor-change` or `/major-change` on the brief — the code-writer + code-reviewer gates are mandatory and are the whole point; never implement or commit the change directly. Do not call AskUserQuestion — it errors in a non-interactive session; put every question in your reply to me instead.

Please read ../ArchitectureSpecs/slices/<SLICE_DIR>/<subproject>/brief.md and come back with your questions.
EOF
```

Check the exit code:
- `0` — success, read the response from `/tmp/<subproject>_response.txt`.
- `1` — error, notify the user and stop.
- `2` — timeout, check `.claude/sessions/<subproject>.json`. If the last invocation has `duration_ms > 0`, the agent was working — resume with a nudge. If `duration_ms == 0` or state is stale, restart.

Answer all informed questions yourself based on your knowledge of the project documentation. Be thorough and precise — you know this project deeply.

**Do not prescribe implementation details.** Your answers describe **what** needs to happen and **why**, not **how**. Do not include code snippets, pseudocode, or specific implementation patterns. The agent reads the codebase, writes the plan, and designs the implementation — that's the whole point of the workflow.

**Pick one value when the agent surfaces a tunable.** When a question asks about a numeric threshold, timer, retry count, cadence, or other tunable, give a single value in your answer — not a range, not "either is acceptable." If the agent disagrees with the value, they must argue back; "either is fine" is abdication, not delegation. Picking one value is not implementation guidance — it is a numeric requirement. If the agent had proposed a different value and you overrode it, log that as a `qa_correction` (the description names the required value); if the agent simply asked, your answer is binding and no log entry is needed.

**Ground every claim about the codebase in a verified `file:line` citation.** When an answer depends on how the code behaves today — a call graph, a dispatcher wiring, an endpoint's side effects, a hook's behavior — read the file or grep before committing the answer, and cite `file_path:line_number` in the answer itself. Do not assert code behavior from your short-term mental model. If a claim would slow the answer down to verify, say "I believe X but have not verified" rather than stating X as fact.

**Trace agent-narrated behavior boundaries against the brief, not the agent's framing.** When the agent's plan or answer narrates a behavior boundary — "metric A is exception-only," "this flag toggles only on path X," "log L is unaffected by Z," "the recovery path doesn't need to know about Y" — do not accept the framing on its own merits. For every relevant acceptance criterion, walk what the operator / user / test observes on the new code path *under the agent's stated boundary*, and compare that to what the brief requires. The failure mode this catches: an agent's narrative ("counter semantic stays exception-driven") sounds defensible in isolation but, when traced through the new path, produces an outcome the brief forbids — zero metric increments on a watchdog-driven reconnect even though the metric exists for that exact observability reason; a recovery log gated on a flag that the new clean-return path never sets; a transition pair the brief mandates that never gets emitted because each half lives behind a different gate. Plausible framing is not requirement satisfaction. Apply this on first-round answers, on revised plans, and especially when the agent's prose does the reasoning instead of the code path. If the agent's stated boundary leaves any relevant AC dangling, that is a `qa_correction`.

**Log the Q&A exchange** to `../ArchitectureSpecs/slices/<SLICE_DIR>/qa_log.md`:

```markdown
## <Subproject> — Round N

Q: <agent's question>
A: <your answer>

Q: <agent's question>
A: <your answer>
```

Pair each question with its answer directly. Do the same for other subprojects (using `## <Subproject> — Round N` headings). Create the file on the first write.

**Log corrections to the verification log.** When your answer overrides the agent's stated direction — the agent proposed approach A and you said no, do B because… — also append an entry to `verification.json` with `source: qa_correction`. The `description` should state what must be true in the implementation (not the discussion that led there). Use the next sequential `V##` id and the area of the agent being answered.

The bar is *direction change*. Clarifications, style preferences, picking a tunable value the agent simply asked about, and "yes that's right" confirmations do **not** go in the log — only cases where the agent was about to do something different and you turned them.

**Log deferred items.** If any Q&A exchange surfaces work out of scope for the current slice but needing future attention (a missing feature, a known limitation, a future improvement), create a card in the Triage **Inbox** (tagged `Architecture`) immediately — don't rely on the QA log alone.

**Decide whether to allow follow-up questions.** Use your judgment:
- If the questions show the agent has a good understanding and your answers are clarifications or minor tweaks, skip the follow-up round and go straight to execution.
- If the questions reveal significant gaps, confusion, or unclear scope, allow a follow-up round by ending your answer with: *"Please come back with followup questions. Do not start the implementation if you don't have any."*

**If allowing followups**, write answers to a prompt file and resume:

```bash
python3 tools/ai_workflow/claude_session.py resume --project <subproject> --timeout 7200 --prompt-file /tmp/<subproject>_answers.txt
```

**When ready to execute** (after answering initial questions directly, or after follow-up rounds), write the final answers plus execution instruction to a prompt file:

```bash
python3 tools/ai_workflow/claude_session.py resume --project <subproject> --timeout 7200 --prompt-file /tmp/<subproject>_execute.txt
```

**Keep the execute prompt tight: answers + novel caveats + closing boilerplate.** If it's in the brief, don't repeat it — no scope restatement, no constraint re-listing, no gate reminders. Novel caveats attach to your answers (e.g., "approve the contract, but audit for any deep-link callsites bypassing the cache check").

**Pick the workflow for this agent** based on the brief plus what you learned from Q&A:

- **`/minor-change`** — pattern-following work with existing precedent, no new architectural decisions, narrow diff (≤ ~200 lines / ≤ ~5 files), executable without a written plan. Examples: a verbatim mirror of a sibling change, a bug fix with a clear reproduction, a cosmetic/config tweak, adding a field that follows an established pattern.
- **`/major-change`** — anything that introduces new patterns, crosses module boundaries, or involves design decisions worth capturing in a written plan. Default to major when in doubt.

Asymmetry across agents is expected — e.g., backend major, portal minor when portal mirrors a sibling change.

The prompt file should end with: *"Run `/<chosen_workflow> ../ArchitectureSpecs/slices/<SLICE_DIR>/<project>/brief.md` (e.g. `/minor-change …/brief.md` or `/major-change …/brief.md`) to implement the brief. Store feature artifacts (change brief, plan files, code reviews, feature docs, and other supporting artifacts) under ../ArchitectureSpecs/slices/<SLICE_DIR>/<project>/ — that subfolder is yours. **Do not create, edit, or delete files at the slice root (../ArchitectureSpecs/slices/<SLICE_DIR>/\*.md, \*.json, or any sibling subproject folder) — those belong to the orchestrator and the other dev agents.** Commit ALL your work when done, including the feature artifacts. Run 'git status' before your final commit to make sure nothing is left uncommitted."*

Wait for the agent to complete. Do not poll for progress — the session manager streams progress to stderr. If a long time has passed (30+ minutes) and you suspect the agent may be stuck, run `git status` as a diagnostic — new or modified files in the subproject indicate the agent is actively working. On timeout (exit 2), read `.claude/sessions/<project>.json` and decide whether to resume or restart. On error (exit 1), report the failure and stop.

**On success, verify the agent actually used the change workflow — do not take "done" on trust.** Agents optimize to ship and will sometimes run straight to implementing + committing, skipping the questions round *and* the mandatory `/minor-change` / `/major-change` gate (it has happened). They will also occasionally try to call `AskUserQuestion`, which errors in a non-interactive dispatch and can knock them off the workflow — the gate above pre-empts it. Confirm the workflow ran by checking its artifacts landed in the subproject slice folder: `change_brief.md` for a minor change; `plan.md` + `plan_review*.md` + `code_review.md` for a major one. **Absent artifacts mean the gate was bypassed**, no matter how clean the diff looks — the adversarial code review is the whole point, and an agent's self-report is exactly what it exists to check.

If an agent bypassed the workflow but the work is already committed and correct, **remediate forward rather than redoing it**: resume the session and have it (a) write the `change_brief.md`, and (b) dispatch the `code-reviewer` over the **committed diff** (point it at the commit hashes, since there are no unstaged changes) against the brief + acceptance criteria, writing `code_review.md`. Resolve every finding. Once the artifacts exist and the review is GO, the gate is satisfied. Never accept a silently bypassed workflow.

**On success**, finish the session:

```bash
python3 tools/ai_workflow/claude_session.py finish --project <subproject>
```

### Step 2: Regenerate derived artifacts (if applicable)

The repo's one generated cross-subproject artifact is `viewer/src/generated/vocab.ts` (plus the JSON Schemas under `schema/v0.1/generated/`), emitted from `schema/` by `tooling/generate.py`. If this slice changed the metaschema or an enum, regenerate and commit before dispatching the `viewer` agent so it builds against the updated vocab:

```bash
cd /work/Architecture/tooling && poetry run python generate.py
git add schema/v0.1/generated viewer/src/generated/vocab.ts && git commit -m "Regenerate schema + viewer vocab (slice <NUMBER>)"
```

A new `cap:` enum entry also needs a hand-added icon in `viewer/src/theme.ts` — see [`docs/capability-enum.md`](../../docs/capability-enum.md). If the slice didn't touch `schema/`, skip this step.

### Step 3: Review the API contract (if applicable)

Read the leading subproject's API definition (its route handlers and the shared request/response models, or the generated API spec if you regenerated one in Step 2) and compare it against `api_contract.json`. For each endpoint entry:

1. Verify the endpoint exists (method + path).
2. Check that `key_request_fields` and `key_response_fields` appear in the corresponding models/schemas.
3. Confirm the `status_codes` match what the route returns.
4. Update the `verified` field to `true` or `false`.

For each `schema_changes` entry, verify the change is reflected in the contract definitions. For each `removals` entry:
- `schema_field` removals: grep the contract definitions for the field name and confirm it does not appear in the named model.
- `endpoint` removals: confirm the method + path combination is gone.

Write the updated `api_contract.json` back to the slice directory.

If any endpoint has `verified: false`, assess whether it's a significant gap (missing endpoint, wrong schema) or a minor difference (field ordering, naming convention). Significant gaps → notify the user and stop. Minor differences are fine.

**Log any issues** (gaps, deferred items, workarounds) as cards in the Triage **Inbox** (tagged `Architecture`).

### Step 4+: Run the consumer subprojects

For each remaining subproject with a brief file, run `claude` using the same pattern as Step 1 (ask questions, log Q&A, append `qa_correction` entries to `verification.json` per the Step 1 rule, pick workflow, execute, verify the change-workflow gate ran, finish). The sequence is the same; only the project name changes.

**UX design:** If `ux_design.md` exists, include it in the initial prompt: ask the agent to read it alongside the brief.

**Check for testing infrastructure gaps.** If the agent's questions reveal that it needs testing infrastructure from the leading subproject (e.g., a seeding endpoint for end-to-end tests), **stop the agent immediately**. Send the leading subproject's agent to implement the missing infrastructure first, then resume. Testing infrastructure gaps are blocking.

### Step 7: Run the full test suite

After all agents have completed, run the full test suite to verify everything is green:

```bash
python3 scripts/build-all.py
```

Run this in the background (`run_in_background: true`). The background task mechanism notifies you automatically when it completes — do **not** poll with sleep+check commands.

**If all tests pass:** proceed to Step 8c.

**If any tests fail:**

1. Read the suite-result artifact for the detailed failure output.
2. For each failure, identify which agent owns it based on where the failing test lives.
3. **Diagnose before fixing.** Understand *why* the test fails. In particular:
   - **When a consumer subproject's tests fail after a leading-subproject-only change**, the cause is almost always test infrastructure that references the old behavior (a startup command, an endpoint path, an env var). Look at how **passing** tests start their services and follow the same pattern for the failing service. Do not add special cases or workarounds — if a fix requires a lot of special-casing, the approach is wrong.
   - **When a fix seems to need changes to the app factory or core test infrastructure**, stop and reconsider. That infrastructure is battle-tested; the problem is more likely in the new code.
4. Write the failure output to a prompt file and send the owning agent back to fix it. Tell the agent explicitly: *"The test suite was green before your changes. These failures are regressions caused by your code changes (all unpushed commits). Find and fix the root cause."* Include the full failure output and your diagnosis.
5. After the agent finishes, re-run the suite to verify the fix.
6. **If a failure is clearly caused by a leading-subproject gap** that a consumer agent cannot fix alone, notify the user and stop.
7. **Repeat until green or blocked.**
8. **Maximum 3 fix rounds per agent.** If an agent cannot get its tests green after 3 attempts, notify the user and stop.

### Step 8c: Independent verification

Verification runs in fresh context via the `slice-verifier` sub-agent walking the verification log.

1. **Determine the slice's commit range** — typically the unpushed commits on the current branch, or the commits added since this slice started. Capture as a hash range or list.

2. **Dispatch the `slice-verifier` sub-agent** with paths only:

   ```
   Slice directory: ../ArchitectureSpecs/slices/<SLICE_DIR>/
   Commit range: <hash>..HEAD  (or specific hashes)
   ```

   **Do not** include framing — no opinions about quality, no hints about which entries you expect to pass. The agent definition contains everything the verifier needs.

3. **Read the updated `verification.json`.** The verifier has filled in `verdict`, `rationale`, and `evidence` per entry.

4. **Route the result:**
   - Any entry with verdict `failed` or `uncertain` → slice goes back to the owning agent (use the entry's `area`) with the verifier's evidence and the gap. Do not re-derive the verdict yourself.
   - A rationale that reads like a rubber-stamp (matches without surprises, no falsification statement) → send back to the verifier with the entry id and ask for sharper reading.
   - All passed → proceed to Step 9.

Trust the verifier's flags. If you genuinely disagree, escalate to the user — do not add an override block to `verification.json`. `verification.json` is committed with the rest of the slice artifacts at the end of the run.

### Step 9: Review QA log for issue log items

Review `../ArchitectureSpecs/slices/<SLICE_DIR>/qa_log.md` end-to-end. Look for:

- **Deferred work** — features or improvements explicitly deferred to a later slice.
- **Known limitations** — architectural shortcuts that will need revisiting.
- **Contract/spec drift** — cases where implementation diverged from the original brief.
- **Design decisions with future implications.**

For each item found, create a card in the Triage **Inbox** (tagged `Architecture`). Don't duplicate items already logged inline during Q&A.

### Step 9b: Reconcile the project docs

A slice that changed the design or a convention is not complete until the project docs reflect what was actually built (per [`docs/documentation-model.md`](docs/documentation-model.md) — the slice author already lodged the slice's decisions in the docs at authoring time; this step confirms reality matches). Scoped to what this slice touched:

- For each decision or convention the slice established or changed, confirm the owning `docs/` topic doc states the design **as implemented**, not just as authored. Where the implementation diverged from the authored intent (watch the `qa_log.md` drift items from Step 9), fix the doc and its thin `DNNN` decision-index row, or run `/update-docs` with a hint to reconcile that scope.
- Design that landed during implementation but has no doc home gets one — a small topic doc, added to the scope's `index.md`.

A full sweep is `/update-docs`'s job, not this step's. Commit any doc changes with the rest of the slice's specs artifacts.

### Step 10: Report results

Summarize what happened:
- Which agents ran and whether they succeeded.
- Any issues encountered.
- The API contract review result (from `api_contract.json` — how many endpoints verified/failed).
- Test suite results (pass/fail per project, number of fix rounds if any).
- Acceptance criteria results — count `source: ac` entries in `verification.json` by `verdict`. At this point all should be `passed` (failed/uncertain were routed back in Step 8c); if any remain unresolved, Step 8c was skipped and you must go back.
- Any failures blocked on identified gaps (link to issue log entries).

Move the slice to completed (only when it is fully complete):

- **In `../ArchitectureSpecs/README.md`**, move the slice's entry from the **Pending** section to the **Completed** section, kept in slice-number order. It stays the **same single line** — `- **NNN** — <short title>: <one-clause summary> (#refs; DNNN)`. Do **not** copy the Step 10 run report (AC counts, agent outcomes, run notes) into the README — that detail lives in the slice's `overview.md` and git history. The slice index is a lean catalogue, not a status log.
- **On disk**, `git mv ../ArchitectureSpecs/slices/<SLICE_DIR> ../ArchitectureSpecs/slices/completed/<SLICE_DIR>` (create `slices/completed/` if it does not exist) so the active `slices/` view shows only in-flight work. The slice folder stays intact as its record.
- **On the Kanban board**, move the slice's card **In Progress → Done**.

Commit the move together with the rest of the slice's specs artifacts. (A slice the operator defers or cancels instead goes to `slices/deferred/` or `slices/cancelled/` — those folders are created lazily, only when first needed; anything already filed under `slices/archive/` is left untouched.)

Notify the user that the slice is complete (or partially complete if there are outstanding items).

## Important notes

- **The test suite is green before every slice.** This is a hard assumption. If tests fail after a slice run, the slice's changes caused the regression. Do NOT dismiss failures as "pre-existing" or "flaky" — this has been wrong every time. Always send the owning agent back with the explicit instruction that the suite was green and their changes caused the failure.
- **No backwards compatibility.** When answering agent questions, never suggest backwards-compatible workarounds (optional fields to preserve old callers, fallback branches, silent defaults for missing data). Always prefer clean breaking changes.
- **Answer questions yourself.** You have full access to all project documentation. Do not ask the user to answer the dev agent's questions.
- **Do not put code in briefs or answers.** Describe *what* and *why*, not *how*.
- **Stop on failure.** If any agent fails, report to the user and stop.
- **Do not run agents in parallel.** Subprojects may have dependencies — the leading subproject must complete before consumers can start.
- **Run subprojects sequentially**, not in parallel. Resource constraints during test suites make parallel runs unreliable.
- **Timeouts.** Dev agents may take a long time, especially running end-to-end tests. Default timeout is 2 hours per invocation. On timeout, check the session state file at `.claude/sessions/<project>.json` before deciding to resume or restart.
- **Session state files** live at `.claude/sessions/<project>.json`. You can read them at any time to check invocation history and session IDs.
- **Agents must always use one of the change workflows — and verify they did.** Gate every initial dispatch to questions-only (see Step 1) so the agent doesn't run ahead, and forbid `AskUserQuestion` (it errors in a non-interactive dispatch). After the agent reports done, confirm the change-workflow artifacts exist before accepting the work (see "On success, verify…"). A missing `change_brief.md` / `code_review.md` means the gate was bypassed; remediate forward via the `code-reviewer` over the committed diff. If an agent genuinely can't make progress within the workflow, the slice is too large — report to the user to discuss splitting it.

## Issue log

Whenever you encounter something that needs future attention — a gap in the API, a deferred feature, a workaround, a missing field, a known limitation — log it as a card on the Triage board's **Inbox** (tagged `Architecture`). See root `CLAUDE.md` for the two-board model and the card conventions.

**Card lifecycle during a slice run:**
- When a slice **starts**, find the slice's card on the **Kanban** board (in **To Do**) — `/write-slice` created it, titled `[NNN]` with the slice number — and move it to **In Progress** (Step 0c).
- When the slice's work is **implemented and verified**, move its Kanban card **In Progress → Done** (Step 10).
- When new issues are **discovered** during the slice (QA log, spec review, test failures), create them as cards in the Triage **Inbox** (tagged `Architecture`). They are fresh intake for a future triage, not part of this slice's Kanban card.
- At the **end of the slice** (Step 10), confirm the slice's Kanban card is in **Done** and that every newly-discovered item is captured in the Triage **Inbox**.
</content>
</invoke>
