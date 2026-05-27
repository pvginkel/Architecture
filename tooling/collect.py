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
from pathlib import Path
from typing import Any

import click

from _arch import (
    PIPELINE_PRODUCERS_FILE,
    PIPELINE_PRODUCERS_SCHEMA,
    load_pipeline_producers,
    load_yaml,
    normalize,
    validate_doc,
)


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

    # Later work items extend this scaffold: capability-enum reconciliation,
    # merge, cross-ref, alias-hint, triple-matrix, grouping, emit.
    _ = output_dir


if __name__ == "__main__":
    main()
