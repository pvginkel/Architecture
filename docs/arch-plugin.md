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

The marketplace source is a **local path**, so the plugin is read live from this checkout —
editing files under `arch/` takes effect without reinstalling (if a refresh is ever needed,
`/plugin marketplace update architecture`). Installing from the local checkout does **not**
require the repo to be pushed first. For a throwaway session without installing at all,
`claude --plugin-dir arch` loads it for that session only.

Component invocation once installed: the skill is `/arch:seed-architecture` (skills are
plugin-namespaced); the agents are referenced by their bare names `update-architecture` /
`update-architecture-generated` (plugin agents are not namespaced, and a same-named
`.claude/agents/` file would override the plugin's).

## Editing

Edit the files under `arch/` directly and reinstall. When a change also affects how producers
are onboarded (new vocabulary in the manual, a changed skill step, a new validator flag),
reflect it in the producer manual and, if it changes onboarding mechanics, in
[`backfill/ONBOARDING-PLAYBOOK.md`](backfill/ONBOARDING-PLAYBOOK.md).
