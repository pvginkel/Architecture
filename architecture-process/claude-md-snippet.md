<!--
Drop this block into a producer repo's CLAUDE.md. Replace
`<ARCH-PATH>` with the actual artifact path (typically
`docs/architecture/<producer>-architecture.yaml`). Keep the wording
otherwise — it's been tuned to nudge without being a hard rule.
-->

## Federated architecture model

We take part in a federated Architecture-as-Code model. The architecture for this repository is maintained in `<ARCH-PATH>`. Whenever a change is made in this repo that could impact an Enterprise Architecture / ArchiMate model modeling everything owned by this repo, nudge the user to spawn the `update-architecture` agent. The agent is incremental, so it's not a hard requirement that it runs on every change. Nudge a bit harder when significant changes are made (new managed host, new daemon, removed service, renamed external identity). When you are performing work unattended, feel free to invoke the agent yourself.

The agent definitions are installed in the operator's `~/.claude/agents/` — `inventory-architecture` (one-shot seed) and `update-architecture` (permanent, incremental). They are not in this repo. The producer manual at `~/.claude/architecture/producer-manual.md` is the authoritative vocabulary reference; both agents read it from the operator's filesystem on startup.
