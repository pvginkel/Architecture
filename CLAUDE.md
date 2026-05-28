# CLAUDE.md

## What this repo is

React + ReactFlow + ELK viewer for [webathome.org](https://webathome.org), built with Vite, served from a container at `architecture.webathome.org/viewer/` and iframe-embedded into webathome.org. Growing into a federated architecture system — see `docs/architecture-rebuild/`.

**Public repo.** No secrets, credentials, internal hostnames/IPs, or non-public names. Assume world-readable.

## About the user

Pieter van Ginkel — Domain Architect at IVO Rechtspraak (Dutch judiciary IT), developer since 2001. Skip beginner framing. Discuss tradeoffs directly.

## `architecture-process/` ↔ `~/.claude/` sync

`architecture-process/` is a snapshot of the operator-side files that
drive the producer-onboarding workflow. The live copies are in
`~/.claude/architecture/` (producer manual, starter `architecture.yaml`,
`arch-validate.py`, `claude-md-snippet.md`) and `~/.claude/agents/`
(`inventory-architecture.md`, `update-architecture.md`).

Treat this as a **two-way merge**. Either side can move first:

- When the user edits a file in `~/.claude/...`, mirror it into the
  matching path under `architecture-process/` (and commit there).
- When something in `architecture-process/` is edited here (review
  fixes, doc updates that came up in conversation), mirror it back to
  the corresponding `~/.claude/...` path.

Filename map:

| `~/.claude/...` | `architecture-process/...` |
|---|---|
| `architecture/producer-manual.md` | `producer-manual.md` |
| `architecture/architecture.yaml` | `architecture.yaml` |
| `architecture/arch-validate.py` | `arch-validate.py` |
| `architecture/claude-md-snippet.md` | `claude-md-snippet.md` |
| `agents/inventory-architecture.md` | `agents/inventory-architecture.md` |
| `agents/update-architecture.md` | `agents/update-architecture.md` |

Diff both sides before editing — if they've drifted, surface the drift
to the user rather than silently picking a side.

## Deployment context

Self-hosted stack: Kubernetes, Jenkins, Kaniko, Ansible. Don't propose hosting alternatives or redesign CI/CD. Focus on the container artifact; K8s/Jenkins glue is the user's.

## Working style

- Commit each meaningful unit without being asked; even a one-line CLAUDE.md edit is its own commit.
- Hand-editing data files is fine; maintenance ergonomics aren't a priority.
- Comfortable with a wide tech stack.

## No defensive coding. No "just in case" infrastructure.

Two flavors of padding to refuse:

- **Fail loudly when things break.** No try/except that swallows errors. No drop-the-bad-input-keep-going paths. No null-guards for conditions the framework already prevents. Boundary validation (schema, user input, external APIs) is the *point*, not defensive coding.
- **Don't add safety nets nothing breaks without.** No scheduled rebuilds "in case triggers are missed." No retries on operations expected to succeed once. No fallback caches or staleness windows without a real observed failure. No belt-and-suspenders checks at adjacent layers. No fall-back-to-old-code paths.

Test before adding a hedge: *what concrete failure does this catch that the current path doesn't?* "Just in case" or "the spec said it'd be nice" isn't an answer. Spec hedges don't override this rule — push back at design time.

Would the failure be obvious now, or silently corrupt the system later? Pick obvious-now.
