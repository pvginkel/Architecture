# Minor change

Lightweight workflow for pattern-following changes that don't need a written plan. Argument: the path to the change brief (`brief.md` in your slice subproject directory). The coordinator runs a short Q&A with the user, dispatches the code-writer, then the code-reviewer, and drives the fix loop.

For substantive changes that introduce new patterns, cross module boundaries, or involve design decisions worth capturing, use `/major-change` instead.

## When to use this workflow

- The change is pattern-following — existing precedent in the codebase, or a verbatim mirror of a sibling change.
- No new architectural decisions are required.
- Diff surface is narrow (rough guide: ≤ ~200 lines, ≤ ~5 files).
- Executable without a written plan once the brief and clarifications are in hand.

If any of these is false, stop and use `/major-change`.

## Hard guardrails

- **You were gated to questions-only first.** When `/run-slice` dispatched you, the orchestrator gates you to a questions-only round — your first turn on the brief is informed questions, **not** code. Never implement or commit a change before the orchestrator has answered and explicitly told you to run this workflow; running straight from the brief bypasses the code-writer + code-reviewer gates below (the orchestrator checks the `change_brief.md` / `code_review.md` artifacts and will send a bypass back through them).
- The `code-writer` and `code-reviewer` subagents are mandatory. Do not implement the change directly, and do not skip code review.
- The Q&A round is mandatory (see Step 2). Do not skip it because the brief looks clear.

## Step 0: Establish the slice subproject directory

Your working directory is the brief's parent: `<slice_dir>/<subproject>/`. The orchestrator (`/run-slice`) created the slice directory and placed `brief.md` there; your subproject is the name of that parent directory.

**Do not create, edit, or delete files at the slice root or in any sibling subproject folder** — those belong to the orchestrator and the other dev agents.

Document paths (alongside the brief):

- Change brief: `change_brief.md`
- Code review: `code_review.md`

**Commit each document to the specs repo as soon as it's written.**

## Step 1: Read or write the change brief

If the user supplied a brief, read it. Otherwise, write a short change brief based on the user's request. Write to the slice subproject directory.

## Step 2: Q&A round with the user (mandatory)

Read the brief and the surrounding code, then ask the user the questions you have.

**Discipline boundary.** Q&A resolves **scope, ambiguity, and missing context** — not design. Valid questions:

- "Does X apply to all entities of type Y, or only the ones that are Z?"
- "Should the new field show on the detail view as well as the list view?"
- "The sibling precedent uses pattern A; is that what you want here?"

Invalid:

- "How should I structure the service / hook?"
- "Should I introduce a new base class / component?"
- "Which pattern is better — A or B?"

If the conversation tips into design questions, this isn't a minor change. Stop and escalate.

Record the answers in a **Clarifications** section appended to the change brief.

## Step 3: Dispatch the code-writer

Launch the code-writer agent. Pass the full path to the change brief (now including Clarifications). Apply only the described change — no adjacent refactors.

## Step 4: Verification checkpoint (after code-writer)

- [ ] `the subproject's check command` passes.
- [ ] `the subproject's test command` passes (full test suite).
- [ ] `git diff` shows no unexpected changes or scope bleed.
- [ ] Tests were added or updated for the changed behavior.

**Hard gate: tests must actually run.** If they fail due to infrastructure issues, **do not proceed**.

**Fix trivial pre-existing issues inline.** If `the subproject's check command` flags something unrelated to your slice and the fix is obvious and one-shot, fix it as part of your slice commit. Don't stop, don't file a card, don't ask. Anything bigger, leave it and escalate.

## Step 5: Dispatch the code-reviewer

Launch the code-reviewer agent. Pass the full path to the change brief (in lieu of a plan) and instruct it to review the unstaged changes. Delete any existing `code_review.md` first.

Read the review. Resolve ALL issues (BLOCKER, MAJOR, and MINOR). Dispatch the same code-reviewer to resolve them.

## Step 6: Verification checkpoint (after fixes)

Repeat Step 4. If any checks fail, return to Step 5.

## Step 7: Iterate if needed

If you lack confidence, request a new code review from a fresh code-reviewer. Place subsequent reviews at `code_review_2.md`, `code_review_3.md`, etc. If not confident after 2 iterations on a minor change, the change was mis-classified — stop and escalate.

## Quality standards

The work is complete when:

- All brief requirements (including Clarifications) are implemented.
- Code review completed with decision GO or GO-WITH-CONDITIONS.
- ALL review issues are resolved.
- `the subproject's check command` passes cleanly.
- No scope bleed — the diff matches the brief, with no adjacent refactors.
