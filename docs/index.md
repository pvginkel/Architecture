# Architecture docs

Root-scope project documentation for the `Architecture` repo — cross-cutting and system-level
design, organized per the [documentation model](documentation-model.md). Per-subproject design
lives in `tooling/docs/`, `viewer/docs/`, and `service/docs/`.

Each entry is one topic doc plus a precise line on what's inside, so a change's reading list can
be assembled without opening them all.

## Topic docs

- [documentation-model.md](documentation-model.md) — how the whole doc set is organized and kept current (read first).
- [deployment.md](deployment.md) — the self-hosted stack the container artifact ships into (K8s/Jenkins/Kaniko/Ansible); what's in scope here vs the operator's.
- [capability-enum.md](capability-enum.md) — the three places a `cap:` enum entry must touch (enum → generated vocab → hand-added viewer icon).
- [architecture-process-sync.md](architecture-process-sync.md) — the two-way sync between `architecture-process/` and the operator's `~/.claude/` producer-onboarding files.

## Not topic docs

`docs/architecture/*.yaml` is this repo's **own** published architecture artifact (the
self-producer dataset), not workflow documentation. `docs/backfill/` and
`docs/iotsupport-iot-architecture-guidance.md` are likewise data/guidance, not topic docs.
