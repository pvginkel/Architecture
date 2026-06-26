"""Scoring rules and thresholds for code health analysis."""

from __future__ import annotations

# Thresholds — files below all thresholds score 0 and are omitted.
# Scores accumulate: a file can be penalized by multiple rules.
# Format: rule_name -> (threshold, points_per_unit_over_threshold)

PYTHON_RULES = {
    "file_sloc": (300, 0.05),           # source lines of code
    "cyclomatic_complexity": (8, 1.0),  # radon CC per function
    "parameter_count": (5, 0.5),        # params per function
    "class_method_count": (12, 0.3),    # methods per class
    "nesting_depth": (4, 1.0),          # max nesting depth
    "inline_imports": (0, 0.5),         # imports inside functions (count)
}

# Per-function-name overrides for parameter_count. Dependency-injected
# __init__ methods commonly take many collaborators; flagging them as smells
# produces false positives on ordinary service wiring.
PYTHON_PARAMETER_COUNT_OVERRIDES = {
    "__init__": (10, 0.5),
}

TS_RULES = {
    "file_sloc": (200, 0.05),
    "parameter_count": (5, 0.5),
    "nesting_depth": (4, 1.0),
}
