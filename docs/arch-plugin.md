# The `arch` plugin

`arch/` is a Claude Code **plugin** that packages the operator-side producer-onboarding
tooling for the webathome.org federated Architecture-as-Code system. It is the **single
source of truth** for that tooling: it lives in this repo and is installed into the
operator's `~/.claude/`. There is no longer a hand-maintained `~/.claude/` mirror to keep
in sync — this directory is the original.

## What it bundles

| Path | Kind | Role |
|---|---|---|
| `arch/.claude-plugin/plugin.json` | manifest | plugin name (`arch`), version, metadata |
| `arch/skills/seed-architecture/SKILL.md` | skill | one-shot: author a repo's first `architecture.yaml`, invoked `/arch:seed-architecture` (fans out Explore agents, so it must run in the main loop — that's why it's a skill, not an agent) |
| `arch/agents/update-architecture.md` | agent | incremental upkeep for a **hand-authored** producer |
| `arch/agents/update-architecture-generated.md` | agent | incremental upkeep for a **generated** producer (edits the annotation layer / generator, never the output) |
| `arch/references/producer-manual.md` | reference | the authoritative vocabulary / ID-grammar / inclusion-rule / relation-matrix manual — read on startup by all three components |
| `arch/assets/architecture.yaml` | asset | starter skeleton the seed skill drafts from |
| `arch/assets/claude-md-snippet.md` | asset | the federated-architecture block dropped into a producer repo's `CLAUDE.md` |
| `arch/scripts/arch-validate.py` | script | submits artifacts to the validation service; producer repos also copy it to their own `scripts/arch-validate.py` for CI |

## Why a plugin (not a single skill)

The set is one skill plus two agents plus shared docs/scripts. A single skill can't hold
agents, and the skill/agent split is deliberate: `seed-architecture` fans out parallel
Explore sub-agents (only possible from the main conversation), while the `update-*` agents
run in isolated context and are nudged from a producer repo's `CLAUDE.md`. A **plugin** is
the container that holds all three component types plus their shared resources.

## Self-contained paths

The skill and agents reference the shared bundled resources via `${CLAUDE_PLUGIN_ROOT}/…`
(e.g. `${CLAUDE_PLUGIN_ROOT}/references/producer-manual.md`,
`${CLAUDE_PLUGIN_ROOT}/scripts/arch-validate.py`) — the portable path variable Claude Code
sets to the plugin's install location. There are no absolute `~/.claude/…` paths inside the
plugin, so it works wherever it is installed.

## Installation

This repo is itself a local Claude Code **marketplace**:
[`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) (marketplace name
`architecture`) lists the `arch` plugin with `source: ./arch`. Install it into `~/.claude/`
by running, from a checkout of this repo:

```
/plugin marketplace add .
/plugin install arch@architecture
```

Installing **snapshots** the plugin into
`~/.claude/plugins/cache/architecture/arch/<version>/`, pinned to the repo's current commit —
it is a copy, not a live reference. After editing files under `arch/`, run
`/plugin marketplace update architecture` to re-snapshot (and restart the session if a changed
skill doesn't reappear — skills register at session start, not reliably on `/reload-plugins`).
Installing from the local checkout does **not** require the repo to be pushed first. For a
throwaway session that loads the plugin live from the working tree, `claude --plugin-dir arch`.

Component invocation once installed differs by kind. The **agents** are available *only*
namespaced — `arch:update-architecture` / `arch:update-architecture-generated`; the bare names
do not resolve, so every reference that spawns them (the producer `CLAUDE.md` snippet, the
manual, the agents' cross-references) uses the `arch:` form. The **skill** resolves *either*
way — `/seed-architecture` and `/arch:seed-architecture` both select it — so references to it
may use whichever reads best. (A same-named `.claude/agents/` file in a repo would override
the plugin's agent of that name.)

## Editing

Edit the files under `arch/` directly and reinstall. When a change also affects how producers
are onboarded (new vocabulary in the manual, a changed skill step, a new validator flag),
reflect it in the producer manual and, if it changes onboarding mechanics, in
[`backfill/ONBOARDING-PLAYBOOK.md`](backfill/ONBOARDING-PLAYBOOK.md).
