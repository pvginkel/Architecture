"""Architecture-pipeline collector.

Runs as a Docker build stage in the Architecture image. Reads each registered
producer's `architecture.yaml` from `producer-artifacts/<producer-id>/`,
validates each artifact, merges them, runs cross-producer checks, and writes
the consolidated dataset to `dist/data/v0.1/`.

v3 ships with `pipeline-producers.yaml` empty; later work items fill in the
capability-enum, merge, cross-ref, alias-hint, triple-matrix, grouping, and
emit stages. This file currently covers work items 2 (load registry) and
3 (discovery + per-artifact validation).

Usage:

    poetry run python collect.py \\
        --producers pipeline-producers.yaml \\
        --in producer-artifacts \\
        --out dist
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import click

from _arch import (
    PIPELINE_PRODUCERS_FILE,
    PIPELINE_PRODUCERS_SCHEMA,
    load_allowed_triples,
    load_capability_enum,
    load_pipeline_producers,
    load_yaml,
    normalize,
    parse_id,
    validate_doc,
)


# Stable namespace for uuid5-derived synthesised producer-relation ids.
# Same (producer-id, element-id) input always yields the same uuid, which
# keeps the merged dataset byte-identical across reruns.
PRODUCER_RELATION_NAMESPACE = uuid.UUID("41a96d77-cf3a-4f53-9e75-2ad5e8d3e7c4")


ELEMENT_KIND_ARRAYS: tuple[str, ...] = (
    "nodes",
    "devices",
    "systemSoftware",
    "applicationComponents",
    "applicationServices",
    "applicationInterfaces",
    "technologyServices",
    "technologyInterfaces",
    "artifacts",
    "capabilities",
    "businessServices",
    "groupings",
)

# YAML envelope key → ArchiMate concept name. The triple matrix
# (x-allowedTriples in generated/relations.schema.yaml) is keyed on
# ArchiMate names; the ResolutionIndex returns the YAML envelope kind.
ARRAY_TO_ARCHIMATE: dict[str, str] = {
    "nodes": "Node",
    "devices": "Device",
    "systemSoftware": "SystemSoftware",
    "applicationComponents": "ApplicationComponent",
    "applicationServices": "ApplicationService",
    "applicationInterfaces": "ApplicationInterface",
    "technologyServices": "TechnologyService",
    "technologyInterfaces": "TechnologyInterface",
    "artifacts": "Artifact",
    "capabilities": "Capability",
    "businessServices": "BusinessService",
    "groupings": "Grouping",
}


class CollectorError(Exception):
    """Phase-level failure carrying one-or-more concrete error messages.
    The CLI surfaces each message and exits non-zero. Raised whenever a
    collector phase finds any violations — no partial-progress paths.
    """

    def __init__(self, phase: str, messages: list[str]) -> None:
        self.phase = phase
        self.messages = messages
        super().__init__(f"{phase}: {len(messages)} error(s)")


def discover_artifacts(producers: list[dict], input_dir: Path) -> dict[str, Path]:
    """Reconcile the registered producer list against the contents of
    `input_dir`. Returns a {producer-id: artifact-path} map for the
    registered producers. Raises CollectorError on:

    - registered producer with no corresponding `<id>/architecture.yaml`
      (the Jenkinsfile should have copied it in via copyArtifacts);
    - directory under `input_dir` that is not registered ("stowaway"
      producer — refused so that local mistakes don't sneak into a
      pipeline build).
    """
    expected_ids = {p["id"] for p in producers}
    found_dirs: set[str] = set()
    if input_dir.exists():
        found_dirs = {entry.name for entry in input_dir.iterdir() if entry.is_dir()}

    messages: list[str] = []
    for pid in sorted(expected_ids - found_dirs):
        messages.append(
            f"missing producer artifact: {input_dir}/{pid}/architecture.yaml "
            f"(producer {pid!r} registered in pipeline-producers.yaml but no "
            f"directory present — Jenkins copyArtifacts step did not run or failed)"
        )
    for pid in sorted(found_dirs - expected_ids):
        messages.append(
            f"stowaway directory: {input_dir}/{pid}/ "
            f"(not registered in pipeline-producers.yaml — register it or remove it)"
        )

    # Even when the directory exists, the artifact file inside it must exist too.
    artifact_paths: dict[str, Path] = {}
    for pid in sorted(expected_ids & found_dirs):
        path = input_dir / pid / "architecture.yaml"
        if not path.exists():
            messages.append(
                f"missing producer artifact: {path} "
                f"(directory present but architecture.yaml absent)"
            )
        else:
            artifact_paths[pid] = path

    if messages:
        raise CollectorError("discovery", messages)
    return artifact_paths


def load_and_validate_artifacts(artifact_paths: dict[str, Path]) -> dict[str, Any]:
    """Load + per-artifact validate each registered producer's artifact.
    Returns {producer-id: parsed-and-normalized-doc} on success. Raises
    CollectorError with one entry per (producer, JSON pointer, message)
    on any schema violation.

    Validation runs through the shared `_arch.validate_doc`, which is the
    same code the v2 `arch-validate` HTTP endpoint and the `validate.py`
    CLI use, so producer CI and the pipeline see identical errors.
    """
    docs: dict[str, Any] = {}
    messages: list[str] = []
    for pid in sorted(artifact_paths):
        path = artifact_paths[pid]
        doc = normalize(load_yaml(path))
        errors = validate_doc(doc)
        if errors:
            for e in errors:
                pointer = "/" + "/".join(str(p) for p in e.absolute_path)
                messages.append(f"{pid}: at {pointer}: {e.message}")
        else:
            docs[pid] = doc

    if messages:
        raise CollectorError("per-artifact-validation", messages)
    return docs


def reconcile_capability_enum(docs: dict[str, Any]) -> None:
    """Every `cap:`-prefixed id appearing anywhere in the merged set must
    exist in `schema/v0.1/enums/capabilities.yaml`. Producers cannot mint
    capabilities — additions require a PR against the enum file.

    Surfaces: declared Capability ids (and their `replacedBy`) in each
    artifact's `capabilities[]` array, plus any `cap:`-prefixed `source`
    or `target` on a relation. Each violation names the producer and the
    JSON pointer to the offending field.
    """
    enum_ids = load_capability_enum()
    messages: list[str] = []
    for pid in sorted(docs):
        doc = docs[pid]
        for i, cap in enumerate(doc.get("capabilities") or []):
            if cap["id"] not in enum_ids:
                messages.append(
                    f"{pid}: at /capabilities/{i}/id: capability "
                    f"{cap['id']!r} not in enums/capabilities.yaml"
                )
            replaced_by = cap.get("replacedBy")
            if replaced_by is not None and replaced_by not in enum_ids:
                messages.append(
                    f"{pid}: at /capabilities/{i}/replacedBy: capability "
                    f"{replaced_by!r} not in enums/capabilities.yaml"
                )
        for i, rel in enumerate(doc.get("relations") or []):
            for field in ("source", "target"):
                ref = rel[field]
                if ref.startswith("cap:") and ref not in enum_ids:
                    messages.append(
                        f"{pid}: at /relations/{i}/{field}: capability "
                        f"{ref!r} not in enums/capabilities.yaml"
                    )

    if messages:
        raise CollectorError("capability-enum", messages)


def synthesize_producer_relations(docs: dict[str, Any]) -> int:
    """Append one Association relation per declared element from the
    artifact's top-level «Producer» Artifact to that element. Mutates each
    doc's `relations` array in place. Producers don't have to emit these
    by hand — provenance falls out of the merged dataset structurally,
    expressed as real ArchiMate edges rather than an attribute on every
    element.

    Relation type is Association (matches every v0.1 element kind in the
    triple matrix from Artifact-as-source; Aggregation/Composition would
    only permit Artifact and Grouping targets).

    Relation ids are uuid5(NAMESPACE, "<producer-id>|<element-id>") so the
    output is deterministic across reruns. The producer's own «Producer»
    Artifact entry is skipped (no self-Association).

    Pre-merge: synthesised relations join their owning artifact's relations
    array, which means they pass through dup-id detection and cross-ref
    resolution like producer-emitted relations.

    Returns the total number of relations synthesised across all artifacts.
    """
    synthesised = 0
    for pid in sorted(docs):
        doc = docs[pid]
        producer_id = doc["producer"]
        relations = doc.setdefault("relations", []) or []
        doc["relations"] = relations
        for kind in ELEMENT_KIND_ARRAYS:
            for elem in doc.get(kind) or []:
                if elem["id"] == producer_id:
                    continue
                rel_uuid = uuid.uuid5(
                    PRODUCER_RELATION_NAMESPACE,
                    f"{producer_id}|{elem['id']}",
                )
                relations.append(
                    {
                        "id": f"rel:{rel_uuid}",
                        "source": producer_id,
                        "target": elem["id"],
                        "type": "Association",
                    }
                )
                synthesised += 1
    return synthesised


def merge_artifacts(docs: dict[str, Any]) -> dict[str, list]:
    """Union every element-kind array (and relations) across producers.
    Fails the run if any id appears in more than one place, reporting
    both the original producer + kind and the conflicting producer + kind.

    Element `producer` back-pointers are preserved verbatim — the merge
    does not rewrite them. Producer iteration is in sorted order so the
    merged array order is deterministic for the same input set.
    """
    merged: dict[str, list] = {name: [] for name in (*ELEMENT_KIND_ARRAYS, "relations")}
    seen: dict[str, tuple[str, str]] = {}  # id -> (kind, producer)
    messages: list[str] = []

    for pid in sorted(docs):
        doc = docs[pid]
        for kind in (*ELEMENT_KIND_ARRAYS, "relations"):
            for elem in doc.get(kind) or []:
                eid = elem["id"]
                if eid in seen:
                    prev_kind, prev_pid = seen[eid]
                    messages.append(
                        f"duplicate id {eid!r}: declared by {prev_pid!r} as "
                        f"{prev_kind} and by {pid!r} as {kind}"
                    )
                    continue
                seen[eid] = (kind, pid)
                merged[kind].append(elem)

    if messages:
        raise CollectorError("merge", messages)
    return merged


class ResolutionIndex:
    """Three lookup tables built from the per-producer `docs` walk:

    * `by_full_id` — exact-string match. The merged set's element id keys
      everything (composite, bare kebab, anything the schema accepts).
    * `by_uuid` — for declarations that minted a UUID (instance kinds).
      Keyed on the UUID portion of the composite declaration.
    * `by_internal_hint` — (producer, kind, hint) → element. Lets a producer
      write hint-only references to its own elements. Cross-producer
      hint-only references deliberately do not resolve through this table.

    Each value is a (kind, elem, owner_pid) tuple, so callers can ask for
    the kind and owner without re-parsing.
    """

    def __init__(self, docs: dict[str, Any]) -> None:
        self.by_full_id: dict[str, tuple[str, dict, str]] = {}
        self.by_uuid: dict[str, tuple[str, dict, str]] = {}
        # Internal-hint key is the id-prefix (e.g. "ss", "node") not the
        # YAML array name (e.g. "systemSoftware"), so it lines up with
        # what `parse_id` returns on a reference.
        self.by_internal_hint: dict[tuple[str, str, str], tuple[str, dict, str]] = {}
        for pid in sorted(docs):
            doc = docs[pid]
            for kind_name in ELEMENT_KIND_ARRAYS:
                for elem in doc.get(kind_name) or []:
                    eid = elem["id"]
                    entry = (kind_name, elem, pid)
                    self.by_full_id[eid] = entry
                    prefix_kind, hint, uuid_str = parse_id(eid)
                    if uuid_str is not None:
                        self.by_uuid[uuid_str] = entry
                    if hint is not None and uuid_str is not None:
                        self.by_internal_hint[(pid, prefix_kind, hint)] = entry

    def resolve(
        self, ref: str, relation_pid: str
    ) -> tuple[tuple[str, dict, str] | None, str | None]:
        """Return (entry-or-None, ref-supplied-hint-for-divergence-check).

        Lookup order:
            1. UUID portion present → by_uuid (any-producer, by design).
            2. No UUID, full-string match → by_full_id (catalogue / curated).
            3. No UUID, hint-only → by_internal_hint for the relation's
               own producer. Cross-producer hint-only refs do not resolve
               and surface as dangling — they need the UUID.
        """
        kind, hint, uuid_str = parse_id(ref)
        if uuid_str is not None:
            return self.by_uuid.get(uuid_str), hint
        if ref in self.by_full_id:
            return self.by_full_id[ref], None
        if hint is not None:
            return self.by_internal_hint.get((relation_pid, kind, hint)), None
        return None, None


def resolve_cross_references(
    docs: dict[str, Any],
    index: ResolutionIndex,
    report: dict[str, Any],
) -> None:
    """For every relation source/target, check the id resolves. Dangling =
    fail. Reference to a `removed` element = fail. Reference to a
    `deprecated` element = warning in the report; the run still succeeds.
    Composite + uuid-only + hint-only forms all flow through `index`.
    """
    messages: list[str] = []

    for pid in sorted(docs):
        for i, rel in enumerate(docs[pid].get("relations") or []):
            for field in ("source", "target"):
                ref = rel[field]
                entry, _ = index.resolve(ref, pid)
                if entry is None:
                    messages.append(
                        f"{pid}: at /relations/{i}/{field}: dangling reference to "
                        f"{ref!r} (no element resolves; cross-producer references "
                        f"must include the UUID)"
                    )
                    continue
                _, elem, _ = entry
                lifecycle = elem.get("lifecycle")
                if lifecycle == "removed":
                    messages.append(
                        f"{pid}: at /relations/{i}/{field}: relation references "
                        f"{ref!r} which is lifecycle=removed "
                        f"(remove the relation or restore the target)"
                    )
                elif lifecycle == "deprecated":
                    report["warnings"].append(
                        {
                            "kind": "deprecated-target",
                            "producer": pid,
                            "pointer": f"/relations/{i}/{field}",
                            "reference": ref,
                            "message": (
                                f"relation references {ref!r} which is "
                                f"lifecycle=deprecated"
                            ),
                        }
                    )

    if messages:
        raise CollectorError("cross-reference", messages)


def check_triple_matrix(
    docs: dict[str, Any],
    index: ResolutionIndex,
) -> None:
    """Every relation's `(source-kind, type, target-kind)` triple, in
    ArchiMate concept-name terms, must appear in `x-allowedTriples` from
    `schema/v0.1/generated/relations.schema.yaml`. The same check runs
    over in-artifact and cross-artifact relations — JSON Schema doesn't
    enforce triples on its own, so the collector is the enforcement
    point for both.

    Synthesised producer-Association edges land in the same relation
    arrays as producer-emitted ones; they're checked here too. (Artifact,
    Association, *) is permitted for every v0.1 element kind, which is
    why Association is the synthesis type.
    """
    allowed = load_allowed_triples()
    messages: list[str] = []

    for pid in sorted(docs):
        for i, rel in enumerate(docs[pid].get("relations") or []):
            source_entry, _ = index.resolve(rel["source"], pid)
            target_entry, _ = index.resolve(rel["target"], pid)
            if source_entry is None or target_entry is None:
                # cross-ref pass would have caught this; if we got here
                # without cross-ref running first, skip rather than spam.
                continue
            source_kind_name, _, _ = source_entry
            target_kind_name, _, _ = target_entry
            source_concept = ARRAY_TO_ARCHIMATE[source_kind_name]
            target_concept = ARRAY_TO_ARCHIMATE[target_kind_name]
            triple = (source_concept, rel["type"], target_concept)
            if triple not in allowed:
                messages.append(
                    f"{pid}: at /relations/{i}: triple "
                    f"({source_concept}, {rel['type']}, {target_concept}) "
                    f"not in x-allowedTriples — source {rel['source']!r}, "
                    f"target {rel['target']!r}"
                )

    if messages:
        raise CollectorError("triple-matrix", messages)


def check_groupings(
    docs: dict[str, Any],
    index: ResolutionIndex,
) -> None:
    """Groupings are producer-local. For every Grouping element, find the
    Aggregation relations sourced from it (each target is a member).
    Two rules:

    - Each member's owning producer must equal the Grouping's owning
      producer. A Grouping that aggregates someone else's element is a
      cross-producer Grouping — refused.
    - A Grouping with zero Aggregation members is refused. The construct
      is a render-time clustering hint; an empty one is dead data.
    """
    messages: list[str] = []

    # Index Groupings → owner_pid
    grouping_owner: dict[str, str] = {}
    for pid in sorted(docs):
        for elem in docs[pid].get("groupings") or []:
            grouping_owner[elem["id"]] = pid

    # Aggregations sourced from a Grouping: {grouping_id: [(pid, i, target_id)]}
    aggregations: dict[str, list[tuple[str, int, str]]] = {
        gid: [] for gid in grouping_owner
    }
    for pid in sorted(docs):
        for i, rel in enumerate(docs[pid].get("relations") or []):
            if rel["type"] != "Aggregation":
                continue
            src_entry, _ = index.resolve(rel["source"], pid)
            if src_entry is None:
                continue
            src_kind_name, _, _ = src_entry
            if src_kind_name != "groupings":
                continue
            src_eid = src_entry[1]["id"]
            aggregations.setdefault(src_eid, []).append((pid, i, rel["target"]))

    for gid, owner_pid in sorted(grouping_owner.items()):
        members = aggregations.get(gid, [])
        if not members:
            messages.append(
                f"{owner_pid}: Grouping {gid!r} declared but no Aggregation "
                f"relation aggregates any member from it"
            )
            continue
        for rel_pid, i, target_ref in members:
            tgt_entry, _ = index.resolve(target_ref, rel_pid)
            if tgt_entry is None:
                # Already caught by cross-ref pass; defensive skip.
                continue
            _, _, target_owner = tgt_entry
            if target_owner != owner_pid:
                messages.append(
                    f"{rel_pid}: at /relations/{i}: cross-producer Grouping — "
                    f"Grouping {gid!r} (owner {owner_pid!r}) aggregates "
                    f"{target_ref!r} owned by {target_owner!r}; "
                    f"Groupings must be producer-local"
                )

    if messages:
        raise CollectorError("groupings", messages)


def compute_rollups(
    docs: dict[str, Any],
    index: ResolutionIndex,
) -> dict[str, Any]:
    """Derive structures consumers expect to find pre-rolled in the merged
    dataset:

    - `groupings`: {grouping-id: [member-id, ...]} — every Aggregation
      sourced from a Grouping element.
    - `capabilityRealizations`: {capability-id: [realising-element-id, ...]} —
      every Realization relation whose target is a Capability.

    Iteration is in producer-sorted order and member lists are sorted so
    reruns produce byte-identical output.
    """
    groupings: dict[str, list[str]] = {}
    realizations: dict[str, list[str]] = {}

    for pid in sorted(docs):
        for rel in docs[pid].get("relations") or []:
            src_entry, _ = index.resolve(rel["source"], pid)
            tgt_entry, _ = index.resolve(rel["target"], pid)
            if src_entry is None or tgt_entry is None:
                continue
            src_kind_name, src_elem, _ = src_entry
            tgt_kind_name, tgt_elem, _ = tgt_entry
            if rel["type"] == "Aggregation" and src_kind_name == "groupings":
                groupings.setdefault(src_elem["id"], []).append(tgt_elem["id"])
            if rel["type"] == "Realization" and tgt_kind_name == "capabilities":
                realizations.setdefault(tgt_elem["id"], []).append(src_elem["id"])

    return {
        "groupings": {k: sorted(set(v)) for k, v in sorted(groupings.items())},
        "capabilityRealizations": {
            k: sorted(set(v)) for k, v in sorted(realizations.items())
        },
    }


def reconcile_alias_hints(
    docs: dict[str, Any],
    index: ResolutionIndex,
    report: dict[str, Any],
) -> None:
    """Compare the hint portion of every composite reference against the
    owner's declared hint. If a referring producer writes a hint that
    differs from the owner's, that's a divergence — captured in the
    report, not a build failure. Convergent hints (same as owner) and
    hint-less references (UUID-only) produce no entry.

    Each divergent observation is grouped per element so the report names
    every referring producer that drifted, and the owner's authoritative
    spelling.
    """
    # uuid -> {"owner_pid": ..., "owner_hint": ..., "observed": [(pid, pointer, hint), ...]}
    divergences: dict[str, dict[str, Any]] = {}

    for pid in sorted(docs):
        for i, rel in enumerate(docs[pid].get("relations") or []):
            for field in ("source", "target"):
                ref = rel[field]
                entry, ref_hint = index.resolve(ref, pid)
                if entry is None or ref_hint is None:
                    continue
                kind, elem, owner_pid = entry
                _, owner_hint, _ = parse_id(elem["id"])
                if owner_hint is None or ref_hint == owner_hint:
                    continue
                uuid_key = parse_id(elem["id"])[2]
                bucket = divergences.setdefault(
                    uuid_key,
                    {
                        "id": elem["id"],
                        "kind": kind,
                        "owner_producer": owner_pid,
                        "owner_hint": owner_hint,
                        "observed": [],
                    },
                )
                bucket["observed"].append(
                    {
                        "producer": pid,
                        "pointer": f"/relations/{i}/{field}",
                        "hint": ref_hint,
                    }
                )

    for entry in divergences.values():
        report["divergences"].append(entry)


def new_report() -> dict[str, Any]:
    """Empty validation-report scaffold. Phases append to `warnings` and
    `divergences`; the emit step (item 10) finalises `summary` and writes
    `validation-report.json`.
    """
    return {"summary": {}, "warnings": [], "divergences": []}


def _fail(err: CollectorError) -> None:
    click.echo(f"FAIL [{err.phase}] {len(err.messages)} error(s):", err=True)
    for m in err.messages:
        click.echo(f"  {m}", err=True)
    sys.exit(1)


@click.command()
@click.option(
    "--producers",
    "producers_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=PIPELINE_PRODUCERS_FILE,
    show_default=True,
    help="Path to pipeline-producers.yaml.",
)
@click.option(
    "--in",
    "input_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("producer-artifacts"),
    show_default=True,
    help="Directory holding <producer-id>/architecture.yaml inputs.",
)
@click.option(
    "--out",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("dist"),
    show_default=True,
    help="Output root; collector writes <out>/data/v0.1/*.",
)
def main(producers_path: Path, input_dir: Path, output_dir: Path) -> None:
    try:
        producers = load_pipeline_producers(producers_path, PIPELINE_PRODUCERS_SCHEMA)
    except ValueError as e:
        click.echo(f"FAIL [registry] {e}", err=True)
        sys.exit(1)

    click.echo(f"Loaded {len(producers)} registered producer(s) from {producers_path}.")
    for p in producers:
        click.echo(f"  - {p['id']} (profile={p['profile']}, jenkinsJob={p['jenkinsJob']})")

    try:
        artifact_paths = discover_artifacts(producers, input_dir)
    except CollectorError as e:
        _fail(e)

    try:
        docs = load_and_validate_artifacts(artifact_paths)
    except CollectorError as e:
        _fail(e)

    click.echo(f"Per-artifact validation: {len(docs)} producer artifact(s) clean.")

    try:
        reconcile_capability_enum(docs)
    except CollectorError as e:
        _fail(e)

    click.echo("Capability-enum reconciliation: every cap: reference resolved.")

    synth_total = synthesize_producer_relations(docs)
    click.echo(
        f"Producer-relation synthesis: appended {synth_total} Association edge(s) "
        f"across {len(docs)} artifact(s)."
    )

    try:
        merged = merge_artifacts(docs)
    except CollectorError as e:
        _fail(e)

    total_elements = sum(len(merged[k]) for k in ELEMENT_KIND_ARRAYS)
    click.echo(
        f"Merge: {total_elements} element(s) + {len(merged['relations'])} relation(s) "
        f"unioned across {len(docs)} producer(s)."
    )

    report = new_report()
    index = ResolutionIndex(docs)

    try:
        resolve_cross_references(docs, index, report)
    except CollectorError as e:
        _fail(e)

    deprecated_warnings = sum(
        1 for w in report["warnings"] if w["kind"] == "deprecated-target"
    )
    click.echo(
        "Cross-reference resolution: all references resolved"
        + (f" ({deprecated_warnings} deprecated-target warning(s))." if deprecated_warnings else ".")
    )

    reconcile_alias_hints(docs, index, report)
    n_div = len(report["divergences"])
    click.echo(
        f"Alias-hint reconciliation: "
        + ("hints agree across all observations." if n_div == 0 else
           f"{n_div} element(s) with hint divergence captured in the report.")
    )

    try:
        check_triple_matrix(docs, index)
    except CollectorError as e:
        _fail(e)

    click.echo("Triple-matrix check: every relation triple permitted by ArchiMate 3.2.")

    try:
        check_groupings(docs, index)
    except CollectorError as e:
        _fail(e)

    rollups = compute_rollups(docs, index)
    click.echo(
        f"Grouping checks + rollup: "
        f"{len(rollups['groupings'])} grouping(s), "
        f"{len(rollups['capabilityRealizations'])} capability realisation map(s)."
    )

    # Later work items extend this scaffold: emit.
    _ = output_dir, merged, report, rollups


if __name__ == "__main__":
    main()
