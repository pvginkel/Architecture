# Architecture backfill — decisions & working notes

Working folder for backfilling `docs/architecture/architecture.yaml` into every
in-house app repo that the Architecture board's **Backlog** flags as a missing
producer. This doc records every non-trivial decision; `repos.json` is the
machine-readable app→repo map. Nothing is committed or pushed until we agree.

## Scope

- **Source of the list:** 23 `Onboard producer for app:*` cards in the Backlog
  list of the Architecture Trello board.
- **app → image:** taken from `HelmCharts-2/charts/*/architecture.yaml`
  (`images: <image>: app:<product>`).
- **image → repo:** the `registry:5000/<image>` kaniko build destination in each
  repo's Jenkinsfile, confirmed against **gitblit HEAD** (not the local
  checkouts — several are stale, see below).

## Key findings

### 1. `../HelmCharts` vs `HelmCharts-2`
You named `../HelmCharts`, but it has **no** `architecture.yaml` files — they all
live in `HelmCharts-2` (which is ahead: it carries the architecture-build
commits). All mapping was done from `HelmCharts-2`. Flagging in case the working
copy you intend differs.

### 2. Local monorepo checkouts are stale
`../DHCPApp`, `../ElectronicsInventory`, `../IoTSupport`, `../ZigbeeControl` are
old **monorepos** (`backend/` + `frontend/`, per-subdir Jenkinsfiles). Their
**gitblit HEAD is now a single backend-only app** (one `app/`, one root
`Jenkinsfile` + `Dockerfile`), and the frontends have been split into standalone
repos (`DHCPAppUI`, `ElectronicsInventoryUI`, `IoTSupportUI`, `ZigbeeControlUI`).
**Consequence:** I will clone fresh from gitblit/GitHub into `./tmp/backfill/`,
never reuse the stale local dirs. Each of these is then a standard single-app
repo with a root Jenkinsfile.

### 3. Clone host
Repos with a remote point at `github.com/pvginkel/<Repo>.git`; gitblit is the
mirror + search index. Plan: clone from GitHub into `./tmp/backfill/<Repo>`.
(Open: whether all are reachable without extra credentials — see questions.)

## Special cases (flagged in repos.json)

- **`app:ha-mcp` has no in-house repo.** The image is the upstream
  `ghcr.io/homeassistant-ai/ha-mcp`. Per the manual's ownership rules a
  repackaged/upstream image is owned by the **deployer** (helm-charts) as an
  upstream product, not onboarded as a producer. The chart comment claiming a
  future source repo is inaccurate. **Recommend dropping it from onboarding**
  and instead fixing it in helm-charts.
- **`app:architecture-viewer` is built from THIS repo** (`pvginkel/Architecture`,
  `registry:5000/architecture_viewer`). This repo is already the `architecture`
  self-producer (`docs/architecture/{infrastructure,home-automation}.yaml`). So
  its product/services belong **here**, not in a new repo — fold into the
  existing self-producer files (or a new `docs/architecture/viewer.yaml`).
- **`GitblitMCPServer` is a 2-app monorepo with NO root Jenkinsfile** —
  `plugin/Jenkinsfile` builds `gitblit-initializer`, `server/Jenkinsfile` builds
  `gitblit-mcp-server`. One producer covering both, but where do
  `docs/architecture/` and `Jenkinsfile.architecture` go (root)? And what's the
  producer id?
- **`MyDownloads` is a packaging repo.** Its image bundles `copyArtifacts` from
  `MyDownloadsServer` (real server source) + `MyDownloadsClient` (Android APK).
  The deployed image identity lives in `MyDownloads.git`, so that's the natural
  producer home, but the actual app logic is elsewhere.
- **`app:design-assistant*` = one monorepo, 5 products.** `DesignAssistant.git`
  builds all five via one root Jenkinsfile (per your note, `Jenkinsfile.architecture`
  goes in root). One producer `design-assistant` emits all five product entries
  in a single `architecture.yaml`. `document-conversion` is built/referenced here
  but **owned by DockerImages** — not emitted as a product by this producer.

## Out of scope (already covered by the DockerImages producer)
Apps whose source lives in `DockerImages` are deliberately absent from the
Backlog and will NOT be seeded here: `document-conversion`, `scan-server`,
`scanned-image-processing`, `esp32-coredump-parser`, `calendar-support`,
`infra-statistics`, `git-sync`, `backup-server`, `rclone-backup`,
`registry-cleanup`, `version-poller`, `nginx-configurator`, `certbot`,
`dnsmasq-*`, `elasticsearch-setup`.

## Planned per-repo procedure (after questions are resolved)
For each in-scope repo:
1. Clone fresh into `./tmp/backfill/<Repo>`.
2. Run the `seed-architecture` skill (survey → triage → author →
   `scripts/arch-validate.py`), producing `docs/architecture/architecture.yaml`.
3. Copy `arch-validate.py` to `scripts/arch-validate.py`.
4. Add `Jenkinsfile.architecture` next to the repo's Jenkinsfile (separate from
   the app build) — validate + archive stages.
5. Add the CLAUDE.md producer snippet (`claude-md-snippet.md`) to the repo's
   CLAUDE.md.
6. Record every modelling decision back into this doc.
7. (Later, on your go) prepare `pipeline-producers.yaml` entries.

Nothing is committed/pushed until reviewed.

## Resolved decisions (2026-05-30)

1. **`app:ha-mcp` — dropped from onboarding.** Upstream image; helm-charts will
   own it as an upstream product. Not seeded. (Chart-comment fix tracked separately.)
   Now **19 in-scope apps** across **18 producers** (design-assistant = 5 apps, 1 producer).
2. **`app:architecture-viewer` — new `docs/architecture/viewer.yaml` in THIS repo**
   under the existing `architecture` self-producer. No clone.
3. **`GitblitMCPServer` — two separate producers** (`gitblit-initializer`,
   `gitblit-mcp-server`). Each gets its own architecture artifact +
   `Jenkinsfile.architecture` alongside its existing subdir Jenkinsfile
   (`plugin/`, `server/`).
4. **Execution — sub-`claude` process per repo.** A wrapper (`seed_repo.py`,
   based on DesignAssistant's proven `claude_session.py`) launches a headless
   `claude` in each cloned repo so the seed skill runs in its own clean context
   and can still fan out Explore agents. **Trial one repo first** (ElectronicsInventory),
   review, then roll out (parallelizable). Headless ⇒ no live triage: the prompt
   pre-bakes scope/producer-id and instructs the sub-session to author best-effort,
   validate, and write a per-repo decisions file listing every assumption/uncertainty
   for human review rather than blocking on questions.

## Modeling conventions (locked — deep dive 2026-05-30, pilot = electronics-inventory)

These bake into every per-repo seed prompt:

1. **External SaaS we actually call → `svc:` ApplicationService**, declared by the
   consuming producer, NO «SoftwareProduct», `stats.homepage` set, edge
   `app —Association→ svc:<ext>` with **no `boundBy`** when the endpoint is a
   hardcoded base-URL constant (the common case). Examples: `svc:openai-api`,
   `svc:mouser-api`. NOT a capability — do **not** mint `cap:llm-inference`
   (reversed; minting a cap just to hang an edge is backwards). A URL-rewriter or
   helper that isn't a consumed API (e.g. LCSC datasheet URL rewriting) is **out**.
2. **No `cap:llm-inference`** added to the enum.
3. **External `svc:` elements are second-pass candidates** to lift into the
   Architecture repo's base set once reuse appears (esp. `svc:openai-api`). Keep a
   running list in this doc; do a dedicated consolidation pass after the initial run.
4. **SSE-gateway callback is an implementation detail**, not a second interface:
   model one edge `app —Association→ svc:ssegateway-<…> boundBy env:SSE_GATEWAY_URL`.
   The webhook the app exposes is conceptually part of the gateway's own interface.
5. **Operational surfaces are out**: `/metrics` (Prometheus scrape), drain/preStop
   endpoints — they belong to the helm-charts deployment lens, not the app architecture.
6. **frontend → backend edges: yes** (authored by the UI producer, referencing the
   backend's `svc:<…>-api` UUID). **backend → frontend: no** (e.g. a version-check
   call is too trivial). ⇒ **providers seed before consumers**: ssegateway →
   backends → UIs.
7. **`introduced` = the repo's TRUE first commit**
   (`git log --reverse --format=%ad --date=short | head -1` on a FULL clone — NOT a
   `--depth 1` shallow clone, which only sees HEAD). For a monorepo, the **same**
   repo-first-commit date applies to all products it emits. (Caveat accepted: for
   the split backend/UI repos this is the split date, not the app's true inception.)
8. **Survey method**: find outbound deps with `grep -rIi '://'` (now baked into the
   seed skill) in addition to env-var scans, triaging out docs/schema URLs — base-URL
   constants in code don't show up as env vars. (Pilot's first run missed Mouser +
   Google favicon because it only read one config file.)

## Pilot status
`electronics-inventory` trial validated the subprocess pipeline but predates these
conventions (3 edges, no external svc, wrong date from shallow clone). It will be
**re-seeded to the full standard** as part of the ordered run (after ssegateway).

## Base-set migration candidates (for the post-run second pass)
- `svc:openai-api` — **confirmed reused 3×** (design-assistant, electronics-inventory,
  newsfilter), each with a different minted uuid → consolidate to one base element.
- Single-use externals to promote only on reuse: `svc:gmail-api`, `svc:mouser-api`,
  `svc:ieee-oui`, `svc:google-favicon`, `svc:twitter-api`, and the mydownloads set
  (`plex`, `imdb`, `thetvdb-api`, `opensubtitles-api`, `eztv`, `fcm`, `ifconfig-co`).

## Initial run outcome (2026-05-30)
21/22 in-scope app products seeded across 17 producers, all validate clean. Outstanding:
`gitblit-initializer` (source repo ambiguous — cross-wired build). Full results +
cross-cutting decisions + per-producer open questions: `docs/backfill/REVIEW.md`.

## Still open
- Whether helm-charts bare-hint `app:*` refs get rewritten to the newly-minted
  UUIDs as part of this effort or separately.
