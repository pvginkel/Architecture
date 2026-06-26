"""TypeScript/TSX file analysis using text-based heuristics."""

from __future__ import annotations

import re
from pathlib import Path

import pathspec

from .config import TS_RULES
from .files import collect_files
from .models import FileReport, Finding
from .suppressions import parse_suppressions

# Matches function/method declarations in TypeScript.
_FUNC_RE = re.compile(
    r'(?:export\s+)?(?:async\s+)?(?:function\s+)?'
    r'(?:const\s+)?(\w+)\s*[=:]\s*(?:async\s*)?\(|'
    r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|'
    r'^\s+(\w+)\s*\([^)]*\)\s*[:{]',
)

_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch"}


def analyze_typescript(
    ts_dir: Path,
    root: Path,
    ignore_spec: pathspec.PathSpec | None,
) -> list[FileReport]:
    """Analyze all TypeScript files in a directory."""
    src_dir = ts_dir / "src"
    if not src_dir.exists():
        return []

    ts_files = collect_files(src_dir, {".ts", ".tsx"}, ignore_spec, root)

    reports: list[FileReport] = []
    for filepath in ts_files:
        report = _analyze_file(filepath)
        if report.findings:
            reports.append(report)

    return reports


# ── Single-file analysis ─────────────────────────────────────────────────


def _analyze_file(filepath: Path) -> FileReport:
    """Analyze a single TypeScript file."""
    report = FileReport(path=str(filepath), language="typescript")
    report.sloc = _count_sloc(filepath)

    suppressed = parse_suppressions(filepath)
    if "*" in suppressed:
        return report

    def add(rule: str, detail: str, value: float, thresh: float, points: float) -> None:
        if rule not in suppressed:
            report.findings.append(Finding(rule=rule, detail=detail, value=value,
                                           threshold=thresh, points=points))

    # File SLOC
    thresh, weight = TS_RULES["file_sloc"]
    if report.sloc > thresh:
        excess = report.sloc - thresh
        add("file_sloc", f"{report.sloc} SLOC (threshold {thresh})",
            report.sloc, thresh, excess * weight)

    # Structural analysis
    structure = _analyze_structure(filepath)

    # Nesting depth
    thresh, weight = TS_RULES["nesting_depth"]
    depth = structure["deep_nesting"]
    if depth > thresh:
        excess = depth - thresh
        add("nesting_depth", f"max nesting depth {depth} (threshold {thresh})",
            depth, thresh, excess * weight)

    # Parameter count
    thresh, weight = TS_RULES["parameter_count"]
    for name, count in structure["high_param_functions"]:
        if count > thresh:
            excess = count - thresh
            add("parameter_count", f"{name}(): {count} params (threshold {thresh})",
                count, thresh, excess * weight)

    return report


# ── Measurement helpers ──────────────────────────────────────────────────


def _count_sloc(filepath: Path) -> int:
    """Count non-blank, non-comment source lines for TS/TSX files."""
    count = 0
    in_block_comment = False
    try:
        with open(filepath) as f:
            for line in f:
                stripped = line.strip()
                if in_block_comment:
                    if "*/" in stripped:
                        in_block_comment = False
                    continue
                if stripped.startswith("/*"):
                    if "*/" not in stripped:
                        in_block_comment = True
                    continue
                if stripped and not stripped.startswith("//"):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def _analyze_structure(filepath: Path) -> dict:
    """Basic structural analysis using brace counting and heuristics.

    Not a full parser — estimates nesting depth and parameter counts from
    brace-depth tracking.
    """
    stats: dict = {
        "deep_nesting": 0,
        "high_param_functions": [],
    }

    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return stats

    max_nesting = 0
    brace_depth = 0

    for line in lines:
        stripped = line.strip()

        # Count braces (rough — doesn't handle strings/comments perfectly)
        opens = stripped.count("{") - stripped.count("}")

        # Detect function/method declarations
        func_match = _FUNC_RE.match(stripped)
        if func_match and "import" not in stripped:
            name = func_match.group(1) or func_match.group(2) or func_match.group(3)
            if name and name not in _CONTROL_KEYWORDS:
                param_count = _count_params(stripped)
                if param_count > 0:
                    stats["high_param_functions"].append((name, param_count))

        brace_depth += opens
        max_nesting = max(max_nesting, brace_depth)

    stats["deep_nesting"] = max_nesting

    return stats


def _count_params(line: str) -> int:
    """Count parameters from a function declaration line."""
    try:
        rest = line[line.index("("):]
    except ValueError:
        return 0

    paren_content = ""
    depth = 0
    for ch in rest:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            paren_content += ch

    if not paren_content.strip():
        return 0

    # Count top-level commas as parameter separators
    param_count = 1
    paren_depth = 0
    for ch in paren_content:
        if ch in "([{":
            paren_depth += 1
        elif ch in ")]}":
            paren_depth -= 1
        elif ch == "," and paren_depth == 0:
            param_count += 1

    return param_count
