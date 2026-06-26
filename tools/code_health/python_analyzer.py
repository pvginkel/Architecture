"""Python file analysis using AST inspection and radon complexity."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pathspec

from .config import PYTHON_PARAMETER_COUNT_OVERRIDES, PYTHON_RULES
from .files import collect_files
from .models import FileReport, Finding
from .suppressions import parse_suppressions


def analyze_python(
    backend_dir: Path,
    root: Path,
    ignore_spec: pathspec.PathSpec | None,
) -> list[FileReport]:
    """Analyze all Python files in the backend."""
    app_dir = backend_dir / "app"
    if not app_dir.exists():
        return []

    py_files = collect_files(app_dir, {".py"}, ignore_spec, root)
    radon_data = _run_radon_cc(app_dir)

    reports: list[FileReport] = []
    for filepath in py_files:
        report = _analyze_file(filepath)
        _merge_radon_findings(report, filepath, backend_dir, radon_data)
        if report.findings:
            reports.append(report)

    return reports


# ── Single-file analysis ─────────────────────────────────────────────────


def _analyze_file(filepath: Path) -> FileReport:
    """Analyze a single Python file using AST inspection."""
    report = FileReport(path=str(filepath), language="python")
    report.sloc = _count_sloc(filepath)

    suppressed = parse_suppressions(filepath)
    if "*" in suppressed:
        return report

    def add(rule: str, detail: str, value: float, thresh: float, points: float) -> None:
        if rule not in suppressed:
            report.findings.append(Finding(rule=rule, detail=detail, value=value,
                                           threshold=thresh, points=points))

    try:
        source = filepath.read_text()
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return report

    # File SLOC
    thresh, weight = PYTHON_RULES["file_sloc"]
    if report.sloc > thresh:
        excess = report.sloc - thresh
        add("file_sloc", f"{report.sloc} SLOC (threshold {thresh})",
            report.sloc, thresh, excess * weight)

    # Walk classes and functions
    total_inline_imports = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            _check_class(node, add)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, add)
            total_inline_imports += _count_inline_imports(node)

    # Aggregate inline imports
    thresh, weight = PYTHON_RULES["inline_imports"]
    if total_inline_imports > thresh:
        excess = total_inline_imports - thresh
        add("inline_imports", f"{total_inline_imports} inline imports",
            total_inline_imports, thresh, excess * weight)

    return report


# ── AST checks ───────────────────────────────────────────────────────────


def _check_class(node: ast.ClassDef, add: callable) -> None:
    methods = [
        n for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    method_count = len(methods)
    thresh, weight = PYTHON_RULES["class_method_count"]
    if method_count > thresh:
        excess = method_count - thresh
        add("class_method_count",
            f"{node.name}: {method_count} methods (threshold {thresh})",
            method_count, thresh, excess * weight)


def _check_function(node: ast.FunctionDef | ast.AsyncFunctionDef, add: callable) -> None:
    func_name = node.name

    # Parameter count (exclude self/cls)
    params = node.args
    param_count = len(params.args) + len(params.kwonlyargs)
    if params.args and params.args[0].arg in ("self", "cls"):
        param_count -= 1
    thresh, weight = PYTHON_PARAMETER_COUNT_OVERRIDES.get(
        func_name, PYTHON_RULES["parameter_count"]
    )
    if param_count > thresh:
        excess = param_count - thresh
        add("parameter_count",
            f"{func_name}(): {param_count} params (threshold {thresh})",
            param_count, thresh, excess * weight)

    # Nesting depth
    depth = _max_nesting_depth(node)
    thresh, weight = PYTHON_RULES["nesting_depth"]
    if depth > thresh:
        excess = depth - thresh
        add("nesting_depth",
            f"{func_name}(): nesting depth {depth} (threshold {thresh})",
            depth, thresh, excess * weight)


# ── Measurement helpers ──────────────────────────────────────────────────


def _count_sloc(filepath: Path) -> int:
    """Count non-blank, non-comment source lines."""
    count = 0
    try:
        with open(filepath) as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
    """Walk AST and find the maximum nesting depth of control structures."""
    nesting_nodes = (
        ast.If, ast.For, ast.While, ast.With, ast.Try,
        ast.AsyncFor, ast.AsyncWith,
    )
    max_depth = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, nesting_nodes):
            max_depth = max(max_depth, _max_nesting_depth(child, current + 1))
        else:
            max_depth = max(max_depth, _max_nesting_depth(child, current))
    return max_depth


def _count_inline_imports(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count import statements inside a function body."""
    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            if hasattr(child, "lineno") and node.body:
                first_line = node.body[0].lineno
                end_line = node.end_lineno or first_line
                if first_line <= child.lineno <= end_line:
                    count += 1
    return count


# ── Radon integration ────────────────────────────────────────────────────


def _run_radon_cc(app_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """Run radon cyclomatic complexity, return {filepath: [(func_name, score)]}."""
    result = subprocess.run(
        ["poetry", "run", "radon", "cc", str(app_dir), "-j", "-n", "C"],
        capture_output=True, text=True, cwd=app_dir.parent,
    )
    if result.returncode != 0 and not result.stdout:
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}

    out: dict[str, list[tuple[str, int]]] = {}
    for filepath, entries in data.items():
        for entry in entries:
            name = entry.get("name", "?")
            complexity = entry.get("complexity", 0)
            out.setdefault(filepath, []).append((name, complexity))
    return out


def _merge_radon_findings(
    report: FileReport,
    filepath: Path,
    backend_dir: Path,
    radon_data: dict[str, list[tuple[str, int]]],
) -> None:
    """Merge radon complexity findings into an existing report."""
    suppressed = parse_suppressions(filepath)
    if "cyclomatic_complexity" in suppressed or "*" in suppressed:
        return

    rel_path = str(filepath)
    for key in radon_data:
        if rel_path.endswith(key) or key.endswith(str(filepath.relative_to(backend_dir))):
            thresh, weight = PYTHON_RULES["cyclomatic_complexity"]
            for func_name, complexity in radon_data[key]:
                if complexity > thresh:
                    excess = complexity - thresh
                    report.findings.append(Finding(
                        rule="cyclomatic_complexity",
                        detail=f"{func_name}(): complexity {complexity} (threshold {thresh})",
                        value=complexity, threshold=thresh,
                        points=excess * weight,
                    ))
