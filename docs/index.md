# Architecture docs

Root-scope project documentation for the `Architecture` repo — cross-cutting and system-level
design, organized per the [documentation model](documentation-model.md). Per-subproject design
lives in `tooling/docs/`, `viewer/docs/`, and `service/docs/`.

Each entry is one topic doc plus a precise line on what's inside, so a change's reading list can
be assembled without opening them all.

## Topic docs

- [documentation-model.md](documentation-model.md) — how the whole doc set is organized and kept current (read first).
- [change-discipline.md](change-discipline.md) — the rules every code change obeys (breaking changes, tombstones, defensive coding, testability, generated artifacts, the public-repo constraint); what each means per component.
- [slice-test-plan.md](slice-test-plan.md) — how a merged slice is proven: the tree-wide suites, the viewer and service live checks, the push and the CI follow-up.
- [slice-doc-plan.md](slice-doc-plan.md) — which doc surfaces a shipped slice must bring up to date, and in what order.
- [deployment.md](deployment.md) — the self-hosted stack the container artifact ships into (K8s/Jenkins/Kaniko/Ansible); what's in scope here vs the operator's.
- [capability-enum.md](capability-enum.md) — the three places a `cap:` enum entry must touch (enum → generated vocab → hand-added viewer icon).
- [arch-plugin.md](arch-plugin.md) — the `arch/` Claude Code plugin that packages the producer-onboarding tooling (seed skill, update agents, manual, validator) and installs into `~/.claude/`.

## Not topic docs

`docs/architecture/*.yaml` is this repo's **own** published architecture artifact (the
self-producer dataset), not workflow documentation. `docs/backfill/` and
`docs/iotsupport-iot-architecture-guidance.md` are likewise data/guidance, not topic docs.
