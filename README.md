# Architecture

The architecture diagram for [webathome.org](https://webathome.org), extracted into its own repo.

Served as a standalone container at [`architecture.webathome.org/viewer`](https://architecture.webathome.org/viewer/) and embedded back into webathome.org via iframe.

## Layout

```
viewer/      # React + ReactFlow SPA (Vite)
  src/         components, layout, data, postMessage bridge
  public/      logos served at /viewer/logos/
  nginx.conf   serves the build with /viewer/ base + CSP for the iframe parents
scripts/
  dev.sh       wrapper for `npm run dev` from the repo root
docs/
  architecture-rebuild/  multi-phase rebuild plan (v0 = this repo)
  todo.md                deferred decisions
Dockerfile     multi-stage: node build → nginx
Jenkinsfile    homelab Jenkins + Kaniko pipeline
```

## Develop

```
./scripts/dev.sh
```

Vite dev server on `http://localhost:5173/viewer/`. Configured for remote access via `http://wrkdev:5173/viewer/`.

## Build the container

```
docker build -t architecture .
docker run --rm -p 8080:80 architecture
# open http://localhost:8080/viewer/
```

## Iframe contract

The viewer is designed to live inside an iframe on webathome.org. It speaks a small `postMessage` protocol with the parent (`viewer/src/parent-bridge.ts`):

- Outbound: `{ type: "ready" }` on mount, `{ type: "view-change", view: <json> }` on filter changes.
- Inbound: `{ type: "set-view", view: <json> }` to deep-link into a named filter state.

Origin is locked to `https://webathome.org`. No consumers yet.

## Plan

See [`docs/architecture-rebuild/`](docs/architecture-rebuild/) — the multi-phase rebuild plan. v0 ("01-repo-extraction") is the current state. Later phases add a metaschema, federated producers, a collector, and a richer data model.
