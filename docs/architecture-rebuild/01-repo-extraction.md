# 01 — Repo extraction (v0)

Move the current diagram out of webathome.org into a new dedicated repo, serve it as its own container, embed back via iframe. No data changes.

## Why a separate repo

- It will grow much larger than the site (federated producers, schema artifacts, collector code).
- Different build cadence: producer artifacts trigger architecture rebuilds; the site does not need to rebuild for those.
- The schema repo is itself a portfolio artifact — publishing it standalone is a stronger story than burying it inside a personal-site repo.
- Decoupling means the site stays small and fast even as the architecture system grows.

## New repo

**Name:** `pvginkel/Architecture`.

**Layout (target after v0; further dirs added in later phases):**

```
.
├── viewer/                    # the React/ReactFlow app, currently src/components/architecture/
│   ├── src/
│   │   ├── components/        # ArchitectureMap.tsx, layout.ts, etc.
│   │   ├── data/              # architecture.ts (unchanged in v0)
│   │   └── styles/            # architecture.css
│   ├── public/
│   │   └── logos/             # full copy of webathome.org's public/logos/ (see "Logos" below)
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts         # Astro is overkill for a single-page viewer
├── scripts/
│   └── dev.sh                 # one-shot dev-server launcher (see "Dev script" below)
├── Dockerfile                 # nginx serving the built viewer
├── Jenkinsfile                # the user wires this; placeholder here
├── docs/
│   ├── architecture-rebuild/  # these planning docs travel with the move
│   └── todo.md                # deferred decisions captured during v0 (see "Logos" below)
└── README.md
```

The current Astro page is 10 lines of wrapper. Astro is not load-bearing for the diagram — drop it for the new repo and use Vite + plain HTML. Smaller image, faster CI.

## Carry list (exact files from this repo)

- `src/components/architecture/ArchitectureMap.tsx` → `viewer/src/components/ArchitectureMap.tsx`
- `src/components/architecture/layout.ts` → `viewer/src/components/layout.ts`
- `src/data/architecture.ts` → `viewer/src/data/architecture.ts`
- `src/styles/architecture.css` → `viewer/src/styles/architecture.css`
- **All** of `public/logos/` → `viewer/public/logos/` (see "Logos" below — full copy, not just the architecture subset).

Do not carry: `src/pages/architecture.astro` (replaced by `viewer/index.html`).

## Logos

The webathome.org ticker (`src/components/Ticker.astro`) also reads from `/logos/`, so the site cannot lose its copy. For v0: **duplicate**. Copy all logos into `viewer/public/logos/` and leave webathome.org's `public/logos/` intact (the cutover only prunes truly orphaned files — see step 2 below).

Two follow-ups go into `docs/todo.md` in the new repo, to be revisited after v0:

1. **Dedupe vs. page-load performance.** A single-source-of-truth (e.g., serving logos from `architecture.webathome.org/logos/` and having the site reference them cross-origin) is tempting but costs an extra TLS handshake on first paint of the ticker. Cross-origin caching, preconnect hints, and CDN behavior all need to be measured before committing. Until then, duplication is fine.
2. **Logos in the build artifact.** Today the architecture viewer reads logos from `viewer/public/logos/` at build time and they end up baked into the nginx image. Once federated producers (later phases) start contributing nodes, their logos will not live in this repo. Need a story for how producer-supplied logos land in the container image — ingestion at build time? sidecar volume? signed bundles? — before federation lands.

## Dev script

`scripts/dev.sh` in the new repo: a one-line wrapper around `npm run dev` (or `pnpm dev`) so the user can run `./scripts/dev.sh` from the repo root without `cd viewer/`. Roughly:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../viewer"
exec npm run dev -- "$@"
```

Passes through any extra args so `./scripts/dev.sh --host` etc. still work.

Dependencies to copy into `viewer/package.json`: `@xyflow/react`, `react`, `react-dom`, `lucide-react`, `vite`, `@vitejs/plugin-react`, TypeScript toolchain. Pin to the versions currently in webathome.org's `package.json` to avoid behavior drift during extraction.

## Build target

Static HTML + JS + CSS, served by nginx out of a container under the `/viewer` path prefix. Same shape as the webathome.org container — the user has a mature K8s/Jenkins/Ansible stack and explicitly asked to focus on the container artifact (CLAUDE.md).

Concretely:
- `vite.config.ts` sets `base: '/viewer/'` so built asset URLs (`/viewer/assets/...`) match the deployed prefix.
- nginx config serves the built `dist/` from `/viewer/` with an SPA fallback (`try_files $uri $uri/ /viewer/index.html`) scoped to that prefix.
- The container root (`/`) is free for siblings later (health endpoint, `/schema`, etc.). For v0, root can return 404 or a tiny landing redirect — undecided, not blocking.

Dockerfile sketch (the user finalizes):

```
FROM node:20-alpine AS build
WORKDIR /app
COPY viewer/package*.json ./
RUN npm ci
COPY viewer/ ./
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# nginx.conf with cache headers and SPA fallback added inline or via COPY
```

The user wires Jenkinsfile + K8s deploy on their own — not a v0 deliverable.

## Embedding back in webathome.org

**Decision: iframe.** Reasons:

- Strict isolation: the viewer's JS bundle, ReactFlow runtime, and assets stay out of the site's bundle.
- Independent deploy cadence: the architecture container can rebuild without touching the site.
- Same-origin via subdomain (`architecture.webathome.org`) avoids cookie/CORS friction if any later feature needs them. The viewer is mounted at `/viewer` on that subdomain — see "Implementation" below.

**Implementation:**

- New `architecture.webathome.org` subdomain pointing at the new container's service.
- In **this repo (webathome.org)**, rewrite `src/pages/architecture.astro` so the slot content — which lands inside `<main class="content">` in `Base.astro` (already invoked with `fullWidth noFooter`) — is just an `<iframe src="https://architecture.webathome.org/viewer" />`. The site header, toolbar, and chrome stay; only the diagram body is now an iframe. The viewer is mounted under `/viewer` (not the container root) so the host has room for sibling paths later (e.g., `/schema`, `/api`, health endpoints) without colliding with the SPA's client-side routing.
- Iframe styling: 100% width/height of its container (the `<main class="content">` area), no border, `loading="lazy"`. The existing `viewport-locked` body class + `fullWidth` layout already gives the iframe the full content area to fill.
- Add `<link rel="preconnect" href="https://architecture.webathome.org">` on the site to mask handshake latency. Best placed in `Base.astro` so it preconnects on every page, since the toolbar links to `/architecture/` from anywhere.

**postMessage groundwork (do now, even though no message is sent in v0):**

The viewer should be ready to receive and send `postMessage` events because retrofitting cross-frame communication later is annoying. Establish the contract now:

- Viewer accepts messages from the parent origin only (`https://webathome.org`).
- Viewer emits a `ready` message on mount.
- Viewer emits a `view-change` message when the filter state changes.
- Parent can send `set-view` messages to deep-link into a named view.

No consumers in v0. The wiring is one `useEffect` and a tiny message bus. Worth ~30 lines for the optionality.

## Auth, analytics, and SEO

- Auth: none. The viewer is public.
- Analytics: skip in v0. If added later, it goes on the viewer side, not via iframe message-passing.
- SEO: the diagram is interactive content, not crawlable text. No special handling. The site's existing `architecture.astro` page (now an iframe wrapper) keeps its title and meta tags so external links still preview correctly.

## Cutover

1. New repo built and container running at `architecture.webathome.org`. Verify diagram renders identically to the current site.
2. Land a single commit on this repo that:
   - Replaces `src/pages/architecture.astro` with the iframe-only version (iframe is the slot child of `Base.astro` with `fullWidth noFooter`).
   - Deletes `src/components/architecture/`, `src/data/architecture.ts`, `src/styles/architecture.css`.
   - Removes `@xyflow/react` and `lucide-react` from `package.json` (and any other deps no longer used after the move; verify with a build). Note: `lucide-react` may still be used elsewhere — verify before dropping.
   - Deletes only logos that are orphaned **after** accounting for the ticker (`Ticker.astro` reads `public/logos/titles.json` and references files by name). Logos referenced by neither the ticker nor any remaining page can go; everything the ticker still uses stays. Duplication with the new repo is intentional for v0 — see "Logos" above and `docs/todo.md` in the new repo.
   - Adds the `preconnect` hint for `architecture.webathome.org` in `Base.astro`.
3. Site rebuilds smaller and faster. Architecture diagram still works via iframe.

## Exit criteria (repeat from roadmap, with concrete checks)

- [ ] New repo created and pushed.
- [ ] `scripts/dev.sh` starts the viewer dev server from a fresh clone.
- [ ] All logos copied into `viewer/public/logos/` (full set, not just the architecture subset).
- [ ] `docs/todo.md` exists in the new repo with the two logo follow-ups (dedupe vs. perf; producer-supplied logos in the build artifact).
- [ ] Container builds locally via `docker build`.
- [ ] Container deploys to the homelab cluster and is reachable at `architecture.webathome.org/viewer`.
- [ ] `architecture.webathome.org/viewer` renders the diagram with content byte-identical to the current site (visual diff or manual review of all 145 nodes).
- [ ] webathome.org's `/architecture` route renders the iframe inside the existing site chrome (`<main class="content">` slot) and looks unchanged to the user.
- [ ] webathome.org's ticker still renders — its logos were not pruned during the cutover.
- [ ] webathome.org's bundle is smaller than before (verify in the build output).
- [ ] postMessage `ready` event fires when the iframe loads (verify in browser console).
- [ ] These planning docs (`docs/architecture-rebuild/*`) are moved into the new repo.

## What is explicitly not in v0

- No schema work. `architecture.ts` ships with current types and current 145-node data, broken taxonomy and all.
- No `position` field deletion. Even though the field is dead code per the user, it moves untouched. v1 deletes it.
- No new node types, no federation, no Jenkins artifact ingestion.
- No deep-link URL state. Filter state lives in memory only.
