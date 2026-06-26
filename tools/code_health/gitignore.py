"""Load .gitignore and .codehealthignore patterns for file exclusion."""

from __future__ import annotations

from pathlib import Path

import pathspec

IGNORE_FILENAMES = (".gitignore", ".codehealthignore")


def _read_ignore_lines(ignore_path: Path) -> list[str]:
    """Read non-empty, non-comment lines from an ignore file."""
    if not ignore_path.is_file():
        return []
    try:
        text = ignore_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _prefix_pattern(prefix: str, pattern: str) -> str:
    """Prefix a gitignore pattern so it matches relative to the project root.

    Root-anchored patterns (starting with /) are turned into prefix-relative.
    Unanchored patterns keep their glob behavior under the prefix subtree.
    Negation patterns (!) are preserved.
    """
    negated = pattern.startswith("!")
    if negated:
        pattern = pattern[1:]

    pattern = pattern.strip()
    if not pattern:
        return ""

    if pattern.startswith("/"):
        # Root-anchored in the sub-directory -> anchor under prefix
        result = f"{prefix}{pattern}"
    else:
        # Unanchored -> match anywhere under the prefix subtree
        result = f"{prefix}/{pattern}"

    return f"!{result}" if negated else result


def load_ignore_patterns(project_root: Path) -> pathspec.PathSpec | None:
    """Load ignore patterns from .gitignore and .codehealthignore files.

    Loads both file types from the project root and all subdirectories.
    Patterns from nested files are prefixed so they match paths relative
    to the project root, mirroring git's own scoping behaviour.

    Returns a PathSpec matcher, or None if no patterns are found.
    """
    all_patterns: list[str] = []

    for filename in IGNORE_FILENAMES:
        # Root ignore file -- patterns apply as-is
        all_patterns.extend(_read_ignore_lines(project_root / filename))

        # Nested ignore files -- prefix patterns with their relative directory
        for gi_path in sorted(project_root.rglob(filename)):
            if gi_path.parent == project_root:
                continue  # already handled above
            rel_dir = str(gi_path.parent.relative_to(project_root))
            for line in _read_ignore_lines(gi_path):
                prefixed = _prefix_pattern(rel_dir, line)
                if prefixed:
                    all_patterns.append(prefixed)

    if not all_patterns:
        return None

    return pathspec.PathSpec.from_lines("gitignore", all_patterns)
