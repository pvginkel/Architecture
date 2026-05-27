"""Architecture-pipeline collector.

Runs as a Docker build stage in the Architecture image. Reads each registered
producer's `architecture.yaml` from `producer-artifacts/<producer-id>/`,
validates each artifact, merges them, runs cross-producer checks, and writes
the consolidated dataset to `dist/data/v0.1/`.

v3 ships with `pipeline-producers.yaml` empty; later work items fill in the
per-artifact, capability-enum, merge, cross-ref, alias-hint, triple-matrix,
grouping, and emit stages. This file currently covers work item 2 (load the
producer registry) and grows from there.

Usage:

    poetry run python collect.py \\
        --producers pipeline-producers.yaml \\
        --in producer-artifacts \\
        --out dist
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from _arch import (
    PIPELINE_PRODUCERS_FILE,
    PIPELINE_PRODUCERS_SCHEMA,
    load_pipeline_producers,
)


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
        click.echo(f"FAIL {e}", err=True)
        sys.exit(1)

    click.echo(f"Loaded {len(producers)} registered producer(s) from {producers_path}.")
    for p in producers:
        click.echo(f"  - {p['id']} (profile={p['profile']}, jenkinsJob={p['jenkinsJob']})")

    # Later work items extend this scaffold: walk input_dir, validate each
    # artifact, merge, cross-check, write to output_dir/data/v0.1/*.
    _ = input_dir, output_dir


if __name__ == "__main__":
    main()
