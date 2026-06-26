# architecture-process/ ↔ ~/.claude/ sync

`architecture-process/` is a snapshot of the operator-side files that drive the
producer-onboarding workflow. The live copies are in the operator's `~/.claude/`:
`~/.claude/architecture/` (producer manual, starter `architecture.yaml`, `arch-validate.py`,
`claude-md-snippet.md`), `~/.claude/skills/seed-architecture/SKILL.md`, and
`~/.claude/agents/{update-architecture,update-architecture-generated}.md`. These onboarding
agents/skills are **global** — they are not copied into this repo.

Treat this as a **two-way merge** — either side can move first:

- When the operator edits a file under `~/.claude/...`, mirror it into the matching path under
  `architecture-process/` (and commit here).
- When something under `architecture-process/` is edited here (review fixes, doc updates that
  came up in conversation), mirror it back to the corresponding `~/.claude/...` path.

Filename map:

| `~/.claude/...` | `architecture-process/...` |
|---|---|
| `architecture/producer-manual.md` | `producer-manual.md` |
| `architecture/architecture.yaml` | `architecture.yaml` |
| `architecture/arch-validate.py` | `arch-validate.py` |
| `architecture/claude-md-snippet.md` | `claude-md-snippet.md` |
| `skills/seed-architecture/SKILL.md` | `skills/seed-architecture/SKILL.md` |
| `agents/update-architecture.md` | `agents/update-architecture.md` |
| `agents/update-architecture-generated.md` | `agents/update-architecture-generated.md` |

Diff both sides before editing — if they've drifted, surface the drift to the operator rather
than silently picking a side.
