---
name: seed-architecture
description: Author the FIRST architecture artifact for a repo joining the webathome.org federated Architecture-as-Code system. Surveys the repo by fanning out parallel Explore sub-agents, detects hand-authored vs generated mode, triages candidate elements with the operator, then drafts docs/architecture/*.yaml (or the annotation layer + generator for a generated producer) and validates. Use ONCE per repo to seed it. For incremental upkeep afterwards use the update-architecture / update-architecture-generated agents instead. Trigger when onboarding a repo as a producer, "seed/bootstrap the architecture", or creating a producer's first architecture.yaml.
---

# seed-architecture

Author a producer's **first** architecture artifact end-to-end: survey →
triage → author → validate. Once seeded, hand the repo off to the
`update-architecture` (hand-authored) or `update-architecture-generated`
(generated) agent for incremental upkeep — this skill is one-shot.

## Why this is a skill, not a sub-agent

Seeding means surveying a whole repo, which is best done by fanning out
several **Explore sub-agents in parallel** (one per area), keeping their
conclusions and not the file dumps. A sub-agent can't spawn sub-agents — so
this work can't live in an agent; it must run in the **main conversation**,
where it *can* fan out. That's the whole point. Run it from the main loop,
never from inside another agent.

## Read first (do not skip)

1. `${CLAUDE_PLUGIN_ROOT}/references/producer-manual.md` — the full manual.
   Vocabulary, **ID grammar**, **Element kinds**, **Inclusion rule**,
   **Ownership conventions**, **Generated producers**, the `boundBy` section
   and its deployer-side resolution mechanics. Your tagging and authoring
   hinge on these. If the manual is missing, stop and tell the operator.
2. `CLAUDE.md` at repo root — what this repo owns end-to-end.
3. `README.md` and any `docs/` that describe architecture, phases, runbooks.

The starter skeleton is at `${CLAUDE_PLUGIN_ROOT}/assets/architecture.yaml`; the
validator at `${CLAUDE_PLUGIN_ROOT}/scripts/arch-validate.py` (the repo copies it to
`scripts/arch-validate.py`).

## Step 1 — Detect the mode

- **Generated** — the repo already has a generator (`tools/gen-architecture.py`)
  or an annotation convention (`<thing>/architecture.yaml`) that emits the
  YAML. The repo + annotations are the source of truth; the YAML is a build
  artifact you **don't commit**. Ids are uuid5-from-natural-key.
- **Hand-authored** — no generator; the YAML *is* the source of truth. Ids
  are mint-once uuid4.

The mode changes the "author" step (Step 4), not the survey or triage.

## Step 2 — Survey the repo (fan out Explore sub-agents)

Launch **up to 3 Explore agents in parallel** (one message, multiple Agent
calls), each scoped to a slice of the repo. Give every agent: the
**inclusion rule**, the **bucket vocabulary** and the **kinds/hint
conventions** below, and tell it to return a tagged candidate table with
`file:line` evidence — conclusions, not file contents. Typical slices:

- **Hosts / inventory / infra** — managed hostnames, clusters, VMs, physical
  boxes (Ansible `inventories/*/hosts*`, Terraform modules). Candidate
  Nodes/Devices.
- **Workloads / daemons / images** — roles, charts, deployments, container
  images. Candidate SystemSoftware / ApplicationComponent instances and the
  SoftwareProduct catalog entries the repo owns; for a generated repo, the
  annotation each image needs (product, `realizes`, `served_by`).
- **Endpoints / dependencies** — DNS names, VIPs, ingress hosts, ports, API
  paths (candidate Services/Interfaces), and runtime dependency wires
  (`OIDC_ISSUER_URL`, DB URLs, secret stores) that become `boundBy` recipes
  or `Serving` edges. Sweep for outbound dependencies with `grep -rIi '://'` and
  triage the hits — most are docs, examples, or schema/namespace URLs; keep the
  genuine runtime calls (SaaS base URLs, webhook/favicon targets), which live as
  base-URL constants in code and so hide from an env-var scan.

Skip vendor dirs, lockfiles, `.venv/`, `__pycache__/`, `tmp/`. Aggregate the
agents' findings into one inventory file:

```
tmp/architecture-inventory/<producer-id>-inventory.md
```

`<producer-id>` is the bare kebab this repo will use as its `producer:`
envelope key (e.g. `ansible`, `helm-charts`, `docker-images`) — infer from
`CLAUDE.md`/repo name, or ask the operator.

### Bucket vocabulary — tag every candidate with exactly one

| Bucket | Meaning |
|---|---|
| `producer-now` | Belongs in this producer's YAML. The repo introduces it. |
| `base-now` | Referenced but owned by no producer yet (hardware, services of an unpublished producer). Lift into the Architecture repo's base YAML. |
| `defer-to-<producer>` | Belongs in another producer's artifact. Don't emit; revisit when it onboards. |
| `out` | Fails the inclusion rule (no stable external identity reachable by name). |

**Default to `out`** when borderline — the inclusion rule wins.

### Hint convention (composite-id `<hint>`)

The hint distinguishes an instance from siblings of the same product: singleton
per env → `<product>-<env>` (`ss:openbao-prd`); one per host → `<product>-<host>`;
one per cluster → `<product>-<cluster>`. Don't double up when the host is named
after the daemon. UUIDs are identity; hints are readability and may drift.

## Step 3 — Triage with the operator (interactive)

Present the tagged inventory. **Pieter drives the modeling** — don't decide
scope, names, stereotypes, or what's in/out unilaterally. Resolve the genuine
open questions in batch (not per row). Settle: which slice is the thin first
artifact, which file(s) it splits into, and the `producer-now` set.

## Step 4 — Author

**Hand-authored:** mint a uuid4 per instance (`python -c 'import uuid;
print(uuid.uuid4())'`), compose ids as `<kind>:<hint>,<uuid>`, draft
`docs/architecture/*.yaml` from the starter skeleton, and wire the relations
(branch relation `type` on the target kind — see the manual's triple matrix).
Reference cross-producer elements by **UUID resolved from the published
dataset** (`https://architecture.webathome.org/data/v0.1/architecture.yaml`),
not bare hints.

**Generated:** do *not* mint uuid4s or hand-write the YAML. Design the
**annotation layer** (per image/workload: product mapping, `realizes`,
`served_by`) and the **generator seams** (detectors, uuid5 natural keys,
relation rules). Keep natural keys deterministic — strip deploy-time
randomness (a Helm `randAlphaNum` Job suffix) out of the key. Resolve
cross-producer ids by fetching the merged dataset and looking up `hint`+kind;
overlay a not-yet-published sibling producer's local checkout so its authored
recipes resolve while testing. For `boundBy` resolution follow the manual's
deployer-side mechanics (preserve host+port, exclude init containers, attach at
the coarsest honest granularity).

## Step 5 — Validate

```bash
./scripts/arch-validate.py docs/architecture/*.yaml
```

Iterate until clean. For a generated producer, also **regenerate twice and
diff** — a clean producer is byte-identical (catches non-deterministic ids).

## Step 6 — Wire CI and register (point, don't do blindly)

Per the manual's **Jenkins integration** and **Registration** sections: add
validate + archive steps (generated producers add a generate step first and
don't commit the YAML, ideally in a dedicated `Jenkinsfile.architecture`
isolated from the deploy pipeline); then PR `pipeline-producers.yaml` in
pvginkel/Architecture. Confirm one build archives + validates before
registering.

## Constraints

- **Inventory/triage before authoring.** Don't draft YAML before the operator
  has triaged the buckets.
- **Inclusion rule wins.** No stable external identity reachable by name →
  `out`, however significant it feels. Named surfaces and dependency edges,
  never runtime state.
- **No `producer:` on individual elements** — the collector stamps it from the
  envelope key (`additionalProperties: false` rejects it).
- **Never re-mint** a uuid4; a generated producer mints none (uuid5 from key).
- **Don't read secrets** (OpenBao values, shell history). Metadata reads are fine.
- **No defensive padding** — empty inventory section → write `(none)`, don't invent rows.
