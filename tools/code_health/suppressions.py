"""Per-file rule suppression via inline comments.

Add a comment in the first 10 lines of a file to suppress specific rules:

    # health: ignore cyclomatic_complexity — state machine with justified branching
    // health: ignore nesting_depth, parameter_count — generated dispatch table
    # health: ignore *  — this file is excluded from health checks

The reason after the dash is required for documentation but not parsed.
"""

from __future__ import annotations

import re
from pathlib import Path

_HEALTH_IGNORE_RE = re.compile(
    r"(?:#|//)\s*health:\s*ignore\s+([\w*][\w\s,*]*?)(?:\s*[—\-]{1,2}\s*.+)?$"
)


def parse_suppressions(filepath: Path) -> set[str]:
    """Parse health: ignore comments from the first 10 lines of a file.

    Returns a set of suppressed rule names, or {"*"} to suppress all rules.
    """
    suppressed: set[str] = set()
    try:
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                m = _HEALTH_IGNORE_RE.search(line.strip())
                if m:
                    rules = [r.strip() for r in m.group(1).split(",")]
                    suppressed.update(rules)
    except (OSError, UnicodeDecodeError):
        pass
    return suppressed
