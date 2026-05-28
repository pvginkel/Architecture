# Metaschema + validation service — index

The original draft of the metaschema + validation work was a single feature doc. It was split into two standalone documents so each can be executed independently:

- [`metaschema-design.md`](./metaschema-design.md) — the schema package: ArchiMate 3.x subset, vendored XSDs + Archi relationship matrix, the `subset.yaml` declaration, generator tooling, per-kind JSON Schemas, enums, golden examples, and the versioning policy. **Status: v0.1 done; two tightening changes (UUID canonicality + alias hints) pending for the next session.**
- [`validation-service.md`](./validation-service.md) — the runtime container: Node/Express service, `POST /api/validate`, schema publication URLs, the merged-artifact static URLs, the `arch-validate.py` dev CLI, `USAGE.md` at the container root, Prometheus, Helm deploy. **Status: planned; not yet started.**

The conversation that produced the split and the subsequent ArchiMate-adoption pivot is preserved in commit history (see `e1eb07e`, `fa016d4`, and `f0ec35a` and successors).

## Where the rest of the rebuild lives

- [`../architecture-rebuild/00-roadmap.md`](../architecture-rebuild/00-roadmap.md) — phase ordering (the legacy data-migration step is intentionally a no-op; bootstrap is Ansible → Helm → apps).
- [`../architecture-rebuild/02-metaschema.md`](../architecture-rebuild/02-metaschema.md) — original brainstorm, marked superseded; kept for the "why" of decisions that landed in `metaschema-design.md`.
- [`../architecture-rebuild/04-producer-protocol.md`](../architecture-rebuild/04-producer-protocol.md) — how a repo becomes a producer (Jenkins archiveArtifacts, UUIDs canonical, alias hints, label-divergence warning).
- [`../architecture-rebuild/05-collector-and-pipeline.md`](../architecture-rebuild/05-collector-and-pipeline.md) — the Architecture-repo pipeline (Python-in-Docker collector, merged artifact published as static HTTP by the v2 service).
