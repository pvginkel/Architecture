# Slice testing strategy

How a slice is proven once its phases are merged. This is the doc `.aiworkflowrc` names as
`test_phase.strategy`: the run loop's test phase is "read this and execute it", and nothing else
names it. Read it top to bottom and do what it says.

## What this phase proves, and what it does not

**Verification here is local.** This repo has exactly one deployment — production, at
`architecture.webathome.org` — and no dev instance to roll. So the test phase does not deploy
anything and does not verify against a deployed instance. It runs the suites tree-wide and
exercises both live surfaces in this environment, from the merged working tree.

**Production still redeploys, downstream and unattended.** `Jenkinsfile` triggers on
`githubPush()` and its final stage is `cicd.helmDeploy()`, so the push this phase performs (below)
starts a build that ends in a prod rollout. That is the repo's standing behaviour — every push to
`main` has always done it — not something this phase controls. The consequence for ordering is the
whole point of this doc: **everything is verified before the push, because after the push it is
live.**

There is no `devlock`: with no dev instance, nothing contends.

## 0. Preconditions

The driver has ff-merged every code phase into the base branch. Confirm the tree is clean
(`git status --short`) before starting — a dirty tree here means an earlier phase left something
behind, and that is a finding, not something to tidy away.

## 1. The suites, tree-wide

```bash
kc project build      # generate.py --check, viewer tsc+vite, service tsc
kc project test       # root artifact validation, tooling pytest + validate.py meta, viewer/service vitest
```

Both must be green. `kc project build` is also what preflight demands, so a red build here means
the slice never should have reached this phase.

**On `kc project lint`:** `tooling`'s `mypy .` is **known red** — two pre-existing errors in
`collect.py` (tracked as a triage card, not caused by any slice). It predates the pipeline and CI
has never run mypy. Do not treat it as a regression from this slice; do check that the count has
not *grown*, and if the slice touched `tooling/` at all, that clearing it was in scope. Once the
card is fixed, delete this paragraph.

## 2. Live checks

Both surfaces are exercised in this environment. Do both whenever the slice touched `viewer/`,
`service/`, `schema/`, or `tooling/generate.py`; a `tooling`-only or docs-only slice can skip to
step 3 and say so.

### The viewer

```bash
scripts/dev.sh        # Vite in the modern-app sidecar; ^C when done
```

Then load `https://viewer.<env-id>.home/viewer/` (`$KUBECODER_ENVIRONMENT_ID` holds the id) and
confirm the graph renders and the slice's change is visible in it. The dev middleware fetches the
**live published dataset** from `architecture.webathome.org/data/v0.1/architecture.json`, so this
also confirms outbound network and renders against real data rather than a fixture.

### The service

The service resolves `../viewer/dist` and `../dist/data` when run from `service/`, so both have to
exist first. `dist/data` cannot be produced locally — the collector needs a `producer-artifacts/`
tree only the Jenkinsfile assembles — so seed it from the published dataset:

```bash
kc project build --project viewer            # -> viewer/dist
kc project build --project service           # -> service/dist
mkdir -p dist/data/v0.1
curl -sS -o dist/data/v0.1/architecture.json \
  https://architecture.webathome.org/data/v0.1/architecture.json

cd service && cexec modern-app node dist/index.js &   # note the PID
```

Then probe every surface the service publishes:

```bash
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://localhost:8080/viewer/
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://localhost:8080/data/v0.1/architecture.json
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://localhost:8080/schema/v0.1/architecture.schema.json
curl -sS -o /dev/null -w '%{http_code} %{content_type}\n' http://localhost:8080/metrics
curl -sS -X POST --data-binary @docs/architecture/viewer.yaml \
  -H 'Content-Type: application/yaml' http://localhost:8080/api/validate
```

All four GETs answer `200`; the validate POST answers `{"valid":true,"schemaVersion":"0.1"}`. Port
8080 is also published as `https://service.<env-id>.home/`, which is worth one request when the
slice touched the CSP or anything header-related, since the offload path is what production
resembles.

**Kill the service by the PID you captured** — never `pkill -f 'node dist/index.js'`, which matches
the killing shell's own command line. Then `rm -rf dist` and confirm `git status` is clean:
`dist/` is git-ignored but the tree must go back to how it started.

## 3. Check off `verification.json`

Mark each acceptance criterion with the evidence that settled it — the command run and what it
returned, or the surface loaded and what was seen. A criterion nothing in steps 1–2 exercised is
not "passed by inspection"; it is either an untested criterion (a finding) or one whose check
belongs in this doc and is missing from it.

## 4. Push, then confirm CI stayed green

Pushing is this phase's job — the driver ff-merges locally and never pushes a code phase, then
checks before the doc phase that every repo in `state.json`'s `bases` reached `origin`. Push each
one, honouring any repo named in `plan.md`'s `## Push holds`.

Then follow the build the push triggered:

```bash
track_build.py 'AaC/Architecture' --hash "$(git rev-parse HEAD)"
```

This is a **did-I-break-CI check, not a verification gate** — the slice was already proven in steps
1–2. What it catches is the class of failure only CI can see: the collector running against all 33
registered producers, and the Dockerfile building end-to-end, neither of which is reachable in this
environment. A red build here is a blocking finding even though every local check passed.

## Findings

Blocking findings come back as appended phases. Sub-bar findings go in the close-out report for the
operator to triage. A live check that cannot be run at all — the dataset endpoint down, the sidecar
unavailable — is reported as *not verified*, never as passed; the phase is allowed to end with a
criterion unproven and said so, and is not allowed to end with one assumed.

## The operator gate

The operator's gate is the close-out report, after the run. Production has by then already taken
the change, which is what makes steps 1–2 the real gate and why they precede the push.
