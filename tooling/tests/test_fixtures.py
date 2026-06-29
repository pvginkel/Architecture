"""Run every collector fixture under tests/fixtures/ as a pytest case.

The fixtures and the runner that drives collect.py against them live in
run_fixtures.py (also usable directly as a script). This module surfaces that
suite to pytest — one parametrized case per fixture directory — so the
collector's golden-output and expected-failure checks run under
`poetry run pytest`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from run_fixtures import FIXTURES, run_fixture

FIXTURE_DIRS: list[Path] = sorted(d for d in FIXTURES.iterdir() if d.is_dir())


def test_fixtures_present() -> None:
    """Fail loudly if the fixture directory ever empties out — an empty
    parametrization would otherwise silently collect nothing."""
    assert FIXTURE_DIRS, f"no collector fixtures under {FIXTURES}"


@pytest.mark.parametrize("fixture_dir", FIXTURE_DIRS, ids=[d.name for d in FIXTURE_DIRS])
def test_collector_fixture(fixture_dir: Path) -> None:
    passed, lines = run_fixture(fixture_dir)
    assert passed, "\n".join(lines)
