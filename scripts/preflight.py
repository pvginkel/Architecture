#!/usr/bin/env python3
"""Pre-flight check before running a slice.

Runs the full repo build+test via build-all.py. Silent on success (exit 0); on failure dumps
build-all's buffered output. /run-slice (Step 0) invokes this before any dev agent starts, so
environment drift and broken builds are caught up front rather than surfacing mid-slice.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "scripts"


def main() -> int:
    result = subprocess.run(
        ["python3", str(SCRIPT_DIR / "build-all.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stdout.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
