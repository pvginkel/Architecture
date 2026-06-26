#!/usr/bin/env python3
"""Code health grader — ranks files by composite quality score.

Runs structural analysis tools across the Python backend and TypeScript
frontends, combines their output into a per-file score, and prints a
ranked list of worst offenders.

File exclusion is driven by .gitignore and .codehealthignore files
(both at root level and nested). No hardcoded exclusion lists.

Usage:
    poetry run code-health                  # all codebases
    poetry run code-health --backend        # Python only
    poetry run code-health --frontend       # frontend + portal TS only
    poetry run code-health --top 20         # show top 20 (default: 20)
    poetry run code-health --json           # JSON output
    poetry run code-health --all            # show all files, not just top N
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .cognitive_analyzer import run_cognitive_analysis
from .formatting import print_report
from .gitignore import load_ignore_patterns
from .models import FileReport
from .python_analyzer import analyze_python
from .ts_analyzer import analyze_typescript


def main() -> None:
    parser = argparse.ArgumentParser(description="Code health grader")
    parser.add_argument("--backend", action="store_true", help="Analyze Python backend only")
    parser.add_argument("--frontend", action="store_true", help="Analyze TypeScript frontends only")
    parser.add_argument("--top", type=int, default=20, help="Show top N files (default: 20)")
    parser.add_argument("--all", action="store_true", help="Show all files with findings")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-gitignore", action="store_true", help="Disable .gitignore/.codehealthignore filtering")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    backend_dir = root / "backend"
    frontend_dir = root / "frontend"
    portal_dir = root / "portal"

    ignore_spec = None if args.no_gitignore else load_ignore_patterns(root)

    do_backend = args.backend or (not args.backend and not args.frontend)
    do_frontend = args.frontend or (not args.backend and not args.frontend)

    reports: list[FileReport] = []

    if do_backend:
        if not args.json:
            print("Analyzing Python backend...", flush=True)
        reports.extend(analyze_python(backend_dir, root, ignore_spec))

    if do_frontend:
        for ts_dir in [frontend_dir, portal_dir]:
            if ts_dir.exists():
                if not args.json:
                    print(f"Analyzing TypeScript ({ts_dir.name})...", flush=True)
                reports.extend(analyze_typescript(ts_dir, root, ignore_spec))

    # Merge cognitive complexity findings from the TypeScript analyzer
    if not args.json:
        print("Running cognitive complexity analysis...", flush=True)
    run_cognitive_analysis(root, reports)

    top_n = None if args.all else args.top
    print_report(reports, top_n, args.json, root)


if __name__ == "__main__":
    # Pipe through a pager when connected to a TTY (unless --json)
    if sys.stdout.isatty() and "--json" not in sys.argv:
        import io
        import shutil

        buf = io.StringIO()
        _real_stdout = sys.stdout
        sys.stdout = buf

        main()

        output = buf.getvalue()
        sys.stdout = _real_stdout

        term_lines = shutil.get_terminal_size().lines
        if output.count("\n") > term_lines:
            pager = subprocess.Popen(
                ["less", "-R"],
                stdin=subprocess.PIPE,
                encoding="utf-8",
            )
            try:
                pager.communicate(input=output)
            except (BrokenPipeError, KeyboardInterrupt):
                pass
        else:
            print(output, end="")
    else:
        main()
