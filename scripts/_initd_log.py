"""Classic init.d style status logging for script steps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

USE_COLOR = sys.stdout.isatty()
GREEN = "\033[32m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""

STATUS_COL = 60


def run_step(
    component: str,
    action: str,
    cmd: list[str],
    cwd: Path | None = None,
) -> int:
    """Run a subprocess and emit a classic init.d style status line.

    On success the subprocess output is discarded. On failure the captured
    stdout/stderr are printed below the status line. Returns the exit code.
    """
    label = f"[{component}] {action}"
    padding = max(1, STATUS_COL - len(label))
    sys.stdout.write(label + " " * padding)
    sys.stdout.flush()

    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

    if result.returncode == 0:
        sys.stdout.write(f"[  {GREEN}OK{RESET}  ]\n")
        sys.stdout.flush()
        return 0

    sys.stdout.write(f"[{RED}FAILED{RESET}]\n")
    sys.stdout.flush()
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")
    sys.stdout.flush()
    sys.stderr.flush()
    return result.returncode
