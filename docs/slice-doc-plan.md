# Slice documentation plan

Which documentation surfaces a shipped slice brings up to date, and the rules for each. This is the
doc `.aiworkflowrc` names as `doc_phase.plan`: the run loop's doc phase is "read this and execute
it", working from the whole slice's merged diff.

The rules that govern the doc *set* — how it is organized, what a topic doc reads like, how the
index works — are in [`documentation-model.md`](documentation-model.md), and this phase does not
restate them. Read that first; this doc is only about which surfaces a slice touches and in what
order.

## The surfaces

Work the diff, not a checklist. Each surface below is owed an update only when the slice's changes
actually reached it.

### 1. The scope `docs/` that owns the change

Four scopes, each with its own `docs/` and `docs/index.md`:

| Scope | Owns |
|---|---|
| root `docs/` | cross-cutting and system-level design: the pipeline as a whole, the wire surfaces, shared conventions |
| `tooling/docs/` | the merge pipeline — collect, generate, validate, the metaschema codegen |
| `viewer/docs/` | the React/ReactFlow/ELK viewer |
| `service/docs/` | the Express service, its endpoints and its container behaviour |

Design belongs to the subproject it describes; design that **spans** subprojects, or describes the
system as a whole, belongs to the root. A slice that changed the producer contract or the published
dataset shape changed a system-level thing, whichever component's code moved.

Note that the three subproject indexes are currently near-empty — those scopes have an `index.md`
and little else. That is a real state, not a gap this phase closes: seed a scope only where **this
slice's** design needs a home, and leave the rest to a `/update-docs` sweep.

### 2. The decision index

`../ArchitectureSpecs/decisions.md` is a thin `DNNN` registry — id, one line, a link to the topic
doc holding the rationale, every row ≤100 characters. If the slice made or changed a decision, the
rationale goes in the topic doc and a row goes (or is updated) here. Depth never goes in the table.
It is a separate git repo: commit there separately.

### 3. The reader-facing docs at the root

- **`README.md`** — the system overview and the build/run instructions. Owed an update when the
  component set, the pipeline's shape, or how you run any of it changed.
- **`USAGE.md`** — the producer-facing surface: dataset URLs, the `arch-validate.py` CLI, what a
  producer repo does. Owed whenever the producer contract or the published endpoints changed.
- **`CLAUDE.md`** (root and per-subproject) — kept to about one screen and holding each fact once.
  A slice rarely touches it; when a new standing rule genuinely belongs there, something else moves
  out to a topic doc rather than the file growing.

### 4. The producer manual, when the contract moved

`arch/references/producer-manual.md` is what producer repos are onboarded against, and
`arch/assets/architecture.yaml` is the skeleton they start from. A slice that changed
`schema/v0.1/`, the enums, or what a valid `architecture.yaml` looks like has changed what
producers must write — update both, and see [`arch-plugin.md`](arch-plugin.md) for how the plugin
is packaged.

### 5. The capability enum's third place

Adding a `cap:` entry touches three places, one of which is hand-written and easy to miss.
[`capability-enum.md`](capability-enum.md) is the doc; if the slice added an entry, confirm the doc
still describes the path correctly.

## What "up to date" means here

Per the documentation model: **state the design as it is**, as implemented, not as the slice
authored it. Where the implementation diverged from the plan, the doc describes what shipped and
the decision row follows the doc. No changelog entries, no "as of slice NNN", no tombstones for
superseded conventions — rewrite the doc instead.

**Ground every claim in the shipped source.** A doc sentence that cannot be checked against the
merged tree does not go in.

## Gates

Documentation changes do not compile, but they do live beside code:

```bash
kc project build       # unchanged and green — the doc phase must not have moved code
```

Check relative links resolve (the indexes link across scopes, and `../ArchitectureSpecs/` links
leave the repo). Then commit — this repo and the spec repo separately, since they are separate git
repos.

## When there is little to do

A slice that changed no design, no convention, and no reader-facing surface owes nothing here, and
saying so plainly is the correct outcome. Do not invent doc work to fill the phase; an index entry
for a doc nobody needed is worse than no entry.
