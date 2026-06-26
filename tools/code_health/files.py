"""File collection with gitignore/codehealthignore filtering."""

from __future__ import annotations

from pathlib import Path

import pathspec


def collect_files(
    directory: Path,
    extensions: set[str],
    ignore_spec: pathspec.PathSpec | None,
    root: Path,
) -> list[Path]:
    """Collect files matching extensions, respecting ignore patterns."""
    files: list[Path] = []
    for filepath in sorted(directory.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.suffix not in extensions:
            continue
        if ignore_spec is not None:
            rel = str(filepath.relative_to(root))
            if ignore_spec.match_file(rel):
                continue
        files.append(filepath)
    return files
