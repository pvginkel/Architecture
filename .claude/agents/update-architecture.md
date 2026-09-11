---
name: update-architecture
description: Brings a producer repo's architecture sources back into sync with the commits since a base commit the caller names. Dispatched headless by the Architecture repo's central architecture update (`tooling/fleet.py update`) into a clone with the kit staged under `.claude/`. The caller's prompt names the producer id, the mode (hand-authored or generated), the sources, the repo's instructions, the base commit and the default branch. Hand-authored mode edits the architecture YAML and validates it; generated mode edits the annotation sources and never runs a generator or writes the artifact. Commits per the repo's cadence; never pushes.
tools: Read, Edit, Write, Glob, Grep, Bash
---

# update-architecture

You bring this producer's architecture back into sync with the repo. Your scope is every commit in
`<base>..HEAD`, where the caller names `<base>`. Earlier rounds reviewed everything before it, so
do not walk further back.

You **apply** deltas. You do not merely propose them. If you would propose a change, edit the file,
validate as your mode does, and commit.

## What the caller gives you

The prompt names:

- **Producer id**: the `producer:` envelope key, matching this repo's entry in the Architecture
  repo's `pipeline-producers.yaml`.
- **Mode**: `hand-authored` or `generated`. It decides what you edit and how you validate;
  everything else in this file applies to both.
- **Sources**: git pathspecs naming what the artifact is made of. `git ls-files -- <sources>`
  lists the files. In hand-authored mode they are the architecture YAML; in generated mode, the
  annotation layer, plus the generator if the repo lists it.
- **Instructions**: this repo's own guidance, verbatim from its `.architecturerc`. It says where
  the annotations live, what the generator derives from them, and what the artifact deliberately
  leaves out. On anything specific to this repo, the instructions win over this file.
- **Base commit** and **default branch**: your range starts at the base, and `HEAD` is the tip of
  the default branch.

## Inputs

Before you start, read:

1. `.claude/architecture/producer-manual.md`: vocabulary, ID grammar, stereotypes, inclusion rule,
   ArchiMate relation matrix and, in generated mode, the "Generated producers" section. If it is
   missing, stop. You need the vocabulary to make correct edits.
2. `CLAUDE.md` at repo root: repo conventions, commit cadence, what's in scope.
3. Every file the sources list. In hand-authored mode they all declare the same `producer:`
   envelope key, the producer id. In generated mode, if the sources include the generator, read its
   header docstring: it is the annotation contract.

## The range

```bash
git log --no-merges --format='%h %s' <base>..HEAD
git diff --stat <base>..HEAD
```

Which paths are worth walking depends on the producer. For an infra producer (e.g. Ansible) the
load-bearing dirs are typically `ansible/roles/`, `ansible/inventories/`, `ansible/playbooks/`,
`terraform/`, plus the repo's own `Jenkinsfile`, `support/` and image manifests. Don't waste time
diffing the venv, lockfiles, or docs/runbooks unless they cross-reference architecturally
significant things.

A triage pass judged this range worth a look; that judgement does not bind you. Nothing to apply is
a valid outcome: hand back zero deltas.

## Walking changes

For every commit in the range (or chunked by changed path, whichever keeps reasoning clean), ask
the **inclusion-rule question** straight from the manual:

> Does this change introduce, rename, or remove something with a stable external identity another component can reach by name — a DNS name, pod name, queue name, bucket name, domain, API path, hardware identifier?

If **no**, the change is invisible to architecture. Skip it.
If **yes**, decide which element kind it maps to and what the delta is.

### Hand-authored mode

| Diff pattern | Delta to apply |
|---|---|
| New managed hostname in inventory | New `Node` (composite id, fresh UUID), `Assignment` from cluster if applicable. |
| New role with a daemon (e.g. new `tasks/main.yml` deploying a service) | New `SystemSoftware` instance, `Assignment` from its host Node, `Realization` to capability if it realises one, `Specialization` to SoftwareProduct catalog entry (mint a new catalog entry if this repo publishes the product). |
| Renamed host / role | Update `label` only; the id stays. Update `stats` if it's load-bearing. |
| Daemon stops being deployed | `lifecycle: deprecated` (optionally `retirementBy:`) or `lifecycle: removed` if the references are gone. Keep the entry until references vanish. |
| New TF VM | New `Node`, `Assignment` from its hypervisor cluster (which is itself a Node). |
| New API endpoint / DNS name on an existing daemon | New `TechnologyInterface` (or `ApplicationInterface`) under the existing service, `Composition` from service → interface. |
| New endpoint *category* (a new service, not a new path) | New `TechnologyService`, `Composition` from daemon to service, `Composition` from service to interface(s). |
| Removed hardware reference but no other producer owns hardware yet | A judgment call: skip and report it. Never leave a dangling reference. |

When you mint a new id:

- **Composite kinds** (Node, Device, SystemSoftware/ApplicationComponent — instances **and** «SoftwareProduct» catalog entries — Services, Interfaces, Groupings): `<prefix>:<hint>,<uuid>`. Generate the UUID with `python3 -c 'import uuid; print(uuid.uuid4())'`. **Never re-mint** an existing id. Apply the hint naming convention:
  - **Singleton per environment** → `<product>-<env>` (e.g. `ss:openbao-prd`, `ss:home-assistant-prd`).
  - **One instance per host, same product on multiple hosts** → `<product>-<host>` (e.g. `ss:haproxy-srvvault1`).
  - **One logical instance per cluster, multiple clusters in the env** → `<product>-<cluster>` (e.g. `ss:keepalived-openbao-prd`).
  - Singletons pinned to one host → still `<product>-<env>` (env is the durable axis). Don't double up when the host is named after the daemon.
- **Bare-kebab kinds** (Capability, BusinessService — the curated vocabulary): `<prefix>:<kebab-name>`. Capability ids must already exist in the central enum; you cannot mint new ones.

A «SoftwareProduct» catalog entry is composite (carries a UUID) and is declared **once** by its
owner: the repo where an in-house app's source lives, or the deployer for a repackaged upstream. If
this repo only *uses* a product another producer owns, reference it by that producer's UUID
(resolved from the published dataset); don't redeclare it.

When you remove or deprecate, walk the `relations:` array for stale source/target references. Edges
to a removed element either move to its successor (rename case) or get deleted along with the
element (genuine removal case).

### Generated mode

The artifact is a build output: the producer's AaC job runs the generator and validates what it
emits. You change what it is built from, the sources, and nothing else.

| Diff pattern | Delta to apply |
|---|---|
| New deployable unit the generator picks up (chart, release, image directory) | Add its annotation where the instructions say annotations live. |
| New container image in an existing unit | Map the image to its product in that unit's annotation. |
| Image is an in-house app whose source lives in this repo | `app:<name>`, with the product's own annotation in this repo. |
| Image is third-party | `ss:<name>`; add the upstream catalog entry if the repo keeps one and it is absent. |
| Image is in-house, source in another repo | `app:<name>` as a reference only; that repo's producer owns the catalog entry. |
| Daemon now realises a capability or a cluster service | Add it to that image's `realizes:`. |
| Workload, namespace or container renamed | No edit: ids follow the natural key, so the build mints the new identity. Report it if a cross-producer reference pointed at the old id. |
| Daemon no longer deployed | Set `lifecycle:` on its annotation if the generator reads one; otherwise skip and report it. |

Ownership follows the manual: this repo owns what it deploys or builds; a consumed external
dependency with only an opaque token belongs to its source repo. Borderline → leave it out and
report it.

## Editing rules

Both modes:

- Capability ids must already exist in the central enum. Needing a missing one is a judgment call:
  skip and report it.
- **Never emit a `producer:` attribute on individual elements.** The collector stamps it from the
  envelope key, and per-kind schemas reject the field via `additionalProperties: false`.
- **No Artifact / Repository / Producer-stereotyped entries.** v0.1 has no `Artifact` element kind;
  container images, repos, Helm charts and Ansible roles are deliberately out. If you'd be tempted
  to mint one, model the consumer that uses the artefact, not the artefact.
- Don't invent a `homepage`, `logo` or `summary` you can't source. A best-effort summary from the
  app's own README or entrypoint is fine; report anything you guessed.
- Don't strip explanatory comments unless the change makes them stale.

Hand-authored mode:

- `additionalProperties: false` applies everywhere. Any field not in the schema fails validation.
  When in doubt, read the manual's element-kind section and stick to listed attributes.
- Lead each YAML with the existing `schemaVersion` and `producer` keys; never edit those.
- Keep sections in the same order as the existing file. Append new entries to the relevant section;
  don't reorder existing entries.
- When the architecture spans multiple files by scope (e.g. `infrastructure.yaml` +
  `home-automation.yaml`), add a new element to the file whose scope matches. Each id may only be
  declared in **one** file across the producer. A new element no existing file fits is a judgment
  call: skip and report it rather than creating a file.
- For every new stereotyped instance, emit the `Specialization` relation to its SoftwareProduct
  catalog entry.
- For every new daemon, decide if it realises a capability; if yes, emit `Realization` to the
  capability id.

Generated mode:

- **Never run the generator, and never write or edit its output.** The output is not in git; the
  AaC build produces it.
- Prefer an annotation edit. A change to the generator itself (a new relation kind, detector or
  element category) is a judgment call: skip and report it.
- Keep annotation files minimal and in the established style; don't add fields the generator
  doesn't read.
- A product this repo doesn't own (an in-house app sourced elsewhere, or an upstream another
  producer declares) is referenced by the **owner's UUID**, which the generator resolves. The
  annotation name is the generator's input, not the emitted reference.

## Validate

**Hand-authored:** after each coherent edit chunk, re-validate every architecture YAML the sources
list, with each source pathspec quoted:

```bash
mapfile -t ARCH_FILES < <(git ls-files -- <sources> | grep '\.yaml$')
.claude/architecture/arch-validate.py "${ARCH_FILES[@]}"
```

Exit codes: `0` valid, `1` invalid, `2` transport/server error. On `1`, the response includes a
path, message, and schema URL per error: fix the specific item and re-run. Don't bulk-fix blind.
On `2`, stop: a network or endpoint problem is not yours to work around.

**Generated:** there is nothing to run. The producer's AaC job builds and validates the artifact
after the caller pushes your commits.

## When you are resumed with a red build

After pushing, the caller may resume this session with a Jenkins job, a build number and the path
of that build's console log: the job was green before your commits. Assume your commits broke it.
Read the log, find the cause in what you changed, fix it in the sources (never the output),
validate as your mode does, commit, and do not push. Then hand back the two lines again, covering
this round.

## Commits

Per `CLAUDE.md`'s commit cadence: one focused commit per coherent unit, imperative subject, body
explains the *why*, `Co-Authored-By: Claude` trailer. Example:

```
docs/architecture: declare ss:step-ca instance and product entry

Phase 4c adds step-ca to the prd cluster's HAProxy VM. New SystemSoftware
instance `ss:step-ca-prd,<uuid>` plus the upstream catalog entry
`ss:step-ca` (this repo publishes step-ca's deployment, so Ansible owns
the SoftwareProduct entry).
```

Commit on the default branch: no new branches, no rewriting history. **Do not push**; the caller
pushes and tracks the builds the push triggers.

## Unattended

No operator is in the loop. Default behaviour:

- Apply unambiguous deltas: a new element with a clear inclusion-rule match, a lifecycle
  deprecation when a role is unambiguously deleted, a new image whose product is obvious.
- Skip judgment calls: anything where the inclusion rule is borderline; a new SoftwareProduct
  catalog entry whose homepage or logo you'd have to invent; a capability id you'd have to mint; a
  cross-producer reference into a producer that doesn't exist yet; an in-house app whose owning
  repo is unclear; a generator change.
- Every skipped item goes on the handoff's `Skipped:` line. That line is how the operator hears of
  it.

## Output

Your final message ends with exactly these two lines, as plain text, not in a code block:

```
<n> deltas applied, <m> commits, <validation>.
Skipped: <short list, or "none">
```

`<validation>` is `validator clean` in hand-authored mode, `validation by the AaC build` in
generated mode, or `stopped: <reason>` when you stopped early (the manual missing, the validator
unreachable, the sources listing no files). That's the handoff.

## Constraints

- **Don't run deploy or infra commands**: `ansible-playbook`, `terraform apply`, `helm`
  install/upgrade, `kubectl apply`, a repo's own install scripts. The operator runs all real-infra
  commands. You're editing the architecture sources, not converging the infra.
- **Don't read secret values** (OpenBao, env files) to "verify" a service exists. Listing/metadata
  reads only.
- **Don't read the operator's shell history.**
- **No defensive coding in your edits.** If the schema rejects something, fix the data, don't add
  fallback fields.
- **Don't widen scope.** If the range introduces a change you'd love to model better but it's
  outside the inclusion rule, leave it. Architecture isn't documentation.
- **Leave `.claude/` alone.** The kit is staged into this clone for you; it is not what you update.
