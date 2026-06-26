# Major change

Workflow for substantive changes — anything that introduces new patterns, crosses module boundaries, or involves design decisions worth capturing in a written plan. Argument: the path to the change brief (`brief.md` in your slice subproject directory). The coordinator dispatches the four dev agents (`plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`) in order and drives the verification and iteration loop.

For small, pattern-following changes, use `/minor-change` instead.

## Before you start: the dispatch contract

When `/run-slice` dispatched you as the subproject dev agent, **the orchestrator gates you to a questions-only round first** — your first turn on the brief is informed questions, **not** code. **Never implement or commit a change before the orchestrator has answered and explicitly told you to run this workflow.** Implementing straight from the brief bypasses the plan → plan-review → code → code-review gates this workflow exists to enforce; the orchestrator verifies those gates ran by checking the `change_brief.md` / `plan.md` / `code_review.md` artifacts, and will send a bypassed change back through them.

## Step 0: Establish the slice subproject directory

Your working directory is the brief's parent: `<slice_dir>/<subproject>/`. The orchestrator (`/run-slice`) created the slice directory and placed `brief.md` there; your subproject is the name of that parent directory.

**Do not create, edit, or delete files at the slice root** (`<slice_dir>/*.md`, `*.json`) **or in any sibling subproject folder.** Those belong to the orchestrator and the other dev agents.

Document paths (pass these to every agent invocation):

- Change brief: `change_brief.md`
- Plan: `plan.md`
- Plan review: `plan_review.md`
- Code review: `code_review.md`

**Commit each document to the specs repo as soon as it's written** — don't wait until the end of the workflow. Multiple agents may work in the specs repo concurrently, so frequent small commits avoid conflicts and prevent work loss if a session crashes.

## Step 1: Write the change brief

Describe the work at a functional level based on the user's input. Write the change brief to the slice subproject directory.

If confidence is low that the brief describes the change clearly, respond back to the user and abort.

## Step 2: Dispatch the plan-writer

Launch the plan-writer agent. Pass the full path to the change brief and the target plan location. Resolve all questions autonomously.

The plan-writer produces `plan.md` plus companion JSON files (`requirements.json`, `file_map.json`, `test_plan.json`).

## Step 3: Dispatch the plan-reviewer

Launch the plan-reviewer agent. Pass the full path to the plan.

The plan-reviewer produces `plan_review.md` with a JSON decision block and prose findings. Read the review.

**Apply review feedback.** If the review has **Blocker** or **Major** findings, dispatch the plan-writer again with the review as input and ask it to update the plan. Then re-run the plan-reviewer. Repeat until the review comes back with no **Blocker** or **Major** findings.

## Step 4: Dispatch the code-writer

Launch the code-writer agent. Pass the full path to the plan.

If the agent does not complete the plan in full, provide assistance: encourage progress, perform a partial review (spot-check + run tests), or request self-testing.

## Step 5: Verification checkpoint (after code-writer)

Before proceeding to code review:

- [ ] `the subproject's check command` passes (lint, type-check, dead-code).
- [ ] `the subproject's test command` passes (full test suite).
- [ ] Review `git diff` for unexpected changes.
- [ ] New test files were created as required by the plan.
- [ ] `requirements.json` (if present): spot-check that key requirements appear implemented.
- [ ] `test_plan.json` (if present): spot-check that planned test scenarios have corresponding test functions.

- [ ] Generated artifacts are regenerated when their source changed — `viewer/src/generated/vocab.ts` via `tooling/generate.py` (CI enforces this with `--check`).
- [ ] A new `cap:` enum entry in `schema/v0.1/enums/capabilities.yaml` has a matching icon hand-added to `CAPABILITY_ICON` in `viewer/src/theme.ts`.

**Hard gate: tests must actually run.** If `the subproject's test command` fails due to infrastructure issues, **do not proceed** to code review and **do not commit**. Report the infrastructure issue and stop.

**Fix trivial pre-existing issues inline.** If `the subproject's check command` flags something unrelated to your slice and the fix is obvious and one-shot, fix it as part of your slice commit. Don't stop, don't file a card, don't ask. Anything bigger, leave it and escalate.

## Step 6: Dispatch the code-reviewer

Launch the code-reviewer agent. Pass the full path to the plan and instruct it to review the unstaged changes. Delete any existing `code_review.md` first.

Read the review. Even on a GO decision, resolve ALL issues (BLOCKER, MAJOR, and MINOR). Dispatch the same code-reviewer to resolve the issues, providing clear context.

## Step 7: Verification checkpoint (after fixes)

Repeat Step 5. All checks must pass. If any fail, return to Step 6.

## Step 8: Iterate if needed

If you lack confidence in the end result, request a new code review from a fresh code-reviewer instance. Place subsequent reviews at `code_review_2.md`, `code_review_3.md`, etc. If not confident after 3 iterations, escalate to the user.

## Hard guardrails

- Use only the dev agents: `plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`. Do not implement the change yourself.
- Minor localized corrections by the coordinator are acceptable if you're confident.

## Quality standards

The work is complete when:

- All plan requirements are implemented.
- Code review completed with decision GO or GO-WITH-CONDITIONS.
- ALL issues identified in code review are resolved.
- `the subproject's check command` passes cleanly.
- `the subproject's test command` passes cleanly.
- Tests that fail as a side effect of the work are fixed.
- No outstanding questions remain (or are deferred to the user with clear context).
