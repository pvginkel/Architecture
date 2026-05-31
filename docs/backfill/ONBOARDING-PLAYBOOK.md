# Architecture producer onboarding — playbook

A reusable, end-to-end procedure for onboarding repos as producers in the
webathome.org federated Architecture-as-Code system, distilled from the May 2026
backfill that onboarded 17 producers (21 app products) in one pass. Use it for the
next batch.

The federation model, vocabulary, and rules are in
`~/.claude/architecture/producer-manual.md` (authoritative). This playbook is the
*operational* layer: how to discover the work, drive headless seeding at scale,
apply the house conventions, review, and land it.

---

## 0. Mental model

- One **producer** = one repo (or one subtree of a monorepo) that emits
  `docs/architecture/*.yaml` per build. Its `producer:` envelope key is a bare
  kebab id.
- A producer owns its app's **logical architecture**: the «SoftwareProduct»
  identity, the ApplicationService(s)/Interface(s) it exposes, capabilities it
  realizes, and its outbound consumption edges. It does **not** own the running
  instance / node placement (that's the deployer — helm-charts).
- Cross-producer references are **by UUID**, resolved from the published dataset
  `https://architecture.webathome.org/data/v0.1/architecture.yaml`. A reference to
  a not-yet-published producer dangles (reported, not fatal).
- Seeding is **hand-authored** mode: mint uuid4 once per element, never re-mint.

---

## 1. Build the work list (app → image → source repo)

Goal: a table mapping each missing product to the repo that builds its image.

1. **Backlog** — the Architecture Trello board (`board 6a1ac2ea2963a48bb0b6ab76`),
   list **Backlog** (`6a1ac2f2270770954432c7cf`), holds `Onboard producer for
   app:<name>` cards. These come from deferred cross-producer refs the helm-charts
   producer emits.
2. **app → image** — grep the helm chart artifacts:
   `grep -rn "app:" /home/pvginkel/source/HelmCharts-2/charts/*/architecture.yaml`
   (each line is `<image>: app:<product>`). **Note:** the live charts are in
   `HelmCharts-2`, not `HelmCharts` (the latter has no `architecture.yaml`).
3. **image → repo** — the `registry:5000/<image>` **kaniko build destination** in
   a repo's Jenkinsfile. Don't trust mere references (validation/integration images
   are pulled, not built); find the `helmCharts.kaniko([... "registry:5000/<image>:..." ...])`
   destination. Confirm against **gitblit HEAD** (MCP `mcp__gitblit__*`), not local
   checkouts — see the stale-monorepo gotcha below.
4. Record everything in a JSON map (see `repos.json` from the last run) with a
   confidence level and notes, and a `decisions.md` for non-trivial calls. Surface
   ambiguities to the operator before seeding — do not guess.

### What is *not* a producer to onboard
- **Upstream/third-party images** (e.g. `ha-mcp` = `ghcr.io/...`). The deployer
  (helm-charts) owns these as upstream products; don't onboard a producer.
- **Apps already owned by DockerImages** (document-conversion, scan-server,
  esp32-coredump-parser, etc.) — absent from the backlog by design.
- **The viewer** is built from the Architecture repo itself → it belongs in the
  `architecture` self-producer (`docs/architecture/`), not a new repo.

---

## 2. The headless seeding harness

Seeding the skill must run in a *top-level* `claude` session (it fans out Explore
sub-agents; a sub-agent can't). So we run **one headless `claude` per repo** as a
subprocess. Three scripts under `docs/backfill/` (generalized from
`DesignAssistant/scripts/claude_session.py`):

### `seed_repo.py` — headless runner
Wraps `claude --print --verbose --dangerously-skip-permissions --output-format
stream-json` with cwd = the cloned repo, prompt via stdin, stream-json progress
parsed to a log, session-id captured for `--resume`, PID-namespace kill on timeout.
```
docs/backfill/seed_repo.py start  --name <producer> --repo-dir tmp/backfill/<Repo> \
    --prompt-file docs/backfill/prompts/<producer>.md --timeout 3600
docs/backfill/seed_repo.py resume --name <producer> --repo-dir ... --prompt-file <followup.md>
```
Outputs: `docs/backfill/runs/<producer>.{log,response.md,session.json}`. Key impl
notes: it pops `CLAUDECODE` from the env; reads stdout via `select()` with a
deadline; extracts `result`/`session_id` from the stream-json `result` event.

### `gen_prompts.py` — per-repo prompt generator
Encodes the locked **conventions** + **deliverables** + the house
`Jenkinsfile.architecture` template **once** (`CONVENTIONS`), and renders one prompt
per producer from a `PRODUCERS` table (producer id, clone url, products list,
role/special notes, optional dependency hints, phase). Cross-producer UUIDs that
aren't published yet (e.g. the just-seeded `svc:ssegateway`) are **hand-injected**
into the consuming prompts (see `SSEGATEWAY_SVC` + `consumes_ssegateway`). Writes
`docs/backfill/prompts/<producer>.md`. Edit the table + re-run to regenerate.

### `run_phase.py` — concurrency-capped batch runner
Runs every producer in a phase through `seed_repo.py` with a thread pool
(`--max N`, default 4), one background task → one completion notification.
```
docs/backfill/run_phase.py B --max 4 --timeout 3600
```

### Prompt anatomy (what each seed session is told)
- Read the producer manual + repo `CLAUDE.md`/`README`/`docs` first; run the
  `/seed-architecture` skill's method but **skip interactive triage** (headless) —
  decide and log to `SEED-NOTES.md` instead of blocking.
- Fixed identity facts (producer id, product «SoftwareProduct» id(s),
  `sourceRepository`, image) so it doesn't re-derive them.
- The locked conventions (Section 4).
- Deliverables (Section 5).
- "No commits/pushes; don't read secret values."

---

## 3. Clone discipline & sequencing

- **Clone fresh, full history, into `./tmp/backfill/<Repo>`** from
  `https://github.com/pvginkel/<Repo>.git`. **Never `--depth 1`** — shallow clones
  break `introduced = git log --reverse --format=%ad --date=short | head -1` (you'd
  get HEAD's date, not the first commit). **Never reuse the working `../<Repo>`
  checkouts** — several were stale monorepos whose gitblit HEAD has since split into
  single-app repos.
- **Providers before consumers** (so cross-producer UUIDs exist to reference):
  - **Phase A**: shared in-house providers first — `ssegateway` (its `svc:` is
    referenced by many backends).
  - **Phase B**: backends + standalone apps (reference Phase-A UUIDs).
  - **Phase C**: UIs (reference their backend's `svc:<…>-api` UUID, read from the
    Phase-B artifact in the sibling `tmp/backfill` clone).
- After Phase A, capture the provider's `svc:` UUID and inject it into the Phase-B
  prompts (regenerate). After Phase B, the UI prompts point at the backend artifact
  path to resolve its API UUID.

---

## 4. Locked modeling conventions (house rules)

These were settled with the operator and are baked into `gen_prompts.py`. Re-confirm
with the operator for a new batch, but they're the defaults:

1. **`introduced` = repo's first commit**, same date on every element in the repo
   (one date for a monorepo's products). Even if older than the app.
2. **External SaaS you actually call → an `ApplicationService` `svc:` element** you
   declare (e.g. `svc:openai-api`, `svc:mouser-api`): `stats.homepage` set, **no**
   «SoftwareProduct», `<app> —Association→ svc`. `boundBy: env:<VAR>` only if an env
   var carries the endpoint; hardcoded SDK base URL → no boundBy. **Do not** mint a
   capability just to hang an external dep on (no `cap:llm-inference`). A URL-rewriter
   /helper that isn't an API you call is OUT.
3. **Substitutable in-house infra → curated `cap:` target** with **required**
   `boundBy`: OIDC→`cap:iam`, SQL→`cap:relational-database`, S3→`cap:object-storage`,
   logging store→`cap:logging`, MQTT/topic→`cap:pub-sub-broker`, task queue→
   `cap:message-queue`, K8s API→`cap:container-orchestration` (via service account →
   no boundBy), source host→`cap:source-control`. Producers **never declare** a
   `capabilities:` block — caps are reference-only.
4. **In-house provider services → reference the provider's specific `svc:<uuid>`**
   (not a cap). A webhook the consumer exposes back to the provider (e.g. the SSE
   gateway callback) is an implementation detail → model ONE consumption edge, not a
   second interface.
5. **Operational surfaces are OUT**: `/metrics`, drain/preStop, health — deployer's
   lens, not the app architecture.
6. **Exposed API**: ONE `ApplicationService` realized by the product, ONE
   `ApplicationInterface` per **distinct consumer class** (group by consumer, never
   per route). Most apps: a single UI/SPA consumer.
7. **Pure frontends/static sites DO expose** a `svc:<…>-web` + browser interface (so
   the deployer can attach the public host). Frontends that wrap/embed other UIs
   model `Association` edges to those wrapped services.
8. **App→app edges**: model **frontend→backend** (UI consuming its backend API, and
   the live SSE stream if it subscribes). Don't model trivial backend→frontend pings.
9. `environment`/`cluster` stay **unset** (logical type-level surfaces span envs).
10. **Find outbound deps** with `grep -rIi '://'` (triage out docs/schema URLs) in
    addition to an env-var/config scan — hardcoded base-URL constants hide from env
    scans. (Now in the seed skill.)
11. **Snippet home**: append the producer snippet from
    `~/.claude/architecture/claude-md-snippet.md` to `CLAUDE.md` (often a symlink →
    `AGENTS.md`; appending follows the link). `<ARCH-PATH>` = `docs/architecture/architecture.yaml`.

### Special repo shapes
- **Monorepo, one root Jenkinsfile, N products** (DesignAssistant): one producer, one
  artifact declaring all N «SoftwareProduct»s; root `Jenkinsfile.architecture`.
- **Packaging repo** (MyDownloads bundles artifacts from a server repo + an Android
  client): the deployed-image repo is the producer home; model the logical app +
  real deps; the client is its own (future) producer.
- **Cross-wired build** (a Jenkinsfile in repo X that clones repo Y): the source is
  the cloned repo; confirm with the operator (we hit a renamed-repo + GitHub-redirect
  case).

---

## 5. Per-repo deliverables

Written into the working tree; never committed by the seed session:
1. `docs/architecture/architecture.yaml` — `producer: <id>`, the artifact.
2. `docs/architecture/SEED-NOTES.md` — every non-trivial decision + open questions
   (kept; it's the review surface and the audit trail).
3. `scripts/arch-validate.py` — `cp ~/.claude/architecture/arch-validate.py`, `chmod +x`.
4. `Jenkinsfile.architecture` at the repo root (or the subtree, for a per-subtree
   producer) — house style: `library('JenkinsPipelineUtils')`, `jenkins-agent` +
   `containerTemplates.python('python')`, clone via `git ... credentialsId
   '5f6fbd66-b41c-405f-b107-85ba6fd97f10'`, then `sh './scripts/arch-validate.py
   docs/architecture/*.yaml'` and `archiveArtifacts 'docs/architecture/*.yaml'`.
   Isolated from the app build pipeline.
5. CLAUDE.md/AGENTS.md producer snippet appended.

---

## 6. Validate & cross-check

- Per file: `./scripts/arch-validate.py docs/architecture/*.yaml` must exit 0.
  (It checks schema, id grammar, ArchiMate triple matrix — NOT cross-producer refs.)
- **Cross-producer resolution sweep** (catches typos in hand-edits; the merge does
  this for real): collect every declared composite id UUID across the whole corpus
  (this repo's `docs/architecture/*.yaml` + all `tmp/backfill/*/docs/architecture/*.yaml`
  + DockerImages `*/architecture.yaml` + `HelmCharts-2/docs/architecture/*.yaml`) and
  every `source:`/`target:` UUID in relations; report referenced-but-undeclared. The
  only legitimate misses are refs to producers not in your local corpus — verify
  those against the published dataset.

---

## 7. Review loop with the operator

1. Produce a consolidated **`REVIEW.md`**: inventory table (elements/relations per
   producer), wiring verification, **cross-cutting decisions** (call out
   inconsistencies the parallel runs produced — they're the signal), per-producer
   open questions (condensed from each `SEED-NOTES.md`), base-set candidates, and
   anything unresolved. Index-only: point at the `tmp` artifacts + SEED-NOTES rather
   than copying them.
2. Operator answers inline by prefixing lines with **`ANSWER:`**.
3. Convert answers into a structured **`review-N-todo.md`** (sections: new seeds,
   per-artifact edits, self-producer additions, base-set consolidation, Trello
   backlog cards, finalization). Work top-down, check items off as you go.
4. Most edits are **surgical hand-edits** to the `tmp` artifacts (you know the model
   by now); re-validate after each. New full producers can still go through the
   harness — unless you're rate-limited (see gotchas), in which case hand-author.

### Recurring decisions worth pre-asking the operator
- Pure-frontend service modeling (yes, model it) · frontend→gateway edges (keep) ·
  capability mapping for shared infra · external SaaS as `svc:` not `cap:` ·
  `introduced` = first commit · snippet → AGENTS.md when no CLAUDE.md.

---

## 8. Base-set consolidation (post-run)

After a batch, find external `svc:` elements declared by **>1 producer** (e.g.
`svc:openai-api` appeared 3×, each with its own UUID). Lift one canonical element
into the `architecture` self-producer (`docs/architecture/external-services.yaml`)
and repoint consumers to that UUID; remove their local declarations. Single-use
externals stay local until reuse appears. (Detect with: collect `id: svc:` per
producer and look for the same hint across producers.)

---

## 9. Landing it

- **Producer repos**: commit (artifact + SEED-NOTES + scripts/arch-validate.py +
  Jenkinsfile.architecture + CLAUDE/AGENTS snippet) and push to `main`. The clones in
  `tmp/backfill` have `origin` = GitHub and are on `main`; `git add -A` is safe
  because a fresh clone only contains the seed's changes (verify `git status` first).
  Commit message: "Add federated architecture producer artifact" + the
  `Co-Authored-By` trailer.
- **Architecture repo** (self-producer): viewer/scanning/external-services additions
  + `pipeline-producers.yaml` registration. Commit directly (no PR) — but only when
  the operator says so; they may want to handle these manually.
- **Registration**: add each producer to `pipeline-producers.yaml`
  (`id` + `jenkinsJob: "<RepoJob> Architecture"`). The architecture Jenkins jobs
  (pointing at each `Jenkinsfile.architecture`) must be **created in Jenkins** before
  registration does anything — operator's CI glue.
- File any deferred modeling as **Trello backlog cards** (e.g. Keycloak management
  interface; device fleets; client-app producers).

---

## 10. Gotchas & lessons (read before the next batch)

- **`HelmCharts-2`, not `HelmCharts`**, holds the chart `architecture.yaml`s.
- **Stale local monorepos**: `../DHCPApp`, `../ElectronicsInventory`, `../IoTSupport`,
  `../ZigbeeControl`, `../GitblitMCPServer` are old `backend/`+`frontend/` (or
  `plugin/`+`server/`) monorepos; gitblit HEAD has split them into single-app repos
  with the frontend in a separate `*UI` repo. Always trust gitblit HEAD + clone fresh.
- **Shallow clone breaks the `introduced` date** — full clones only.
- **`CLAUDE.md` is frequently a symlink → `AGENTS.md`** in these repos; the snippet
  lands in `AGENTS.md` (fine). Repos with no CLAUDE.md get one created or the snippet
  in AGENTS.md.
- **Account session limit**: a parallel fleet of headless `claude` sessions can trip
  the account session/usage limit mid-run ("You've hit your session limit"). Keep
  `--max` modest, and be ready to **hand-author** a stuck producer in the main
  session (you have the conventions; it's just YAML).
- **Harness output-channel fault**: one long run (electronics-inventory, ~27 min)
  hit a transient tool-output fault and recovered via delegated agents — give
  outlier-duration runs extra scrutiny on review.
- **kaniko destination ≠ reference**: validation/integration images appear in
  Jenkinsfiles but aren't built there; map by the build destination only.
- **Don't over-model**: operational surfaces, browser-side CDNs, intra-product
  plumbing, and doc-drift fixes are out of scope. Default borderline to OUT.

---

## 11. Artifacts from the May 2026 run (reference)
- `repos.json` — the app→image→repo map + confidence/notes.
- `decisions.md` — locked conventions + base-set candidates + run outcome.
- `prompts/<producer>.md` — generated seed prompts.
- `runs/<producer>.{log,response.md,session.json}` — per-run logs/summaries.
- `REVIEW.md` — the operator review surface (with inline `ANSWER:` lines).
- `review-1-todo.md` — the worked review-round todo.
- `seed_repo.py`, `gen_prompts.py`, `run_phase.py` — the harness.
