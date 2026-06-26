"""Integration layer for the TypeScript cognitive complexity analyzer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import FileReport, Finding

# Threshold and weight for the cognitive complexity rule.
COGNITIVE_THRESHOLD = 15
COGNITIVE_WEIGHT = 0.8


def run_cognitive_analysis(
    root: Path,
    reports: list[FileReport],
) -> None:
    """Run the cognitive complexity analyzer and merge findings into reports.

    Calls the TypeScript-based analyzer as a subprocess, parses its JSON
    output, and appends cognitive_complexity findings to matching reports.
    """
    if not reports:
        return

    cognitive_dir = root / "tools" / "code_health" / "cognitive"
    tsx_bin = cognitive_dir / "node_modules" / ".bin" / "tsx"
    if not tsx_bin.exists():
        # Try workspace-hoisted location
        tsx_bin = _find_tsx(root)
        if tsx_bin is None:
            return

    index_ts = cognitive_dir / "index.ts"
    if not index_ts.exists():
        return

    # Collect all file paths from reports
    file_paths = [r.path for r in reports]

    result = subprocess.run(
        [str(tsx_bin), str(index_ts), *file_paths, "--threshold", str(COGNITIVE_THRESHOLD)],
        capture_output=True,
        text=True,
        cwd=str(cognitive_dir),
        timeout=120,
    )
    if result.returncode != 0:
        return

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return

    # Build lookup: absolute file path -> [(name, complexity)]
    lookup: dict[str, list[tuple[str, int]]] = {}
    for entry in data:
        file_path = entry["file"]
        for fn in entry["functions"]:
            lookup.setdefault(file_path, []).append(
                (fn["name"], fn["complexity"])
            )

    # Merge into reports
    for report in reports:
        abs_path = str(Path(report.path).resolve())
        functions = lookup.get(abs_path, [])
        for func_name, complexity in functions:
            excess = complexity - COGNITIVE_THRESHOLD
            if excess <= 0:
                continue
            report.findings.append(Finding(
                rule="cognitive_complexity",
                detail=f"{func_name}(): cognitive complexity {complexity} (threshold {COGNITIVE_THRESHOLD})",
                value=complexity,
                threshold=COGNITIVE_THRESHOLD,
                points=excess * COGNITIVE_WEIGHT,
            ))


def _find_tsx(root: Path) -> Path | None:
    """Search workspace node_modules for tsx binary."""
    for candidate in [
        root / "node_modules" / ".bin" / "tsx",
        root / "frontend" / "node_modules" / ".bin" / "tsx",
        root / "portal" / "node_modules" / ".bin" / "tsx",
    ]:
        if candidate.exists():
            return candidate
    return None
