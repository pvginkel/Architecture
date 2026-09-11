"""Tests for the architecture-update tool and the registry fields it reads.

The registry cases drive collect.py as a subprocess against a registry under
tmp_path: its startup check is what rejects a malformed `repo:`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOLING = Path(__file__).resolve().parent.parent
COLLECT = TOOLING / "collect.py"
REGISTRY = TOOLING.parent / "pipeline-producers.yaml"


def _collect(producers: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    (tmp_path / "in").mkdir()
    (tmp_path / "views").mkdir()
    return subprocess.run(
        [
            sys.executable,
            str(COLLECT),
            "--producers", str(producers),
            "--in", str(tmp_path / "in"),
            "--out", str(tmp_path / "out"),
            "--views", str(tmp_path / "views"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "repo",
    [
        "https://github.com/pvginkel/NewsFilter.git",
        "pvginkel/NewsFilter.git",
        "NewsFilter",
        "pvginkel/NewsFilter/extra",
        "-pvginkel/NewsFilter",
        "pvginkel/",
        "",
    ],
)
def test_registry_rejects_malformed_repo(tmp_path: Path, repo: str) -> None:
    registry = tmp_path / "producers.yaml"
    registry.write_text(
        yaml.safe_dump(
            {"producers": [{"id": "newsfilter", "repo": repo, "jenkinsJob": "AaC/NewsFilter"}]}
        )
    )
    proc = _collect(registry, tmp_path)
    assert proc.returncode == 1
    assert "FAIL [registry]" in proc.stderr
    assert "at /producers/0/repo:" in proc.stderr


def test_committed_registry_names_a_repo_for_every_fleet_producer(tmp_path: Path) -> None:
    producers = yaml.safe_load(REGISTRY.read_text())["producers"]
    assert [p["id"] for p in producers if "repo" not in p] == ["home-automation-fleet"]
    proc = _collect(REGISTRY, tmp_path)
    assert "FAIL [registry]" not in proc.stderr, proc.stderr
    assert f"Loaded {len(producers)} registered producer(s)" in proc.stdout
