# Metaschema + validation service — superseded

This document was the initial breakdown of `02-metaschema.md` into a feature plan. It has been split into two standalone feature documents so each can be executed independently:

- [`metaschema-design.md`](./metaschema-design.md) — the schema package: per-kind schemas, enum files, master artifact wrapper, versioning policy. Execute first.
- [`validation-service.md`](./validation-service.md) — the runtime container: Node/Express service, `POST /api/validate`, schema publication URLs, `arch-validate` dev CLI, `USAGE.md` at the container root, Prometheus, Helm deploy. Execute once the schema design lands.

The conversation that produced the split is preserved in commit history (see `e1eb07e` and successors).

Inspiration for both docs: [`../architecture-rebuild/02-metaschema.md`](../architecture-rebuild/02-metaschema.md). That doc is the brainstorm; the two feature docs above are the specs to execute against.
