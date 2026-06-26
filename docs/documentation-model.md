# Architecture documentation model

How Architecture's project documentation is organized and kept current. This is the meta-doc:
the rules every scope's `docs/` follows, and who maintains them. It is not project design itself — for
a change, you want the topic docs, not this file.

## Why the docs exist

The documentation is here to be **assembled into a per-change reading list**. Before a change is
planned, the docs relevant to it are discovered from the index and handed to whoever implements and
reviews it. That single purpose drives every rule below: a doc is useful only if it can be *found*
and *pulled in* without reading the whole set first.

This is the model the project is moving to. Historically the design rationale often lived in one
giant append-only `decisions.md` — a do's-and-don'ts log: golden information, unusable format. That
content becomes ordinary project documentation — small topic docs that state the design as it is.

## Layout — the same rules in every scope

Every scope has a `docs/` directory: the **root** (`docs/`, for cross-cutting and system-level
design) and **each subproject** (`viewer/docs/`, …). The rules are identical everywhere;
only the *content* differs. There is no rigid per-document template — these are rules, not a format:

- **An index.** `docs/index.md` is a pure fan-out: one entry per topic doc, each a path plus one
  precise line on what's inside. A good entry lets the right doc surface for a change without opening
  it. No prose that belongs in the topic docs; no entry without a doc; no doc missing from the index.
- **Separate folders and documents.** Organize topics into folders by area; don't pile everything
  into one file. Reach for subfolders once a scope grows past a handful of docs.
- **Small, targeted topic docs.** One subject per doc. **Split rather than grow** — when a doc starts
  covering two subjects, cut it in two and index both. Small docs keep a reading list cheap to load.
- **Each doc is self-describing.** Its subject is obvious from the title and first lines.
- **State the design as it is.** A topic doc reads as "how it works and why," not "what we decided on
  date X." Rationale is welcome; a chronological log is not. **No tombstones** — when a convention is
  superseded, rewrite the doc; don't append a changelog.
- **Ground every claim.** Document what is true in the code and specs, with enough specificity to be
  checkable. Don't document aspirational or invented conventions.

Scope rule: design belongs to the subproject it describes. Design that spans subprojects, or
describes the system as a whole (the components, the wire surfaces, shared conventions), lives in the
**root** `docs/`.

## Decisions

`DNNN` ids stay — they are stable anchors referenced from slices, the API contracts, and code, and
they remain the unit a slice writer cites. What changes is where the *content* lives:

- The **rationale** for a decision lives in the relevant topic doc, as part of the design it shaped.
- `../ArchitectureSpecs/decisions.md` becomes the **decision index** — a thin table, nothing more:

  | ID   | Decision                                  | Where                                |
  | ---- | ----------------------------------------- | ------------------------------------ |
  | D043 | <one-line description of the decision>    | viewer/docs/<topic>.md     |
  | D094 | <one-line description of the decision>    | viewer/docs/<topic>.md     |

  Keep every line **≤100 characters**: the id, a short description, and a link to the doc that holds
  the rationale. The index is a registry, not a record — depth goes in the doc, never in the table.

## Maintenance — it follows authorship

Whoever authors or changes a decision or a design convention owns reflecting it into the docs. In
practice:

- **`/write-slice`** is the primary keeper. A slice writer already records the decisions a slice
  makes; recording one now includes putting its rationale in the right topic doc and adding (or
  updating) its row in the decision index. Same act, one more output.
- **`/run-slice`** verifies at close-out that the docs match what was actually built, and reconciles
  if the implementation diverged from the authored decision.
- **`/update-docs`** seeds a scope from nothing and reconciles drift in bulk — on demand, or with a
  hint to focus. It is how the set was first built and how it is swept for staleness.

A change that alters the design or a convention is not done until the docs reflect it.
