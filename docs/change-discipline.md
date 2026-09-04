# Change discipline

The rules every code change in this repo obeys, across all four components. This is the doc
`.aiworkflowrc` names as `design_philosophy`: it is handed to every `code-writer`, `code-reviewer`,
`plan-writer` and `plan-reviewer` the pipeline dispatches, and it is what a reviewer cites when
sending work back. It states the rules; the *design* they apply to lives in the topic docs indexed
from [`index.md`](index.md).

## Clean breaking changes

Greenfield, no external consumers. Nothing outside this repo imports its code, so when an interface
changes, **fix the callers** — do not add a shim, an adapter, or an overload that keeps the old
shape alive alongside the new one.

The one place this rule stops is the **published dataset and the producer contract**. Producer repos
across the homelab emit `architecture.yaml` against `schema/v0.1/`, and the service publishes
`data/v0.1/` to consumers that are not in this repo (the viewer, the Home app switcher, a Chrome
extension). That surface is versioned for a reason: a breaking change there is a `v0.2`, not an
edit to `v0.1`. Inside the repo, break freely; at those two boundaries, version.

## No tombstones

Delete replaced code completely. No "moved to X" comments, no stub functions that forward, no
deprecated aliases, no commented-out blocks, no dead re-exports. The same applies to prose: when a
convention is superseded, **rewrite the doc** rather than appending a note that the old rule no
longer holds. Git history is the record of what things used to be; the working tree is only ever a
statement of what is true now.

## No defensive coding, no "just in case" infrastructure

No `try`/`except` that swallows an error, no drop-the-bad-input-and-keep-going path, no null-guard
for a condition the schema or the framework already prevents, no silent fallback for data the
dataset guarantees. No scheduled rebuild, retry, or fallback cache added without a real observed
failure to point at.

**Boundary validation is the exception, and it is the point.** This project's whole job is
validating input: the metaschema against producer artifacts, request bodies at the service's API,
the dataset the viewer loads. Checking those is not defensive coding — it is the feature. The
distinction is where the input comes from: validate what crosses into the system, trust what the
system already established.

Prefer obvious-now failure over silent-corruption-later. A pipeline that merges 33 producers into
one published model corrupts quietly and visibly-much-later if it is allowed to.

Per-component readings of the same rule: for `tooling/` it is the metaschema and producer input
that get validated and everything downstream that does not; for `service/` it is request input and
the dataset it loads, never a drop-the-request-keep-serving path; for `viewer/` it is that the
dataset's shape is guaranteed by the schema, so rendering code does not defend against it.

## Testability is critical

Every change ships with a test. A feature without one is incomplete, and "I verified it by hand" is
not a substitute — the point of the test is that it runs again next time.

What that means per component:

| Component | Suite | Runs as |
|---|---|---|
| `tooling` | pytest, under `tooling/tests/` | `kc project test --project tooling` (also runs `validate.py meta`) |
| `viewer` | Vitest | `kc project test --project viewer` |
| `service` | Vitest + supertest | `kc project test --project service` |
| `root` | `validate.py` over `docs/architecture/*.yaml` | `kc project test --project root` |

A change that genuinely cannot be covered by any of those is a change whose testability problem is
the first thing to solve — say so and fix the seam, rather than shipping it uncovered.

## Never hand-edit generated artifacts

`tooling/generate.py` emits `schema/v0.1/generated/` and the viewer's `src/generated/vocab.ts` from
`schema/v0.1/subset.yaml` and the vendored ArchiMate sources. Both trees are **committed**, which
makes them look editable; they are not. Change the source and regenerate. `generate.py --check` is
`tooling`'s build gate and fails when the committed trees are stale, so a hand-edit is caught — but
it is caught as a confusing build failure rather than as the mistake it was.

Adding a `cap:` enum entry is the case where this bites hardest, because one of its three
touch-points is genuinely hand-written. See [`capability-enum.md`](capability-enum.md).

## This is a public repo

`github.com/pvginkel/Architecture` is world-readable, and so is the dataset it publishes. No
secrets, credentials, internal hostnames or IP addresses, and no non-public names — in code,
in tests, in fixtures, in commit messages, or in the architecture artifacts under
`docs/architecture/`. Assume every line is read by someone outside the homelab, because it can be.
