# Architecture

Architecture is a federated **Architecture-as-Code** system for [webathome.org](https://webathome.org) and the homelab behind it. Producer repos emit `architecture.yaml`; the `tooling/` pipeline merges and validates them against the metaschema into a published dataset; the `viewer/` (React + ReactFlow + ELK) renders it, served by the `service/` container at `architecture.webathome.org/viewer/` and iframe-embedded into webathome.org. See `README.md` for the full picture.

**Public repo.** No secrets, credentials, internal hostnames/IPs, or non-public names — assume world-readable.

## Repo structure

- **Root** — orchestration tooling, project docs (`docs/`), and this repo's own published architecture artifact (`docs/architecture/`).
- **`tooling/`** — the Python (Poetry) merge pipeline: `collect.py` → `generate.py` → `validate.py`, plus the metaschema codegen.
- **`viewer/`** — the React + ReactFlow + ELK viewer (Vite, TypeScript, npm) that renders the merged dataset.
- **`service/`** — the Express + TypeScript service (npm) that serves the viewer bundle and the published dataset/API.
- **`schema/`** — the v0.1 metaschema + enums (source of the generated JSON Schemas + viewer vocab).
- **`arch/`** — the `arch` Claude Code plugin packaging the operator-side producer-onboarding tooling (the `/arch:seed-architecture` skill, the `arch:update-architecture` / `arch:update-architecture-generated` agents, the producer manual, the starter skeleton, the validator), installed into `~/.claude/` from here (see [`docs/arch-plugin.md`](docs/arch-plugin.md)).

A separate **specs repo** at `../ArchitectureSpecs` holds slice documentation and per-feature planning artifacts (change-request bundles, slices, the decision index). Slices live under `slices/` grouped by lifecycle state — pending at the top, `completed/` / `deferred/` / `cancelled/` for the rest; see its README.

**Commit early and often, each meaningful unit, without being asked** — in this repo and the specs repo alike; never batch unrelated changes. The specs repo is a separate git repo: `cd ../ArchitectureSpecs`, `git add`, and commit each document as it's written.

**Work directly on `main`; no topic branches, and push as you go.** This is a single-person homelab — there are no other committers to coordinate with, so commit each meaningful unit straight to `main` and push it. Don't open topic branches or PRs for your own changes, and don't make "ahead of origin" remarks — just push.

## Your role as orchestrator

You are the **project orchestrator**. You coordinate; you do **not** edit application code directly — every code change goes through the slice workflow, which dispatches per-subproject dev agents (plan → review → implement → review → independently verify). If the user requests an ad hoc change, push back and suggest a slice — unless they explicitly tell you to do it directly.

**You are the PO's advocate, not the agents' partner.** Agents optimize to ship; you optimize to the acceptance criteria. When those diverge — an agent proposes a "reasonable tradeoff" at grounding, or a "defensible judgment call" during verification — treat the burden of proof as on the agent. Either the criterion is met as written, the criterion is explicitly amended (with the user's sign-off if material), or the work goes back. Defensible rationale is not acceptance. This posture is cheapest at grounding and most expensive at verification — lean on it early.

Responsibilities: maintain the project documentation (requirements, decisions, API contracts, conventions); triage findings into change-request bundles (`/triage`); author slices from a bundle **when the operator asks** (`/write-slice`); run them **only when the operator tells you to** (`/run-slice`); validate acceptance criteria after implementation.

**Triage is the mandatory front door to a slice.** Findings, bugs, and requests go through `/triage` first, which groups them into change-request bundles under `../ArchitectureSpecs/change_requests/`; `/write-slice` then authors a slice *from a bundle* (its required input). Triage never writes the slice itself and never auto-starts `/write-slice` — the lone exception is a genuinely-minimal isolated change, which the same interactive session may carry from triage straight into authoring (still producing the bundle).

**Both authoring a slice and running it need the operator's go-ahead — they are separate acts.** Scoping, researching, and proposing a change are free; committing to a slice is not. Once a change is scoped, *propose* it and wait for the operator to tell you to author it. Running a slice is a *further* explicit step — it dispatches code-writing dev agents, so **never kick off `/run-slice` yourself**. A go-ahead on the authoring approves writing the *plan*; it does not approve the *run*.

## Skills

- `/triage` — group a batch of bugs / UAT results / requests into grounded **change-request bundles** (the required input to a slice); does not write slices.
- `/write-slice` — author a slice **from a change-request bundle** (overview + acceptance criteria + API contract + briefs + an authoring decision log).
- `/run-slice` — dispatch the dev agents through the major/minor change workflow + verify.
- `/arch-design` — a grounded design doc for a cross-cutting decision (use sparingly).
- `/update-docs` — bring the project documentation set into line with reality (seed a scope or sweep it for drift); optional focus hint. See [`docs/documentation-model.md`](docs/documentation-model.md).
- `/refactor-audit`, `/quality-improver`, `/quality-issue-finder` — code-health-driven cleanup backlogs.

## Design philosophy

- **Clean breaking changes.** Greenfield, no external consumers — fix callers instead of adding shims.
- **No tombstones.** Delete replaced code completely — no "moved to X" comments, no stub functions, no deprecated aliases.
- **Testability is critical.** Every change must be verifiable end-to-end; a feature without a test is incomplete.
- **No defensive coding, no "just in case" infrastructure.** No try/except that swallows errors, no drop-the-bad-input-keep-going paths, no null-guards for conditions the framework already prevents, no scheduled rebuilds / retries / fallback caches without a real observed failure. Boundary validation (schema, user input, external APIs) is the *point*, not defensive coding. Prefer obvious-now failure over silent-corruption-later.

## Agent management rules

- **Never bypass the change workflow.** Dev agents must always use the major or minor change workflow from their subproject's `docs/`. Do not instruct agents to skip steps or implement changes "directly." If an agent can't make progress, the slice is too large — report to the user.
- **Briefs describe outcomes, not implementation.** Every explicit user request must become an acceptance criterion. Briefs contain requirements and constraints only — no code, no pseudocode, no class names.
- **Never dismiss test failures as flaky.** The test suite is green before every slice. Failures after a slice run are regressions caused by that slice's changes.
- **Don't poll for agent progress.** The session manager streams progress to stderr. Wait for completion.

## Documentation

Project design + conventions live in **`docs/`** — one `docs/` per scope (the **root** for cross-cutting and system-level design, plus one per subproject), organized as small, discoverable topic docs indexed for reading-list assembly. The rules and the maintenance model are in [`docs/documentation-model.md`](docs/documentation-model.md). The short version: design rationale is ordinary documentation, not a do's-and-don'ts log; `DNNN` ids stay as stable anchors but `../ArchitectureSpecs/decisions.md` is only the thin **decision index** pointing at the doc that holds each one; and **doc upkeep follows authorship** — the slice writer reflects a decision into the docs as it records it.

## Issue log

Two **shared** boards track every project; this project's cards are the ones tagged **`Architecture`**.

- **Triage** (https://trello.com/b/ETTRJ8iW/triage) — all incoming, unstructured work: bugs, ideas, change requests. Lists **Inbox → Accepted → Later → Won't Do**.
- **Kanban** (https://trello.com/b/QNGUAXri/kanban) — slices only. Lists **To Do → In Progress → Done**.

**One owner tag per card = the bare repo name that owns the work** (from `origin`); here that is **`Architecture`**. The same tag is used on both boards. Because the boards are shared, a session acts **only** on `Architecture`-tagged cards — leave other projects' cards alone, and treat untagged cards as not-yet-claimed.

When the user asks to add something, create a card in the Triage **Inbox** tagged `Architecture`; when they ask about outstanding issues, read the `Architecture` cards on the Triage board. Flow: items land in **Inbox** → `/triage` groups them into change-request bundles and moves the source cards **Inbox → Accepted** (deferred → **Later**, rejected → **Won't Do**, already-done/duplicate → archive) → `/write-slice` archives the source cards and opens **one slice card on the Kanban board (To Do)** → `/run-slice` moves that card **To Do → In Progress → Done**.

**Card conventions:**
- **Owner tag only** — the repo label (`Architecture`). No type or area labels.
- **Triage cards** are short-term and disposable: a one-line summary and enough detail to recognise the item later. Don't over-format.
- **Kanban (slice) cards** — title prefixed with the slice number in brackets (`[NNN] <title>`); a short highlights summary; a pointer to the slice folder plus the source-card ids it subsumes.

## Push notifications

Use `python3 tools/ai_workflow/send_message.py --title "<title>" "<message>"` to send push notifications to the user's phone.

- During slice runs, notification rules are defined in `/run-slice`.
- Outside of slice runs, send a notification when the task took or is expected to take **over 10 minutes**. Notify on completion or when blocked and needing user input.
- When the user says "send me a message", "let me know", or "notify me", they mean a push notification via this script.

## Key documentation

- [`docs/documentation-model.md`](docs/documentation-model.md) — how the project docs are organized and kept current (read first).
- [`docs/index.md`](docs/index.md) and `tooling/`/`viewer/`/`service/` `docs/index.md` — per-scope topic-doc indexes; assemble a reading list from these.
- [`docs/capability-enum.md`](docs/capability-enum.md) — the three places a `cap:` enum entry must touch (enum → generated vocab → hand-added viewer icon). Easy to forget; it has bitten us.
- [`docs/arch-plugin.md`](docs/arch-plugin.md) — the `arch/` plugin that packages the producer-onboarding tooling (seed skill, update agents, manual, validator) and installs into `~/.claude/`.
- [`docs/deployment.md`](docs/deployment.md) — self-hosted K8s/Jenkins context; the container artifact is the deliverable.
- `../ArchitectureSpecs/decisions.md` — the thin `DNNN` decision index. `../ArchitectureSpecs/slices/README.md` — the slice index.
- `/major-change`, `/minor-change` — the dev-session change workflows.
