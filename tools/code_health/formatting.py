"""Terminal formatting and report output."""

from __future__ import annotations

import json
import os
import sys

from .models import FileReport, score_to_rating

_USE_COLOR = sys.stdout.isatty()


def _sgr(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str) -> str:
    return _sgr("1", text)


def _dim(text: str) -> str:
    return _sgr("2", text)


def _red(text: str) -> str:
    return _sgr("31", text)


def _yellow(text: str) -> str:
    return _sgr("33", text)


def _green(text: str) -> str:
    return _sgr("32", text)


def _cyan(text: str) -> str:
    return _sgr("36", text)


def _rating_color(rating: int, text: str) -> str:
    """Color a rating value: red 1-3, yellow 4-6, green 7-10."""
    if rating <= 3:
        return _red(text)
    elif rating <= 6:
        return _yellow(text)
    return _green(text)


def print_report(
    reports: list[FileReport],
    top_n: int | None,
    as_json: bool,
    root: "os.PathLike[str]",
) -> None:
    """Print the ranked report to stdout."""
    ranked = sorted(reports, key=lambda r: r.score, reverse=True)
    if top_n is not None:
        ranked = ranked[:top_n]

    if not ranked:
        print("No files exceeded any thresholds. Codebase looks healthy!")
        return

    if as_json:
        _print_json(ranked, root)
    else:
        _print_table(ranked, reports, root)


def _print_json(ranked: list[FileReport], root: "os.PathLike[str]") -> None:
    output = []
    for r in ranked:
        rel = os.path.relpath(r.path, root)
        rating = score_to_rating(r.score)
        output.append({
            "file": rel,
            "language": r.language,
            "sloc": r.sloc,
            "score": round(r.score, 1),
            "rating": rating,
            "findings": [
                {
                    "rule": f.rule,
                    "detail": f.detail,
                    "value": round(f.value, 1),
                    "threshold": round(f.threshold, 1),
                    "points": round(f.points, 1),
                }
                for f in sorted(r.findings, key=lambda x: x.points, reverse=True)
            ],
        })
    print(json.dumps(output, indent=2))


def _print_table(
    ranked: list[FileReport],
    all_reports: list[FileReport],
    root: "os.PathLike[str]",
) -> None:
    max_score = ranked[0].score if ranked else 1

    print()
    print(_bold("CODE HEALTH REPORT"))
    print(_dim("=" * 80))
    print(f"  Files analyzed: {_bold(str(len(all_reports)))}")
    print(f"  Files with findings: {_bold(str(len([r for r in all_reports if r.findings])))}")
    print(f"  Showing: top {len(ranked)}")
    print(_dim("=" * 80))
    print()

    for i, r in enumerate(ranked, 1):
        rel = os.path.relpath(r.path, root)
        bar_width = int(40 * r.score / max_score) if max_score else 0
        bar = "\u2588" * bar_width

        rating = score_to_rating(r.score)
        rating_str = _rating_color(rating, f"{rating:2d}/10")

        print(f"  {i:3d}. {rating_str}  {_bold(rel)}")
        print(f"       Score: {r.score:.1f}  {_rating_color(rating, bar)}")
        print(f"       {_dim(f'{r.language} | {r.sloc} SLOC | {len(r.findings)} findings')}")

        top_findings = sorted(r.findings, key=lambda f: f.points, reverse=True)[:3]
        for f in top_findings:
            print(f"         {_dim('-')} {f.rule}: {f.detail} {_red(f'(+{f.points:.1f})')}")

        if len(r.findings) > 3:
            remaining = sum(
                f.points for f in sorted(r.findings, key=lambda f: f.points, reverse=True)[3:]
            )
            print(f"         {_dim(f'- ... {len(r.findings) - 3} more findings (+{remaining:.1f})')}")
        print()

    _print_rule_summary(all_reports)


def _print_rule_summary(reports: list[FileReport]) -> None:
    print(_dim("-" * 80))
    print(_bold("  FINDINGS BY RULE"))
    print(_dim("-" * 80))

    rule_counts: dict[str, int] = {}
    rule_points: dict[str, float] = {}
    for r in reports:
        for f in r.findings:
            rule_counts[f.rule] = rule_counts.get(f.rule, 0) + 1
            rule_points[f.rule] = rule_points.get(f.rule, 0) + f.points

    for rule in sorted(rule_points, key=lambda k: rule_points[k], reverse=True):
        print(f"    {_cyan(f'{rule:30s}')}  {rule_counts[rule]:4d} hits  {_bold(f'{rule_points[rule]:8.1f}')} pts")
    print()
