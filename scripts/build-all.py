#!/usr/bin/env python3
"""Build the whole Architecture monorepo: install + lint/type + build + test, per subproject.

Each STEPS entry is (component_label, action_description, command_argv, working_directory).
/run-slice's pre-flight (Step 0, via preflight.py) invokes this to catch dependency drift and
broken builds before any dev agent starts; it is also the full-suite command (Step 7).
"""

from __future__ import annotations

import sys
from pathlib import Path

from _initd_log import run_step

REPO_ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, str, list[str], Path]] = [
    ("root", "poetry install", ["poetry", "install", "--no-interaction"], REPO_ROOT),
    # tooling — Python merge pipeline (Poetry, ruff + mypy strict, pytest)
    ("tooling", "poetry install", ["poetry", "install", "--no-interaction"], REPO_ROOT / "tooling"),
    ("tooling", "ruff check", ["poetry", "run", "ruff", "check", "."], REPO_ROOT / "tooling"),
    ("tooling", "mypy", ["poetry", "run", "mypy", "."], REPO_ROOT / "tooling"),
    ("tooling", "pytest", ["poetry", "run", "pytest"], REPO_ROOT / "tooling"),
    # viewer — React + ReactFlow + ELK viewer (npm, vite, vitest)
    ("viewer", "npm ci", ["npm", "ci"], REPO_ROOT / "viewer"),
    ("viewer", "npm run build", ["npm", "run", "build"], REPO_ROOT / "viewer"),
    ("viewer", "npm test", ["npm", "test"], REPO_ROOT / "viewer"),
    # service — Express dataset/API service (npm, tsc, vitest)
    ("service", "npm ci", ["npm", "ci"], REPO_ROOT / "service"),
    ("service", "npm run build", ["npm", "run", "build"], REPO_ROOT / "service"),
    ("service", "npm test", ["npm", "test"], REPO_ROOT / "service"),
]


def main() -> int:
    for component, action, cmd, cwd in STEPS:
        if run_step(component, action, cmd, cwd) != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
