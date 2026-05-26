# Architecture

The architecture diagram for [webathome.org](https://webathome.org), extracted into its own repo.

Served as a standalone container at `architecture.webathome.org/viewer` and embedded back into webathome.org via iframe.

## Layout

```
viewer/      # React + ReactFlow SPA (Vite)
scripts/     # dev helpers
docs/        # planning docs (architecture-rebuild) and deferred decisions
Dockerfile   # multi-stage build → nginx
Jenkinsfile  # placeholder, wired against the homelab stack
```

## Develop

```
./scripts/dev.sh
```

Opens the viewer dev server at `http://localhost:5173/viewer/`.

## Build the container

```
docker build -t architecture .
docker run --rm -p 8080:80 architecture
# open http://localhost:8080/viewer/
```

## Plan

See [`docs/architecture-rebuild/`](docs/architecture-rebuild/) — these planning docs travel with the repo and define the full multi-phase rebuild. v0 (this commit) is "01-repo-extraction".
