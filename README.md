# Architecture

The architecture diagram for [webathome.org](https://webathome.org), extracted into its own repo.

Served as a standalone container at [`architecture.webathome.org/viewer`](https://architecture.webathome.org/viewer/) and embedded back into webathome.org via iframe.

## Layout

```
viewer/      # React + ReactFlow SPA (Vite)
  src/         components, layout, data, postMessage bridge
  public/      logos served at /viewer/logos/
service/     # Node + Express validation service (TypeScript)
  src/         routes (validate, static, usage, metrics, csp), schema loader, error translation
  test/        vitest suite
schema/v0.1/ # JSON Schema metaschema + vendored ArchiMate sources
tooling/     # Python (Poetry): generate.py, validate.py, [collect.py — v3]
scripts/
  arch-validate  bash CLI producer repos copy into their own scripts/
  dev.sh         wrapper for `npm run dev` from the repo root
docs/
  architecture-rebuild/  multi-phase rebuild plan
  features/              feature specs (metaschema-design, validation-service)
USAGE.md     # producer integration docs; rendered at the container root
Dockerfile   # multi-stage: schema-check → viewer build → service build → node runtime
Jenkinsfile  # homelab Jenkins + Kaniko pipeline
```

## Develop

```
./scripts/dev.sh
```

Vite dev server on `http://localhost:5173/viewer/`. Configured for remote access via `http://wrkdev:5173/viewer/`.

## Build the container

```
docker build -t architecture .
docker run --rm -p 8080:8080 architecture
# open http://localhost:8080/         — rendered USAGE.md
# open http://localhost:8080/viewer/  — diagram
# curl http://localhost:8080/healthz  /metrics  /schema/v0.1/architecture.schema.yaml
```

## Iframe contract

The viewer is designed to live inside an iframe on webathome.org. It speaks a small `postMessage` protocol with the parent (`viewer/src/parent-bridge.ts`):

- Outbound: `{ type: "ready" }` on mount, `{ type: "view-change", view: <json> }` on filter changes.
- Inbound: `{ type: "set-view", view: <json> }` to deep-link into a named filter state.

Origin is locked to `https://webathome.org`. No consumers yet.

## Validation service

Producer-facing integration documentation lives in [`USAGE.md`](./USAGE.md): the
`POST /api/validate` contract, schema URLs, the `arch-validate` CLI, and how to
file schema-change requests. It is also rendered at the deployed container root
(`architecture.webathome.org/`).

## Plan

See [`docs/architecture-rebuild/`](docs/architecture-rebuild/) — the multi-phase rebuild plan. v0 ("01-repo-extraction") is the current state. Later phases add a metaschema, federated producers, a collector, and a richer data model.
