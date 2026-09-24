"""`validate.py views` — the root gate's check on the repo's views/.

Each case points `views_validate` at a copy of the views-happy fixture's
views/ directory, intact or broken, and checks the exit code and the report.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from run_fixtures import FIXTURES

from validate import views_validate

HAPPY_VIEWS = FIXTURES / "views-happy" / "views"


@pytest.fixture
def views_dir(tmp_path: Path) -> Path:
    target = tmp_path / "views"
    shutil.copytree(HAPPY_VIEWS, target)
    return target


def test_valid_views_pass(views_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert views_validate(views_dir) == 0
    assert "OK   " in capsys.readouterr().out


def test_order_mismatch_fails(views_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (views_dir / "identity.yaml").unlink()
    assert views_validate(views_dir) == 1
    assert "FAIL [views]" in capsys.readouterr().err


def test_schema_violation_fails(views_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = views_dir / "infra.yaml"
    path.write_text(path.read_text() + "notAViewField: true\n")
    assert views_validate(views_dir) == 1
    assert "FAIL [views]" in capsys.readouterr().err


def test_missing_directory_fails(tmp_path: Path) -> None:
    assert views_validate(tmp_path / "absent") == 1
