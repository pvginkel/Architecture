# Quality Improver

Scan a subproject for duplicated patterns and reinvented utilities, producing a prioritized backlog for `/triage`. Argument: `<subproject> [--since <git-ref> | --last <N>]`.

## What this skill does

You are the orchestrator. You dispatch a single sub-session into a subproject that performs the scan, writes findings to the specs repo, and returns a count. You then summarize for the user and point at the next step.

This skill does **not** create slices or dispatch dev agents. Its output is a findings document — `/triage` is what turns those findings into slices.

## Procedure

### Step 1: Parse arguments

Parse `$ARGUMENTS`:

- **Required positional**: the subproject name (e.g., `viewer`).
- **Optional flags** (mutually exclusive):
  - `--since <git-ref>` — scan only hunks changed since `<git-ref>`.
  - `--last <N>` — scan only hunks changed in the last `<N>` commits.
  - Absence → full scan.

If the subproject is invalid for this monorepo, stop and tell the user the allowed values. If both `--since` and `--last` are passed, stop.

### Step 2: Compute paths

The sub-session runs with `cwd=<subproject>` (e.g., `/work/Architecture/viewer/`), so the specs repo path resolves differently from the subproject CWD. Use **absolute paths** in the prompt to avoid ambiguity:

- Specs repo: `/work/ArchitectureSpecs`
- Output dir: `/work/ArchitectureSpecs/quality-audits/`
- JSON: `/work/ArchitectureSpecs/quality-audits/YYYY-MM-DD-<subproject>.json`
- Markdown: `/work/ArchitectureSpecs/quality-audits/YYYY-MM-DD-<subproject>.md`

Use today's date. The sub-session creates the `quality-audits/` dir if it doesn't exist.

### Step 3: Dispatch the scanner

Write a prompt file to `/tmp/quality-improver-<subproject>-prompt.txt`:

```
I'm the orchestrator. You are the code-quality scanner for the <subproject> subproject. Invoke `/quality-issue-finder` and follow its procedure exactly.

Scope: <"full" | "incremental since <ref>" | "incremental last <N> commits">
JSON output path: <absolute path>
Markdown output path: <absolute path>

When done, print "AUDIT_COMPLETE: N findings" as the final line of your response, where N is the finding count.
```

Dispatch:

```bash
python3 tools/ai_workflow/claude_session.py start --project <subproject> --timeout 3600 \
    --prompt-file /tmp/quality-improver-<subproject>-prompt.txt \
    --response-file /tmp/quality-improver-<subproject>-response.txt
```

### Step 4: Handle the outcome

Check the exit code:

- `0` — success, continue.
- `1` — error. Show the tail of the response file to the user and stop.
- `2` — timeout. Inspect `.claude/sessions/<subproject>.json`. If the last invocation has `duration_ms > 0`, resume with a nudge; otherwise restart.

Verify the run:

- Final line of `/tmp/quality-improver-<subproject>-response.txt` is `AUDIT_COMPLETE: N findings`.
- The JSON file exists, parses, and has `findings` matching the reported count.
- The markdown file exists.
- The files are committed in the specs repo (`cd /work/ArchitectureSpecs && git log -1 -- quality-audits/` should show the scanner's commit).

If any check fails, report to the user and stop. Do not fabricate success.

Finish the session:

```bash
python3 tools/ai_workflow/claude_session.py finish --project <subproject>
```

### Step 5: Report

Read the JSON. Summarize to the user:

- Total findings, broken down by category (`reinvented-utility`, `extraction-candidate`) and severity (`high`, `medium`, `low`).
- The top 3 findings as one-liners: `Q-00N (category/severity) — <title>`.
- Path to the markdown.

Suggest the next step:

```
To turn these into slices, when you're ready:
    /triage ../ArchitectureSpecs/quality-audits/YYYY-MM-DD-<subproject>.md
```

Send a push notification only if the run took over 10 minutes (per root `CLAUDE.md`).

## Important notes

- **One subproject per invocation.** If the user wants a sweep, run once per subproject.
- **Output lives in the specs repo**, not the main repo. The sub-session commits.
- **First run is full.** Subsequent runs on the same subproject can use `--since <last-audit-commit>` or `--last <N>` to scan only drift since the prior audit.
- **This skill does not create slices.** Feed the output to `/triage` when the user is ready.
- **No cross-subproject extraction in v1.** Findings are scoped within a single subproject. Proposals to move code into a shared package are out of scope here.
