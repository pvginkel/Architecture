"""Data models for code health analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    rule: str
    detail: str
    value: float
    threshold: float
    points: float


@dataclass
class FileReport:
    path: str
    language: str
    sloc: int = 0
    findings: list[Finding] = field(default_factory=list)

    # Rules excluded from scoring — superseded by cognitive_complexity.
    _SCORE_EXCLUDED_RULES = frozenset({"cyclomatic_complexity", "nesting_depth"})

    @property
    def score(self) -> float:
        return sum(f.points for f in self.findings if f.rule not in self._SCORE_EXCLUDED_RULES)


# Fixed breakpoints so ratings are stable across runs.
_RATING_BREAKPOINTS = [2, 5, 10, 15, 25, 35, 50, 75, 110]


def score_to_rating(score: float) -> int:
    """Convert raw score to a 1-10 health rating (10 = clean, 1 = worst)."""
    for i, bp in enumerate(_RATING_BREAKPOINTS):
        if score < bp:
            return 10 - i
    return 1
