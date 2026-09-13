"""Tests for the architecture-update tool and the registry fields it reads.

The registry cases drive collect.py as a subprocess against a registry under
tmp_path: its startup check is what rejects a malformed `repo:`.

The fleet cases build each producer repo as a bare git repo under tmp_path,
served over file:// in place of GitHub; the clone area, the specs repo and the
kit are under tmp_path too. The sessions go to a fake `kc` on PATH that plays
canned turns.
"""

from __future__ import annotations

import ast
import base64
import dataclasses
import email.message
import io
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

import fleet

TOOLING = Path(__file__).resolve().parent.parent
COLLECT = TOOLING / "collect.py"
REGISTRY = TOOLING.parent / "pipeline-producers.yaml"

ID = "newsfilter"
REPO = "pvginkel/NewsFilter"
JOB = "AaC/NewsFilter"
NOW = datetime(2026, 9, 11, 14, 30)

# Registry entries, as pipeline-producers.yaml writes them.
NEWSFILTER = {"id": ID, "repo": REPO, "jenkinsJob": JOB}
PAPER_CLOCK = {"id": "paper-clock", "repo": "pvginkel/PaperClock", "jenkinsJob": "AaC/PaperClock"}
HA_FLEET = {"id": "home-automation-fleet", "jenkinsJob": "AaC/Home Assistant Fleet"}

KIT = {
    "agents/triage-architecture.md": "triage agent\n",
    "agents/update-architecture.md": "update agent\n",
    "architecture/arch-validate.py": "#!/usr/bin/env python3\n",
    "architecture/producer-manual.md": "manual\n",
    "skills/seed-architecture/SKILL.md": "seed skill\n",
}


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
    assert all("jenkinsJob" in p for p in producers)
    assert [p["id"] for p in producers if p.get("self")] == ["architecture"]
    proc = _collect(REGISTRY, tmp_path)
    assert "  - architecture (jenkinsJob=AaC/Architecture, self)\n" in proc.stdout
    assert "  - ansible (jenkinsJob=AaC/Ansible)\n" in proc.stdout
    assert "FAIL [registry]" not in proc.stderr, proc.stderr
    assert f"Loaded {len(producers)} registered producer(s)" in proc.stdout


# ---- fleet.py ----


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Fleet Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "fleet-test@example.invalid")


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


class Remote:
    """A producer repo on the stand-in GitHub, and a work tree that pushes to it."""

    def __init__(self, tmp_path: Path, repo: str) -> None:
        self.bare = tmp_path / "remotes" / f"{repo}.git"
        self.work = tmp_path / "work" / repo
        self.bare.mkdir(parents=True)
        _git(self.bare, "init", "--quiet", "--bare", "-b", "main")
        _git(self.bare, "config", "uploadpack.allowFilter", "true")
        self.work.mkdir(parents=True)
        _git(self.work, "init", "--quiet", "-b", "main")
        _git(self.work, "remote", "add", "origin", str(self.bare))

    def commit(self, files: dict[str, str], executable: tuple[str, ...] = ()) -> str:
        for name, text in files.items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        for name in executable:
            (self.work / name).chmod(0o755)
        _git(self.work, "add", "--all")
        _git(self.work, "commit", "--quiet", "-m", "change")
        _git(self.work, "push", "--quiet", "origin", "HEAD")
        return _git(self.work, "rev-parse", "HEAD")


def _envelope(producer: str) -> str:
    return f'schemaVersion: "0.1"\nproducer: {producer}\n'


def _specs(tmp_path: Path) -> Path:
    """The specs repo the run writes to: a work tree with a bare origin to push to."""
    specs, bare = tmp_path / "specs", tmp_path / "specs.git"
    bare.mkdir()
    _git(bare, "init", "--quiet", "--bare", "-b", "main")
    specs.mkdir()
    _git(specs, "init", "--quiet", "-b", "main")
    _git(specs, "remote", "add", "origin", str(bare))
    (specs / "README.md").write_text("the specs repo\n")
    _git(specs, "add", "README.md")
    _git(specs, "commit", "--quiet", "-m", "the specs repo")
    _git(specs, "push", "--quiet", "-u", "origin", "main")
    return specs


def _fleet(tmp_path: Path, *producers: dict[str, str]) -> fleet.Fleet:
    kit = tmp_path / "kit"
    for rel, text in {**KIT, "skills/architecture-update/SKILL.md": "operator-side\n"}.items():
        (kit / rel).parent.mkdir(parents=True, exist_ok=True)
        (kit / rel).write_text(text)
    (kit / "architecture/arch-validate.py").chmod(0o755)
    registry = tmp_path / "producers.yaml"
    registry.write_text(yaml.safe_dump({"producers": list(producers)}))
    return fleet.Fleet(
        registry=registry,
        kit=kit,
        clones=tmp_path / "clones",
        spec_repo=_specs(tmp_path),
        remote_base=f"file://{tmp_path / 'remotes'}",
    )


def _scan(f: fleet.Fleet, reviewed: str | None = None) -> fleet.Scan:
    producer = fleet.Producer(ID, REPO, JOB)
    return fleet.scan_producer(f, producer, REPO, fleet.Review(reviewed), fleet.Jenkins.from_env())


def test_default_sources_find_nested_artifacts(tmp_path: Path) -> None:
    remote = Remote(tmp_path, REPO)
    watermark = remote.commit(
        {
            "backend/docs/architecture/architecture.yaml": _envelope(ID),
            "frontend/docs/architecture/architecture.yaml": _envelope(ID),
        }
    )
    remote.commit({"backend/app.py": "one\n"})
    remote.commit({"backend/app.py": "two\n"})
    result = _scan(_fleet(tmp_path))
    assert result.config == fleet.RepoConfig()
    assert (result.watermark, result.base, result.commits) == (watermark, watermark, 2)
    assert result.shortstat == "1 file changed, 1 insertion(+)"
    assert not result.current


def test_a_producer_whose_sources_changed_last_is_current(tmp_path: Path) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({"src/app.py": "app\n"})
    head = remote.commit({"docs/architecture/architecture.yaml": _envelope(ID)})
    result = _scan(_fleet(tmp_path))
    assert result.current
    assert (result.base, result.clone.head, result.commits) == (head, head, 0)


def test_architecturerc_sets_mode_sources_and_instructions(
    tmp_path: Path, jenkins: FakeJenkins
) -> None:
    rc = {
        "generated": True,
        "sources": ["*/architecture.yaml"],
        "instructions": "Edit the annotations.\n",
    }
    remote = Remote(tmp_path, REPO)
    watermark = remote.commit(
        {".architecturerc": yaml.safe_dump(rc), "app-a/architecture.yaml": "images: {}\n"}
    )
    remote.commit({"docs/architecture/notes.md": "not a source here\n"})
    jenkins.job(JOB)
    result = _scan(_fleet(tmp_path))
    assert result.config == fleet.RepoConfig(
        generated=True, sources=("*/architecture.yaml",), instructions="Edit the annotations.\n"
    )
    assert (result.watermark, result.commits, result.gaps) == (watermark, 1, ())


@pytest.mark.parametrize(
    "text, reason",
    [
        ("generated: maybe\n", "`generated` must be true or false"),
        ("sources: docs/architecture\n", "`sources` must be a non-empty list of pathspecs"),
        ("sources: []\n", "`sources` must be a non-empty list of pathspecs"),
        ("sources: [1]\n", "`sources` must be a non-empty list of pathspecs"),
        ("instructions: [a, b]\n", "`instructions` must be text"),
        ("generated: true\nmode: generated\n", "unknown key(s): mode"),
        ("- generated\n", "must be a mapping"),
        ("", "must be a mapping"),
        ("sources: [unclosed\n", "not valid YAML"),
    ],
)
def test_a_malformed_architecturerc_fails_the_producer(
    tmp_path: Path, text: str, reason: str
) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({".architecturerc": text, "docs/architecture/a.yaml": _envelope(ID)})
    with pytest.raises(fleet.ProducerError) as failure:
        _scan(_fleet(tmp_path))
    assert str(failure.value).startswith(".architecturerc: ")
    assert reason in str(failure.value)


def test_architecturerc_is_read_from_origin_head_not_the_working_tree(tmp_path: Path) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit(
        {".architecturerc": "instructions: from the remote\n", "docs/architecture/a.yaml": "x\n"}
    )
    clone = fleet.prepare(_fleet(tmp_path), REPO)
    (clone.path / ".architecturerc").write_text("generated: true\n")
    assert fleet.read_repo_config(clone.path, clone.head) == fleet.RepoConfig(
        instructions="from the remote"
    )


def test_a_repo_with_no_sources_at_origin_head_fails(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"README.md": "readme\n"})
    with pytest.raises(fleet.ProducerError, match="no sources at origin/HEAD"):
        _scan(_fleet(tmp_path))


def test_a_source_envelope_naming_another_producer_fails(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope("ginbov-nl")})
    with pytest.raises(fleet.ProducerError) as failure:
        _scan(_fleet(tmp_path))
    assert "declares `producer: ginbov-nl`, the registry entry is newsfilter" in str(
        failure.value
    )


def test_notes_and_data_files_among_the_sources_are_passed_over(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit(
        {
            "backend/docs/architecture/SEED-NOTES.md": "notes\n",
            "backend/docs/architecture/a-firmware.yaml": "firmware: {}\n",
            "backend/docs/architecture/architecture.yaml": _envelope(ID),
            "frontend/docs/architecture/architecture.yaml": _envelope(ID),
        }
    )
    assert _scan(_fleet(tmp_path)).current


def test_hand_authored_sources_without_an_envelope_fail(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": "images: {}\n"})
    with pytest.raises(fleet.ProducerError, match="no source declares a `producer:` envelope"):
        _scan(_fleet(tmp_path))


@pytest.mark.parametrize(
    "reviewed_at, base_at, commits",
    [
        (None, "watermark", 2),
        ("before", "watermark", 2),
        ("middle", "middle", 1),
        ("head", "head", 0),
    ],
)
def test_the_base_is_the_later_of_watermark_and_reviewed(
    tmp_path: Path, reviewed_at: str | None, base_at: str, commits: int
) -> None:
    remote = Remote(tmp_path, REPO)
    shas = {
        "before": remote.commit({"README.md": "readme\n"}),
        "watermark": remote.commit({"docs/architecture/a.yaml": _envelope(ID)}),
        "middle": remote.commit({"src/app.py": "one\n"}),
        "head": remote.commit({"src/app.py": "two\n"}),
    }
    f = _fleet(tmp_path, NEWSFILTER)
    if reviewed_at is not None:
        state = f.spec_repo / "architecture-updates" / "state.yaml"
        state.parent.mkdir(parents=True)
        entry = {"reviewed": shas[reviewed_at], "date": "2026-09-11", "outcome": "skipped"}
        state.write_text(yaml.safe_dump({ID: entry}))
    [row] = fleet.scan(f, fleet.Jenkins.from_env())
    if commits == 0:
        assert (row.status, row.detail) == (fleet.CURRENT, "")
    else:
        assert row.status == fleet.STALE
        assert row.detail.startswith(f"{commits} commit")
        assert f"since {shas[base_at][:12]}: " in row.detail


def test_a_reviewed_commit_outside_origin_heads_history_fails(tmp_path: Path) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({"docs/architecture/a.yaml": _envelope(ID)})
    _git(remote.work, "checkout", "--quiet", "-b", "side")
    side = remote.commit({"src/app.py": "side\n"})
    with pytest.raises(fleet.ProducerError, match="is not in origin/HEAD's history"):
        _scan(_fleet(tmp_path), reviewed=side)


def test_a_missing_state_file_means_nothing_is_reviewed(tmp_path: Path) -> None:
    assert fleet.load_state(tmp_path) == {}


def test_the_gaps_advance_with_reviewed_and_are_kept_while_it_is_not(tmp_path: Path) -> None:
    """A delivery that fails keeps the gaps its session was handed but advances nothing."""
    producer = fleet.Producer(ID, REPO, JOB)
    gaps = ("app: image 'queue' (in app/queue)",)
    fleet.record_state(
        tmp_path, fleet.Outcome(producer, fleet.CURRENT, reviewed="a" * 40, gaps=gaps), "2026-09-11"
    )
    assert yaml.safe_load((tmp_path / fleet.STATE_FILE).read_text()) == {
        ID: {"reviewed": "a" * 40, "gaps": list(gaps), "date": "2026-09-11", "outcome": "current"}
    }
    detail = "git push failed: protected branch"
    failed = fleet.Outcome(producer, fleet.FAILED, detail, gaps=("another",), issues=(detail,))
    fleet.record_state(tmp_path, failed, "2026-09-12")
    assert fleet.load_state(tmp_path) == {ID: fleet.Review("a" * 40, gaps)}
    fleet.record_state(
        tmp_path, fleet.Outcome(producer, fleet.CURRENT, reviewed="b" * 40), "2026-09-13"
    )
    assert yaml.safe_load((tmp_path / fleet.STATE_FILE).read_text()) == {
        ID: {"reviewed": "b" * 40, "date": "2026-09-13", "outcome": "current"}
    }


def test_a_state_entry_without_reviewed_is_read_past_and_kept_until_a_run_advances_it(
    tmp_path: Path,
) -> None:
    """A failed first run leaves an entry with no `reviewed`; every later read must skip it."""
    producer = fleet.Producer(ID, REPO, JOB)
    detail = "triage session timed out after 600 s"
    failed = fleet.Outcome(producer, fleet.FAILED, detail, issues=(detail,))
    fleet.record_state(tmp_path, failed, "2026-09-11")
    state = tmp_path / fleet.STATE_FILE
    assert yaml.safe_load(state.read_text()) == {
        ID: {"date": "2026-09-11", "outcome": f"failed: {detail}"}
    }
    assert fleet.load_state(tmp_path) == {ID: fleet.Review()}
    other = fleet.Outcome(
        fleet.Producer("paper-clock", "x/PaperClock", "AaC/PaperClock"),
        fleet.CURRENT,
        reviewed="a" * 40,
    )
    fleet.record_state(tmp_path, other, "2026-09-12")
    fleet.record_state(tmp_path, failed, "2026-09-12")
    assert fleet.load_state(tmp_path) == {
        ID: fleet.Review(),
        "paper-clock": fleet.Review("a" * 40),
    }
    skipped = fleet.Outcome(producer, fleet.SKIPPED, "Only CI.", reviewed="b" * 40)
    fleet.record_state(tmp_path, skipped, "2026-09-13")
    assert fleet.load_state(tmp_path) == {
        ID: fleet.Review("b" * 40),
        "paper-clock": fleet.Review("a" * 40),
    }


def test_the_specs_repo_is_aiworkflowrcs_spec_repo(tmp_path: Path) -> None:
    rc = tmp_path / "Architecture" / ".aiworkflowrc"
    rc.parent.mkdir()
    rc.write_text('spec_repo = "../ArchitectureSpecs"\n\n[push]\nenabled = true\n')
    assert fleet.spec_repo_from(rc) == tmp_path.resolve() / "ArchitectureSpecs"


def test_staging_copies_the_kit_excludes_it_and_leaves_the_clone_clean(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    clone = fleet.prepare(_fleet(tmp_path), REPO)
    assert (clone.path, clone.branch) == (tmp_path / "clones" / "NewsFilter", "main")
    claude = clone.path / ".claude"
    staged = {p.relative_to(claude).as_posix(): p for p in claude.rglob("*") if p.is_file()}
    assert {rel: p.read_text() for rel, p in staged.items()} == KIT
    assert stat.S_IMODE(staged["architecture/arch-validate.py"].stat().st_mode) == 0o755
    exclude = (clone.path / ".git" / "info" / "exclude").read_text().splitlines()
    assert {f"/.claude/{rel}" for rel in KIT} <= set(exclude)
    assert _git(clone.path, "status", "--porcelain") == ""
    assert _git(clone.path, "config", "remote.origin.partialclonefilter") == "blob:none"


def test_staging_an_existing_clone_fetches_and_excludes_each_path_once(tmp_path: Path) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path)
    fleet.prepare(f, REPO)
    head = remote.commit({"src/app.py": "app\n"})
    clone = fleet.prepare(f, REPO)
    assert clone.head == head == _git(clone.path, "rev-parse", "HEAD")
    exclude = (clone.path / ".git" / "info" / "exclude").read_text().splitlines()
    assert all(exclude.count(f"/.claude/{rel}") == 1 for rel in KIT)


@pytest.mark.parametrize(
    "tracked",
    [
        {"agents/update-architecture.md": "the producer's own agent\n"},
        {"architecture/arch-validate.py": KIT["architecture/arch-validate.py"]},
    ],
    ids=["content", "mode"],
)
def test_a_tracked_file_conflicting_with_the_kit_is_refused_every_run_untouched(
    tmp_path: Path, tracked: dict[str, str]
) -> None:
    files = {f".claude/{rel}": text for rel, text in tracked.items()}
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID), **files})
    f = _fleet(tmp_path)
    clone = f.clones / "NewsFilter"
    for _ in range(2):
        with pytest.raises(fleet.ProducerError) as failure:
            fleet.prepare(f, REPO)
        assert str(failure.value) == (
            f"the repo tracks kit files that differ from the kit: {', '.join(files)}"
        )
        assert _git(clone, "status", "--porcelain") == ""
        assert {name: (clone / name).read_text() for name in files} == files


def test_a_gitignore_re_including_kit_paths_is_refused_every_run_with_the_copies_removed(
    tmp_path: Path,
) -> None:
    Remote(tmp_path, REPO).commit(
        {"docs/architecture/a.yaml": _envelope(ID), ".gitignore": "!/.claude/agents/*.md\n"}
    )
    f = _fleet(tmp_path)
    clone = f.clones / "NewsFilter"
    for _ in range(2):
        with pytest.raises(fleet.ProducerError) as failure:
            fleet.prepare(f, REPO)
        assert str(failure.value) == (
            "the repo's .gitignore re-includes kit paths, which .git/info/exclude cannot hide: "
            "?? .claude/agents/triage-architecture.md; ?? .claude/agents/update-architecture.md"
        )
        assert not (clone / ".claude").exists()
        assert _git(clone, "status", "--porcelain") == ""


def test_a_repo_tracking_the_kit_identically_is_staged(tmp_path: Path) -> None:
    files = {f".claude/{rel}": text for rel, text in KIT.items()}
    Remote(tmp_path, "pvginkel/Architecture").commit(
        {**files, "docs/architecture/a.yaml": _envelope("architecture")},
        executable=(".claude/architecture/arch-validate.py",),
    )
    clone = fleet.prepare(_fleet(tmp_path), "pvginkel/Architecture")
    assert _git(clone.path, "status", "--porcelain") == ""


def test_the_self_producer_refused_for_an_unpushed_kit_edit_stages_once_it_is_pushed(
    tmp_path: Path,
) -> None:
    repo = "pvginkel/Architecture"
    remote = Remote(tmp_path, repo)
    remote.commit(
        {
            **{f".claude/{rel}": text for rel, text in KIT.items()},
            "docs/architecture/a.yaml": _envelope("architecture"),
        },
        executable=(".claude/architecture/arch-validate.py",),
    )
    f = _fleet(tmp_path)
    fleet.prepare(f, repo)
    (f.kit / "agents/update-architecture.md").write_text("edited agent\n")
    with pytest.raises(
        fleet.ProducerError, match=r"differ from the kit: \.claude/agents/update-architecture\.md$"
    ):
        fleet.prepare(f, repo)
    remote.commit({".claude/agents/update-architecture.md": "edited agent\n"})
    clone = fleet.prepare(f, repo)
    assert _git(clone.path, "status", "--porcelain") == ""


def test_a_clone_with_unpushed_commits_is_refused(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path)
    clone = fleet.prepare(f, REPO)
    (clone.path / "src.py").write_text("local\n")
    _git(clone.path, "add", "src.py")
    _git(clone.path, "commit", "--quiet", "-m", "local")
    with pytest.raises(fleet.ProducerError, match="unpushed commits in .*: push or discard"):
        fleet.prepare(f, REPO)


def test_a_clone_with_uncommitted_changes_is_refused(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path)
    clone = fleet.prepare(f, REPO)
    (clone.path / "docs/architecture/a.yaml").write_text("edited\n")
    with pytest.raises(fleet.ProducerError, match="uncommitted changes in "):
        fleet.prepare(f, REPO)


def test_scan_reports_each_producer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stale = Remote(tmp_path, REPO)
    base = stale.commit({"docs/architecture/a.yaml": _envelope(ID)})
    stale.commit({"src/app.py": "app\n"})
    Remote(tmp_path, "pvginkel/PaperClock").commit(
        {"docs/architecture/a.yaml": _envelope("paper-clock")}
    )
    Remote(tmp_path, "pvginkel/Ginbov").commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(
        tmp_path,
        NEWSFILTER,
        PAPER_CLOCK,
        HA_FLEET,
        {"id": "ginbov-nl", "repo": "pvginkel/Ginbov", "jenkinsJob": "AaC/Ginbov"},
    )
    assert fleet.run(["scan"], f, NOW) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"newsfilter             pvginkel/NewsFilter  stale              "
        f"1 commit since {base[:12]}: 1 file changed, 1 insertion(+)",
        "paper-clock            pvginkel/PaperClock  current",
        "home-automation-fleet  -                    not fleet-managed",
        "ginbov-nl              pvginkel/Ginbov      failed             "
        "docs/architecture/a.yaml declares `producer: newsfilter`, "
        "the registry entry is ginbov-nl: is its `repo` right?",
    ]


def test_scan_exits_zero_when_no_producer_fails(tmp_path: Path) -> None:
    assert fleet.run(["scan"], _fleet(tmp_path, HA_FLEET), NOW) == 0


def test_stage_takes_an_unregistered_repo_as_owner_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = Remote(tmp_path, "pvginkel/NewRepo").commit({"README.md": "readme\n"})
    assert fleet.run(["stage", "pvginkel/NewRepo"], _fleet(tmp_path), NOW) == 0
    clone = tmp_path / "clones" / "NewRepo"
    assert (clone / ".claude" / "agents" / "triage-architecture.md").is_file()
    assert capsys.readouterr().out == f"staged {clone} at main {head[:12]}\n"


def test_stage_resolves_a_registered_repos_bare_name(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"README.md": "readme\n"})
    f = _fleet(tmp_path, NEWSFILTER)
    assert fleet.run(["stage", "NewsFilter"], f, NOW) == 0
    assert (tmp_path / "clones" / "NewsFilter" / ".claude" / "architecture").is_dir()


@pytest.mark.parametrize(
    "name, reason",
    [
        ("NewRepo", "NewRepo is not a registered repo; name it as <owner>/NewRepo"),
        ("a/b/c", "a/b/c: expected a repo name or owner/name"),
    ],
)
def test_stage_rejects_a_name_it_cannot_resolve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, reason: str
) -> None:
    assert fleet.run(["stage", name], _fleet(tmp_path), NOW) == 1
    assert capsys.readouterr().err == f"stage {name}: {reason}\n"


def test_the_default_fleet_stages_this_repos_kit() -> None:
    f = fleet.Fleet.default()
    assert f.clones == Path("/tmp/architecture-update/repos")
    assert f.spec_repo == (TOOLING.parent.parent / "ArchitectureSpecs").resolve()
    assert f.url(REPO) == "https://github.com/pvginkel/NewsFilter.git"
    assert [p.as_posix() for p in fleet.kit_files(f.kit)] == [
        "agents/triage-architecture.md",
        "agents/update-architecture.md",
        "architecture/arch-validate.py",
        "architecture/architecture.yaml",
        "architecture/producer-manual.md",
        "skills/seed-architecture/SKILL.md",
    ]


def test_fleet_imports_only_the_standard_library_and_pyyaml() -> None:
    tree = ast.parse(Path(fleet.__file__).read_text())
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert modules - sys.stdlib_module_names == {"yaml"}


# ---- fleet.py update: the sessions ----

FAKE_KC = """\
import json, os, signal, subprocess, sys, time
from pathlib import Path

log = Path(os.environ["FAKE_KC_LOG"])
calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
args = sys.argv[1:]


def record(**extra):
    with log.open("a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd(), **extra}) + "\\n")


def count(verb):
    return sum(c["args"][1] == verb for c in calls if not c.get("interrupted"))


verb = args[1]
if verb == "create-headless":
    record()
    if os.environ.get("FAKE_KC_REFUSE"):
        print(os.environ["FAKE_KC_REFUSE"], file=sys.stderr)
        sys.exit(1)
    print(f"fake-{count('create-headless')}")
elif verb == "send":
    # Installed before anything else in this branch (turn/JSON parsing, the prompt-file
    # read, record()'s own file I/O) so a SIGINT is handled the same way no matter how
    # slow this interpreter is to start up on a loaded machine: it no longer has to land
    # while we're inside a `time.sleep()` try/except to be caught correctly.
    def on_interrupt(signum, frame):
        record(interrupted=True)
        sys.exit(130)

    signal.signal(signal.SIGINT, on_interrupt)
    turn = json.loads(Path(os.environ["FAKE_KC_TURNS"]).read_text())[count("send")]
    record(prompt=Path(args[args.index("--prompt-file") + 1]).read_text())
    if turn.get("ignore_interrupt"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    for path, text in turn.get("write", {}).items():
        Path(path).write_text(text)
    for path, text in turn.get("commit", {}).items():
        Path(path).write_text(text)
        subprocess.run(["git", "add", path], check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", f"architecture: {path}"], check=True)
    time.sleep(turn.get("sleep", 0))
    Path(args[args.index("--response-file") + 1]).write_text(turn.get("response", ""))
    sys.exit(turn.get("exit", 0))
elif verb == "status":
    record()
    plays = os.environ.get("FAKE_KC_STATUS", "")
    if plays == "refuse":
        sys.exit(1)
    if plays == "hang":
        time.sleep(30)
    if plays == "garbage":
        print("session fake-0: idle")
        sys.exit(0)
    print(json.dumps({"sessionId": "sid-" + args[2], "state": "idle"}))
else:
    record()
    if verb == "end" and os.environ.get("FAKE_KC_END") == "hang":
        time.sleep(30)
"""


class FakeKc:
    """A `kc` on PATH that plays one canned turn per send and logs every call."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        kc = bin_dir / "kc"
        kc.write_text(f"#!{sys.executable}\n{FAKE_KC}")
        kc.chmod(0o755)
        self.log = tmp_path / "kc.jsonl"
        self.turns = tmp_path / "kc-turns.json"
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_KC_LOG", str(self.log))
        monkeypatch.setenv("FAKE_KC_TURNS", str(self.turns))
        self.play()

    def play(self, *turns: dict[str, Any]) -> None:
        self.turns.write_text(json.dumps(turns))

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def verbs(self) -> list[str]:
        return [c["args"][1] for c in self.calls() if not c.get("interrupted")]

    def creates(self) -> list[list[str]]:
        return [c["args"][2:] for c in self.calls() if c["args"][1] == "create-headless"]

    def prompts(self) -> list[str]:
        return [c["prompt"] for c in self.calls() if "prompt" in c]


@pytest.fixture
def kc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeKc:
    return FakeKc(tmp_path, monkeypatch)


SESSION = ["create-headless", "send", "status", "end"]
SKIP = {"response": "Only CI changed.\n\nVERDICT: skip\nOnly CI housekeeping.\n"}
UPDATE = {"response": "VERDICT: update\nThe app now consumes a queue.\n"}
NOTHING = {"response": "0 deltas applied, 0 commits, validator clean.\nSkipped: none\n"}
UNPARSEABLE = fleet.Verdict(True, "no parseable verdict; counted as update")
PRODUCER = fleet.Producer(ID, REPO, JOB)


def _stale(tmp_path: Path, rc: dict[str, Any] | None = None) -> tuple[fleet.Fleet, str, str]:
    remote = Remote(tmp_path, REPO)
    files = {"docs/architecture/a.yaml": _envelope(ID)}
    if rc is not None:
        files[".architecturerc"] = yaml.safe_dump(rc)
    base = remote.commit(files)
    head = remote.commit({"src/app.py": "app\n"})
    return _fleet(tmp_path, NEWSFILTER), base, head


def _state(f: fleet.Fleet) -> dict[str, Any]:
    state: dict[str, Any] = yaml.safe_load((f.spec_repo / fleet.STATE_FILE).read_text())
    return state


def _update(f: fleet.Fleet) -> fleet.Outcome:
    [outcome] = fleet.update(f, [PRODUCER], NOW, fleet.Jenkins.from_env())
    return outcome


@pytest.mark.parametrize(
    "response, verdict",
    [
        (SKIP["response"], fleet.Verdict(False, "Only CI housekeeping.")),
        ("VERDICT: update\nroles/dns adds a zone.", fleet.Verdict(True, "roles/dns adds a zone.")),
        ("VERDICT: skip\n\n  Only tests.  \n\n", fleet.Verdict(False, "Only tests.")),
        ("VERDICT: skip\nOnly tests.\nAnything else?", UNPARSEABLE),
        ("Only tests.\nVERDICT: skip", UNPARSEABLE),
        ("VERDICT: maybe\nUnsure.", UNPARSEABLE),
        ("**VERDICT: skip**\nOnly tests.", UNPARSEABLE),
        ("", UNPARSEABLE),
    ],
)
def test_the_triage_verdict_is_its_final_two_lines(response: str, verdict: fleet.Verdict) -> None:
    assert fleet.parse_verdict(response) == verdict


@pytest.mark.parametrize(
    "response, handoff",
    [
        (
            "Walked 3 commits.\n\n2 deltas applied, 2 commits, validator clean.\nSkipped: none\n",
            fleet.Handoff(2, 2, "validator clean", None, "none"),
        ),
        (
            "1 delta applied, 1 commit, validation by the AaC build.\nSkipped: ss:foo (no logo)",
            fleet.Handoff(1, 1, "validation by the AaC build", None, "ss:foo (no logo)"),
        ),
        (
            "0 deltas applied, 0 commits, stopped: the manual is missing.\nSkipped: none",
            fleet.Handoff(0, 0, "stopped: the manual is missing", "the manual is missing", "none"),
        ),
    ],
)
def test_the_update_handoff_is_its_final_two_lines(response: str, handoff: fleet.Handoff) -> None:
    assert fleet.parse_handoff(response) == handoff


@pytest.mark.parametrize(
    "response",
    [
        "2 deltas applied, 2 commits, validator clean.",
        "2 deltas applied, 2 commits, validator clean.\nSkipped: none\nAnything else?",
        "2 deltas applied, 2 commits, validator failed.\nSkipped: none",
        "2 deltas applied, 2 commits, validator clean\nSkipped: none",
        "`2 deltas applied, 2 commits, validator clean.`\nSkipped: none",
        "",
    ],
)
def test_anything_else_is_no_handoff(response: str) -> None:
    assert fleet.parse_handoff(response) is None


def test_the_handoff_text_reads_back_as_the_agent_wrote_it() -> None:
    assert fleet.Handoff(1, 2, "validator clean", None, "none").text == (
        "1 delta applied, 2 commits, validator clean. Skipped: none"
    )


def test_a_session_is_created_sent_its_id_read_and_ended(tmp_path: Path, kc: FakeKc) -> None:
    kc.play({"response": "the answer\n"})
    session = fleet.run_session(tmp_path, fleet.UPDATE, "the prompt\n")
    assert session == fleet.Session(None, "the answer\n", "sid-fake-0")
    create, send, status, end = kc.calls()
    assert create["args"] == [
        "session", "create-headless", "--cwd", str(tmp_path),
        "--agent", "update-architecture", "--model", "opus", "--reasoning-effort", "xhigh",
    ]
    assert send["args"][:3] == ["session", "send", "fake-0"]
    assert send["args"][3::2] == ["--prompt-file", "--response-file", "-v"]
    assert send["prompt"] == "the prompt\n"
    assert status["args"] == ["session", "status", "fake-0", "--output=json"]
    assert end["args"] == ["session", "end", "fake-0"]
    assert {c["cwd"] for c in kc.calls()} == {str(tmp_path)}


@pytest.mark.parametrize(
    "turn, interrupted",
    [({"sleep": 30}, True), ({"sleep": 30, "ignore_interrupt": True}, False)],
    ids=["interrupted", "killed"],
)
def test_a_session_past_its_timeout_is_interrupted_then_killed_and_ended(
    tmp_path: Path,
    kc: FakeKc,
    monkeypatch: pytest.MonkeyPatch,
    turn: dict[str, Any],
    interrupted: bool,
) -> None:
    monkeypatch.setattr(fleet, "INTERRUPT_GRACE", 1)
    kc.play(turn)
    agent = dataclasses.replace(fleet.TRIAGE, timeout=1)
    assert fleet.run_session(tmp_path, agent, "p") == fleet.Session("timed out after 1 s", "", None)
    assert kc.verbs() == ["create-headless", "send", "end"]
    assert any(c.get("interrupted") for c in kc.calls()) is interrupted


@pytest.mark.parametrize("plays", ["refuse", "hang", "garbage"])
def test_a_status_that_cannot_be_read_costs_only_the_session_id(
    tmp_path: Path, kc: FakeKc, monkeypatch: pytest.MonkeyPatch, plays: str
) -> None:
    monkeypatch.setattr(fleet, "KC_TIMEOUT", 1)
    monkeypatch.setenv("FAKE_KC_STATUS", plays)
    kc.play({"response": "the answer\n"})
    session = fleet.run_session(tmp_path, fleet.TRIAGE, "p")
    assert session == fleet.Session(None, "the answer\n", None)
    assert kc.verbs() == SESSION


def test_an_end_that_hangs_is_reported_and_let_go(
    tmp_path: Path, kc: FakeKc, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(fleet, "KC_TIMEOUT", 1)
    monkeypatch.setenv("FAKE_KC_END", "hang")
    kc.play({"response": "the answer\n"})
    session = fleet.run_session(tmp_path, fleet.TRIAGE, "p")
    assert session == fleet.Session(None, "the answer\n", "sid-fake-0")
    assert kc.verbs() == SESSION
    assert capsys.readouterr().err == "kc session end fake-0 did not finish within 1 s\n"


def test_a_session_exiting_non_zero_fails_and_is_ended(tmp_path: Path, kc: FakeKc) -> None:
    kc.play({"response": "partial", "exit": 2})
    session = fleet.run_session(tmp_path, fleet.TRIAGE, "p")
    assert session == fleet.Session("exited 2", "partial", None)
    assert kc.verbs() == ["create-headless", "send", "end"]


def test_a_session_kc_will_not_create_fails(
    tmp_path: Path, kc: FakeKc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_KC_REFUSE", "no capacity")
    session = fleet.run_session(tmp_path, fleet.TRIAGE, "p")
    assert session == fleet.Session("did not start: no capacity", "", None)
    assert kc.verbs() == ["create-headless"]


def test_a_skip_verdict_advances_reviewed_without_an_update_session(
    tmp_path: Path, kc: FakeKc, capsys: pytest.CaptureFixture[str]
) -> None:
    f, _, head = _stale(tmp_path)
    kc.play(SKIP)
    assert fleet.run(["update"], f, NOW) == 0
    assert kc.verbs() == SESSION
    clone = str(tmp_path / "clones" / "NewsFilter")
    assert kc.creates() == [
        ["--cwd", clone, "--agent", "triage-architecture", "--model", "sonnet"]
    ]
    assert {c["cwd"] for c in kc.calls()} == {clone}
    assert _state(f) == {
        ID: {"reviewed": head, "date": "2026-09-11", "outcome": "skipped: Only CI housekeeping."}
    }
    assert capsys.readouterr().out.splitlines() == [
        "newsfilter  pvginkel/NewsFilter  skipped            Only CI housekeeping.",
        f"report: {f.spec_repo / fleet.report_file(NOW)}",
        "unresolved: 0",
        "judgment calls: 0",
    ]


def test_the_triage_prompt_carries_the_brief_and_the_instructions_verbatim(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins
) -> None:
    instructions = "Annotations live in values.yaml.\n  Keep their indent.\n"
    rc = {"generated": True, "sources": ["*/architecture.yaml"], "instructions": instructions}
    remote = Remote(tmp_path, REPO)
    base = remote.commit(
        {".architecturerc": yaml.safe_dump(rc), "app/architecture.yaml": "images: {}\n"}
    )
    remote.commit({"src/app.py": "app\n"})
    jenkins.job(JOB)
    kc.play(SKIP)
    _update(_fleet(tmp_path, NEWSFILTER))
    assert kc.prompts() == [
        f"Does anything in {base}..HEAD (1 commit) change what producer `newsfilter`'s "
        "architecture must say? End with your two-line verdict.\n\n"
        "- Producer id: newsfilter\n"
        "- Mode: generated\n"
        "- Sources: `*/architecture.yaml`\n"
        f"- Base commit: {base}\n"
        "\nThe repo's instructions, verbatim from its `.architecturerc`:\n\n"
        f"{instructions}\n"
    ]


def test_an_update_verdict_runs_the_update_session_with_its_brief(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f, base, _ = _stale(tmp_path)
    handoff = "1 delta applied, 1 commit, validator clean.\nSkipped: none\n"
    edit = {"docs/architecture/a.yaml": _envelope(ID) + "# the queue\n"}
    kc.play(UPDATE, {"commit": edit, "response": handoff})
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42)]})
    outcome = _update(f)
    clone = tmp_path / "clones" / "NewsFilter"
    assert kc.verbs() == SESSION * 2
    assert kc.creates()[1] == [
        "--cwd", str(clone),
        "--agent", "update-architecture", "--model", "opus", "--reasoning-effort", "xhigh",
    ]
    assert kc.prompts()[1] == (
        "Bring producer `newsfilter`'s architecture sources up to date with the commits in "
        f"{base}..HEAD. Commit per the repo's cadence, do not push. End with your two-line "
        "handoff.\n\n"
        "- Producer id: newsfilter\n"
        "- Mode: hand-authored\n"
        "- Sources: `:(glob)**/docs/architecture/**`\n"
        f"- Base commit: {base}\n"
        "- Default branch: main\n"
        "\nThe repo's instructions, verbatim from its `.architecturerc`:\n\n(none)\n"
    )
    pushed = _git(clone, "rev-parse", "HEAD")
    assert (outcome.status, outcome.reviewed, outcome.issues) == (fleet.UPDATED, pushed, ())
    assert outcome.detail == "1 delta applied, 1 commit, validator clean. Skipped: none"
    assert outcome.triage == fleet.Verdict(True, "The app now consumes a queue.")
    assert outcome.update is not None
    assert outcome.update.session_id == "sid-fake-1"
    assert outcome.update.commits == (_git(clone, "log", "-1", "--format=%h %s"),)
    assert outcome.update.commits[0].endswith(" architecture: docs/architecture/a.yaml")
    assert outcome.push == fleet.Push(pushed, (_tracked(JOB, 0, fleet.Build(JOB, 42, "SUCCESS")),))
    assert _state(f) == {
        ID: {"reviewed": pushed, "date": "2026-09-11", "outcome": f"updated: {outcome.detail}"}
    }


def test_an_update_with_nothing_to_apply_advances_reviewed(tmp_path: Path, kc: FakeKc) -> None:
    f, _, head = _stale(tmp_path)
    kc.play(UPDATE, NOTHING)
    outcome = _update(f)
    assert (outcome.status, outcome.reviewed, bool(outcome.issues)) == (fleet.NOTHING, head, False)
    assert outcome.update is not None and outcome.update.commits == ()
    assert _state(f)[ID]["reviewed"] == head


def test_an_unparseable_verdict_runs_the_update_session(tmp_path: Path, kc: FakeKc) -> None:
    f, _, _ = _stale(tmp_path)
    kc.play({"response": "Looks harmless to me."}, NOTHING)
    outcome = _update(f)
    assert kc.verbs() == SESSION * 2
    assert (outcome.status, outcome.triage) == (fleet.NOTHING, UNPARSEABLE)


@pytest.mark.parametrize(
    "turn, detail",
    [
        (
            {"response": "0 deltas applied, 0 commits, stopped: no validator.\nSkipped: none\n"},
            "the update session stopped: no validator",
        ),
        ({"response": "All done!"}, "the update session's final two lines are not its handoff"),
        (
            {"write": {"scratch.txt": "notes\n"}, **NOTHING},
            "the update session left uncommitted changes in {clone}",
        ),
        ({"response": "partial", "exit": 1}, "update session exited 1"),
    ],
    ids=["stopped", "no-handoff", "dirty", "non-zero"],
)
def test_an_update_session_that_does_not_finish_cleanly_is_unresolved(
    tmp_path: Path, kc: FakeKc, turn: dict[str, Any], detail: str
) -> None:
    f, _, head = _stale(tmp_path)
    kc.play(UPDATE, turn)
    outcome = _update(f)
    detail = detail.format(clone=tmp_path / "clones" / "NewsFilter")
    assert (outcome.status, outcome.detail, outcome.reviewed) == (fleet.FAILED, detail, None)
    assert bool(outcome.issues)
    assert _git(tmp_path / "remotes" / f"{REPO}.git", "rev-parse", "main") == head
    assert _state(f) == {ID: {"date": "2026-09-11", "outcome": f"failed: {detail}"}}


def test_a_failed_triage_is_unresolved_keeps_reviewed_and_the_run_moves_on(
    tmp_path: Path,
    kc: FakeKc,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(fleet, "TRIAGE", dataclasses.replace(fleet.TRIAGE, timeout=1))
    first = Remote(tmp_path, REPO)
    base = first.commit({"docs/architecture/a.yaml": _envelope(ID)})
    first.commit({"src/app.py": "app\n"})
    second = Remote(tmp_path, "pvginkel/PaperClock")
    second.commit({"docs/architecture/a.yaml": _envelope("paper-clock")})
    head = second.commit({"src/app.py": "app\n"})
    f = _fleet(
        tmp_path,
        NEWSFILTER,
        PAPER_CLOCK,
        HA_FLEET,
    )
    state = f.spec_repo / fleet.STATE_FILE
    state.parent.mkdir(parents=True)
    state.write_text(yaml.safe_dump({ID: {"reviewed": base, "date": "2026-09-01", "outcome": "x"}}))
    kc.play({"sleep": 30}, SKIP)
    assert fleet.run(["update"], f, NOW) == 1
    assert kc.verbs() == ["create-headless", "send", "end", *SESSION]
    assert _state(f) == {
        ID: {
            "reviewed": base,
            "date": "2026-09-11",
            "outcome": "failed: triage session timed out after 1 s",
        },
        "paper-clock": {
            "reviewed": head,
            "date": "2026-09-11",
            "outcome": "skipped: Only CI housekeeping.",
        },
    }
    assert capsys.readouterr().out.splitlines() == [
        "newsfilter             pvginkel/NewsFilter  failed             "
        "triage session timed out after 1 s",
        "paper-clock            pvginkel/PaperClock  skipped            Only CI housekeeping.",
        "home-automation-fleet  -                    not fleet-managed",
        f"report: {f.spec_repo / fleet.report_file(NOW)}",
        "unresolved: 1",
        "judgment calls: 0",
    ]


MISSING_AGENT = "agent definition(s) missing from the clone: .claude/agents/update-architecture.md"


def test_a_clone_missing_an_agent_stops_the_producer_before_any_session(
    tmp_path: Path, kc: FakeKc
) -> None:
    f, _, _ = _stale(tmp_path)
    (f.kit / "agents/update-architecture.md").unlink()
    assert _update(f) == fleet.Outcome(
        PRODUCER,
        fleet.FAILED,
        MISSING_AGENT,
        issues=(MISSING_AGENT,),
    )
    assert kc.calls() == []


def test_a_current_producer_runs_no_session_and_a_hand_authored_one_reads_no_gaps(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins
) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({"src/app.py": "app\n"})
    head = remote.commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path, NEWSFILTER)
    assert _update(f) == fleet.Outcome(PRODUCER, fleet.CURRENT, reviewed=head)
    assert kc.calls() == [] and jenkins.paths == []
    assert _state(f) == {ID: {"reviewed": head, "date": "2026-09-11", "outcome": "current"}}


def test_update_takes_only_the_named_producers(
    tmp_path: Path, kc: FakeKc, capsys: pytest.CaptureFixture[str]
) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    Remote(tmp_path, "pvginkel/PaperClock").commit(
        {"docs/architecture/a.yaml": _envelope("paper-clock")}
    )
    f = _fleet(
        tmp_path, NEWSFILTER, PAPER_CLOCK
    )
    assert fleet.run(["update", "paper-clock"], f, NOW) == 0
    assert capsys.readouterr().out.splitlines() == [
        "paper-clock  pvginkel/PaperClock  current",
        f"report: {f.spec_repo / fleet.report_file(NOW)}",
        "unresolved: 0",
        "judgment calls: 0",
    ]
    assert list(_state(f)) == ["paper-clock"]


def test_update_rejects_an_unknown_producer_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _fleet(tmp_path, NEWSFILTER)
    with pytest.raises(SystemExit) as exit_:
        fleet.run(["update", "newsfilter", "nope", "design-assistant"], f, NOW)
    assert exit_.value.code == 2
    assert "unknown producer id(s): design-assistant, nope" in capsys.readouterr().err


class Killed(Exception):
    pass


def test_the_state_is_recorded_as_each_producer_finishes(
    tmp_path: Path, kc: FakeKc, monkeypatch: pytest.MonkeyPatch
) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path, NEWSFILTER, PAPER_CLOCK)
    update_producer = fleet.update_producer

    def killed_at_the_second(
        fl: fleet.Fleet, producer: fleet.Producer, review: fleet.Review, jenkins: fleet.Jenkins
    ) -> fleet.Outcome:
        if producer.id == "paper-clock":
            raise Killed
        return update_producer(fl, producer, review, jenkins)

    monkeypatch.setattr(fleet, "update_producer", killed_at_the_second)
    with pytest.raises(Killed):
        fleet.run(["update"], f, NOW)
    assert list(_state(f)) == [ID]


# ---- fleet.py update: the push, the tracked builds, the fix loop ----

JENKINS = "https://jenkins.example.invalid"
TOKEN = "test-token"
APP = "NewsFilter/NewsFilter"
SCM = f"https://github.com/{REPO}.git"

PUSH_TRIGGER = (
    "<com.cloudbees.jenkins.GitHubPushTrigger><spec/></com.cloudbees.jenkins.GitHubPushTrigger>"
)
TIMER_TRIGGER = (
    "<hudson.triggers.TimerTrigger><spec>H 3 * * *</spec></hudson.triggers.TimerTrigger>"
)

JOB_CONFIG = """\
<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <properties>
    <org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty>
      <triggers>
        {trigger}
      </triggers>
    </org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition">
    <scm class="hudson.plugins.git.GitSCM">
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>{url}</url>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
    </scm>
    <scriptPath>Jenkinsfile.architecture</scriptPath>
  </definition>
  <disabled>{disabled}</disabled>
</flow-definition>
"""


FakeJob = tuple[str, list[tuple[int, str | None]], str, bool, tuple[str, ...], tuple[str, ...]]


class FakeJenkins:
    """Canned Jenkins REST responses under a placeholder host, in place of urlopen.

    A job carries its SCM URL, its builds newest first as `(number, result)`
    (`last` alone stands for one build #1 with that result, None for a job
    never built), the trigger in its config, whether it is disabled, the jobs
    its last completed build's console says it started, and the lines its last
    successful build's console adds; the folders are the job names' prefixes,
    at any depth. `no_history` refuses the build listing the tool reads a
    failed build's prior result from.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.paths: list[str] = []
        self.down = False
        self.no_history = False
        monkeypatch.setenv("JENKINS_URL", JENKINS)
        monkeypatch.setenv("JENKINS_TOKEN", TOKEN)
        monkeypatch.delenv("JENKINS_USER", raising=False)
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def job(
        self,
        name: str,
        scm: str = SCM,
        last: str | None = "SUCCESS",
        trigger: str = PUSH_TRIGGER,
        disabled: bool = False,
        builds: list[tuple[int, str | None]] | None = None,
        starts: tuple[str, ...] = (),
        console: tuple[str, ...] = (),
    ) -> None:
        if builds is None:
            builds = [(1, last)] if last is not None else []
        self.jobs[name] = (scm, builds, trigger, disabled, starts, console)

    def _completed(self, name: str) -> tuple[int, str] | None:
        completed = [(n, r) for n, r in self.jobs[name][1] if r is not None]
        return max(completed) if completed else None

    def _successful(self, name: str) -> int | None:
        successful = [n for n, r in self.jobs[name][1] if r == "SUCCESS"]
        return max(successful) if successful else None

    def _listing(self, folder: str) -> list[dict[str, Any]]:
        prefix = f"{folder}/" if folder else ""
        children: dict[str, dict[str, Any]] = {}
        for name in self.jobs:
            if name.startswith(prefix):
                child, _, rest = name[len(prefix) :].partition("/")
                children[child] = {"fullName": prefix + child, **({"jobs": []} if rest else {})}
        return list(children.values())

    def urlopen(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        credentials = base64.b64encode(f"admin:{TOKEN}".encode()).decode()
        assert request.get_header("Authorization") == f"Basic {credentials}"
        if self.down:
            raise urllib.error.URLError("no route to host")
        url = urllib.parse.urlsplit(request.full_url)
        assert f"{url.scheme}://{url.netloc}" == JENKINS
        path = urllib.parse.unquote(url.path)
        tree = urllib.parse.parse_qs(url.query).get("tree", [""])[0]
        self.paths.append(path)
        parts = path.strip("/").split("/")
        console = path.endswith("/consoleText")
        name = "/".join(parts[1:-2:2] if console else parts[1:-1:2])
        body: Any
        if path.endswith("/config.xml") and name in self.jobs:
            scm, _, trigger, disabled, _, _ = self.jobs[name]
            config = JOB_CONFIG.format(url=scm, trigger=trigger, disabled=str(disabled).lower())
            return io.BytesIO(config.encode())
        if console and name in self.jobs:
            number = int(parts[-2])
            last = self._completed(name)
            started = self.jobs[name][4] if last and last[0] == number else ()
            lines = ["Started by an SCM change", *(f"Starting building: {j}" for j in started)]
            if number == self._successful(name):
                lines += self.jobs[name][5]
            return io.BytesIO("\n".join(lines).encode())
        if path.endswith("/api/json") and name in self.jobs:
            if tree == "lastCompletedBuild[number,result]":
                last = self._completed(name)
                built = None if last is None else {"number": last[0], "result": last[1]}
                body = {"lastCompletedBuild": built}
            elif tree == "lastSuccessfulBuild[number]":
                successful = self._successful(name)
                built = None if successful is None else {"number": successful}
                body = {"lastSuccessfulBuild": built}
            else:
                assert tree == f"builds[number,result]{{0,{fleet.SCAN_RANGE}}}"
                if self.no_history:
                    raise urllib.error.HTTPError(
                        request.full_url, 500, "Server Error", email.message.Message(), None
                    )
                builds = [{"number": n, "result": r} for n, r in self.jobs[name][1]]
                body = {"builds": builds}
        elif path.endswith("/api/json") and (not name or self._listing(name)):
            assert tree == "jobs[fullName,jobs[fullName]]"
            body = {"jobs": self._listing(name)}
        else:
            raise urllib.error.HTTPError(
                request.full_url, 404, "Not Found", email.message.Message(), None
            )
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture(autouse=True)
def jenkins(monkeypatch: pytest.MonkeyPatch) -> FakeJenkins:
    return FakeJenkins(monkeypatch)


FAKE_TRACKER = """\
import json, os, sys, time
from pathlib import Path

job, commit = sys.argv[1], sys.argv[sys.argv.index("--hash") + 1]
log = Path(os.environ["FAKE_TRACKER_LOG"])
calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
turns = json.loads(Path(os.environ["FAKE_TRACKER_PLAN"]).read_text())[job]
turn = turns[sum(call["job"] == job for call in calls)]
with log.open("a") as f:
    f.write(json.dumps({"job": job, "hash": commit, "argv": sys.argv[1:]}) + "\\n")
if "hang" in turn:
    time.sleep(turn["hang"])
print(f"[12:00:00] Resolving {job} build for commit {commit}", file=sys.stderr)
if "error" in turn:
    print(f"error: {turn['error']}", file=sys.stderr)
    sys.exit(3)
print("=== Build tracking summary ===")
for name, number, result in turn["builds"]:
    print(f"{name:<24}  #{number:<4}  {result:<8}   1m 2s  {os.environ['JENKINS_URL']}/")
    if result != "SUCCESS":
        path = Path(os.environ["FAKE_TRACKER_LOGS"]) / f"{name.replace('/', '_')}_{number}.log"
        print(f"{'':<24}  {'':<5}  \\u21b3 full log: {path}")
print()
red = sum(result != "SUCCESS" for _, _, result in turn["builds"])
print(f"Result: {red} of {len(turn['builds'])} tracked build(s) did NOT succeed.")
sys.exit(1 if red else 0)
"""


class FakeTracker:
    """A `track_build.py` on PATH that plays one canned result per call per job."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bin_dir = tmp_path / "tracker-bin"
        bin_dir.mkdir()
        tracker = bin_dir / "track_build.py"
        tracker.write_text(f"#!{sys.executable}\n{FAKE_TRACKER}")
        tracker.chmod(0o755)
        self.log = tmp_path / "tracker.jsonl"
        self.logs = tmp_path / "tracker-logs"
        self.plan = tmp_path / "tracker-plan.json"
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_TRACKER_LOG", str(self.log))
        monkeypatch.setenv("FAKE_TRACKER_LOGS", str(self.logs))
        monkeypatch.setenv("FAKE_TRACKER_PLAN", str(self.plan))
        self.play({})

    def play(self, turns: dict[str, list[dict[str, Any]]]) -> None:
        self.plan.write_text(json.dumps(turns))

    def calls(self) -> list[tuple[str, str]]:
        if not self.log.exists():
            return []
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [(call["job"], call["hash"]) for call in calls]

    def argv(self) -> list[list[str]]:
        """Every call's full argument vector, in call order."""
        if not self.log.exists():
            return []
        return [json.loads(line)["argv"] for line in self.log.read_text().splitlines()]


@pytest.fixture(autouse=True)
def tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeTracker:
    return FakeTracker(tmp_path, monkeypatch)


HANDOFF = "1 delta applied, 1 commit, validator clean.\nSkipped: none\n"
HANDED_OFF = fleet.Handoff(1, 1, "validator clean", None, "none")


def _edit(note: str) -> dict[str, str]:
    return {"docs/architecture/a.yaml": _envelope(ID) + f"# {note}\n"}


def _fix(round_: int) -> dict[str, Any]:
    return {"commit": _edit(f"fix {round_}"), "response": HANDOFF}


def _built(number: int, job: str = JOB, result: str = "SUCCESS") -> dict[str, Any]:
    return {"builds": [[job, number, result]]}


def _updated(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, *fixes: dict[str, Any]
) -> fleet.Fleet:
    """A stale producer whose update session commits, and a fix session per `fixes`."""
    remote = Remote(tmp_path, REPO)
    remote.commit({"docs/architecture/a.yaml": _envelope(ID)})
    remote.commit({"src/app.py": "app\n"})
    kc.play(UPDATE, {"commit": _edit("the queue"), "response": HANDOFF}, *fixes)
    return _fleet(tmp_path, NEWSFILTER)


def _deliver(f: fleet.Fleet) -> fleet.Outcome:
    [outcome] = fleet.update(f, fleet.load_registry(f.registry), NOW, fleet.Jenkins.from_env())
    return outcome


def _tracked(job: str, code: int, *builds: fleet.Build) -> fleet.Tracked:
    return fleet.Tracked(job, code, builds, "")


def _pushed(tmp_path: Path) -> str:
    return _git(tmp_path / "remotes" / f"{REPO}.git", "rev-parse", "main")


def test_the_job_index_reads_every_folder_level_once_per_run(jenkins: FakeJenkins) -> None:
    jenkins.job(JOB)
    jenkins.job("Apps/Web/NewsFilter", "https://github.com/pvginkel/newsfilter")
    jenkins.job(
        "AaC/Home Assistant Fleet",
        "https://github.com/pvginkel/Architecture.git",
        trigger=TIMER_TRIGGER,
    )
    jenkins.job("Standalone", "https://github.com/pvginkel/PaperClock.git")
    jenkins.job("Mirrors/Elsewhere", "https://git.example.invalid/pvginkel/NewsFilter.git")
    client = fleet.Jenkins.from_env()
    assert client.jobs_by_repo() == {
        "pvginkel/newsfilter": (JOB, "Apps/Web/NewsFilter"),
        "pvginkel/paperclock": ("Standalone",),
    }
    read = len(jenkins.paths)
    client.jobs_by_repo()
    assert len(jenkins.paths) == read
    assert "/job/Apps/job/Web/api/json" in jenkins.paths
    assert "/job/AaC/job/Home Assistant Fleet/config.xml" in jenkins.paths
    assert fleet.tracked_jobs(JOB, REPO, client) == [JOB, "Apps/Web/NewsFilter"]
    assert fleet.tracked_jobs("AaC/PaperClock", "pvginkel/PaperClock", client) == ["Standalone"]
    assert fleet.tracked_jobs("AaC/Home Assistant Fleet", "pvginkel/Architecture", client) == []


def test_a_builds_prior_result_is_its_jobs_newest_completed_build_below_it(
    jenkins: FakeJenkins,
) -> None:
    jenkins.job(JOB, builds=[(43, None), (42, "FAILURE"), (41, "SUCCESS"), (40, "ABORTED")])
    client = fleet.Jenkins.from_env()
    assert client.result_before(JOB, 44) == "FAILURE"
    assert client.result_before(JOB, 43) == "FAILURE"
    assert client.result_before(JOB, 42) == "SUCCESS"
    assert client.result_before(JOB, 40) is None
    assert client.last_completed(JOB) == (42, "FAILURE")
    jenkins.job(APP, last=None)
    assert client.last_completed(APP) is None


def test_a_builds_downstream_is_read_off_its_console_as_the_tracker_reads_it() -> None:
    console = (
        "Started by an SCM change\n"
        "[Pipeline] build\n"
        "Scheduling project: IaC » HelmCharts\n"
        "Starting building: IaC » HelmCharts #6386\n"
        "Starting building: MyDownloads/MyDownloads #12\n"
        "Finished: SUCCESS\n"
    )
    assert fleet.scheduled_jobs(console) == ["IaC/HelmCharts", "MyDownloads/MyDownloads"]
    assert fleet.scheduled_jobs("Finished: FAILURE\n") == []


def test_the_jenkins_address_defaults_in_the_tool_and_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JENKINS_URL")
    default = fleet.Jenkins.from_env()
    assert (default.base, default.user, default.token) == (
        fleet.JENKINS_URL,
        fleet.JENKINS_USER,
        TOKEN,
    )
    monkeypatch.setenv("JENKINS_URL", f"{JENKINS}/")
    monkeypatch.setenv("JENKINS_USER", "robot")
    overridden = fleet.Jenkins.from_env()
    assert (overridden.base, overridden.user) == (JENKINS, "robot")


def test_the_tracker_summary_names_each_build_and_a_failed_ones_log() -> None:
    stdout = (
        "=== Build tracking summary ===\n"
        "AaC/Home Assistant Fleet  #12   SUCCESS    1m 02s  https://ci.example.invalid/12/\n"
        "AaC/Architecture          #340  FAILURE    3m 10s  https://ci.example.invalid/340/\n"
        "                                ↳ full log: /tmp/track_build/AaC_Architecture_340.log\n"
        "\n"
        "Events:\n"
        "  - AaC/Architecture #339 was superseded by #340\n"
        "\n"
        "Result: 1 of 2 tracked build(s) did NOT succeed.\n"
    )
    assert fleet.parse_track_summary(stdout) == (
        fleet.Build("AaC/Home Assistant Fleet", 12, "SUCCESS"),
        fleet.Build(
            "AaC/Architecture", 340, "FAILURE", "/tmp/track_build/AaC_Architecture_340.log"
        ),
    )
    assert fleet.parse_track_summary("error: authentication failed (401)\n") == ()


def test_an_update_is_pushed_and_each_tracked_job_followed_once_at_the_pushed_commit(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    jenkins.job(APP)
    jenkins.job("AaC/PaperClock", "https://github.com/pvginkel/PaperClock.git")
    tracker.play({JOB: [_built(42)], APP: [_built(7, APP)]})
    before = _pushed(tmp_path)
    outcome = _deliver(f)
    pushed = _pushed(tmp_path)
    assert pushed == _git(tmp_path / "clones" / "NewsFilter", "rev-parse", "HEAD") != before
    assert tracker.calls() == [(JOB, pushed), (APP, pushed)]
    assert outcome.push == fleet.Push(
        pushed,
        (
            _tracked(JOB, 0, fleet.Build(JOB, 42, "SUCCESS")),
            _tracked(APP, 0, fleet.Build(APP, 7, "SUCCESS")),
        ),
    )
    assert not any(path.endswith("/api/json") and "builds[" in path for path in jenkins.paths)
    assert (outcome.status, outcome.reviewed, bool(outcome.issues), outcome.fixes) == (
        fleet.UPDATED,
        pushed,
        False,
        (),
    )
    assert outcome.detail == "1 delta applied, 1 commit, validator clean. Skipped: none"
    assert _state(f)[ID] == {
        "reviewed": pushed,
        "date": "2026-09-11",
        "outcome": f"updated: {outcome.detail}",
    }
    assert kc.verbs() == SESSION * 2


def test_a_job_the_push_does_not_start_is_not_tracked(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    scheduled = "AaC/Home Assistant Fleet"
    retired = "Firmware/NewsFilter"
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    jenkins.job(scheduled, trigger=TIMER_TRIGGER)
    jenkins.job(retired, disabled=True)
    stalls = [{"error": "no build of the commit appeared"}]
    tracker.play({JOB: [_built(42)], scheduled: stalls, retired: stalls})
    outcome = _deliver(f)
    assert tracker.calls() == [(JOB, _pushed(tmp_path))]
    assert "/job/AaC/job/Home Assistant Fleet/config.xml" in jenkins.paths
    assert "/job/AaC/job/Home Assistant Fleet/api/json" not in jenkins.paths
    assert "/job/Firmware/job/NewsFilter/api/json" not in jenkins.paths
    assert (bool(outcome.issues), outcome.detail) == (
        False,
        "1 delta applied, 1 commit, validator clean. Skipped: none",
    )


def test_a_registry_job_the_push_does_not_start_is_unresolved_and_the_rest_tracked(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB, trigger=TIMER_TRIGGER)
    jenkins.job(APP)
    tracker.play({APP: [_built(7, APP)]})
    outcome = _deliver(f)
    pushed = _pushed(tmp_path)
    assert tracker.calls() == [(APP, pushed)]
    assert (outcome.status, outcome.reviewed) == (fleet.UPDATED, pushed)
    assert outcome.issues == (
        f"{JOB} not tracked: a push to {REPO} does not start it "
        "(no GitHub push trigger, or disabled)",
    )
    assert outcome.detail == (
        f"1 delta applied, 1 commit, validator clean. Skipped: none; {outcome.issues[0]}"
    )


def test_a_build_red_before_the_push_is_pre_existing_and_never_resumes_the_session(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB, last="FAILURE")
    jenkins.job(APP, last=None)
    tracker.play({JOB: [_built(42, result="FAILURE")], APP: [_built(7, APP, "FAILURE")]})
    outcome = _deliver(f)
    assert kc.verbs() == SESSION * 2
    assert (outcome.reviewed, bool(outcome.issues), outcome.fixes) == (
        _pushed(tmp_path),
        True,
        (),
    )
    assert outcome.detail == (
        "1 delta applied, 1 commit, validator clean. Skipped: none; "
        "AaC/NewsFilter red, pre-existing: FAILURE before the push; "
        "NewsFilter/NewsFilter red; it had no completed build before the push"
    )


def test_a_tracker_that_cannot_finish_is_operational_and_unresolved(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [{"error": "authentication failed (401)"}]})
    outcome = _deliver(f)
    assert kc.verbs() == SESSION * 2
    assert outcome.push == fleet.Push(
        _pushed(tmp_path), (fleet.Tracked(JOB, 3, (), "error: authentication failed (401)"),)
    )
    assert bool(outcome.issues) and outcome.reviewed == _pushed(tmp_path)
    assert outcome.detail.endswith(
        "; AaC/NewsFilter tracking failed: error: authentication failed (401)"
    )


def test_the_tracker_is_given_an_appear_timeout_that_covers_a_queued_build(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42)]})
    _deliver(f)
    assert tracker.argv() == [
        [JOB, "--hash", _pushed(tmp_path), "--appear-timeout", str(fleet.APPEAR_TIMEOUT)]
    ]


def test_a_tracker_that_never_finishes_is_capped_and_reported_operational(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fleet, "TRACK_TIMEOUT", 0.5)
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [{"hang": 30, "builds": []}]})
    outcome = _deliver(f)
    assert outcome.push == fleet.Push(
        _pushed(tmp_path),
        (fleet.Tracked(JOB, fleet.TIMED_OUT, (), "the tracker did not finish within 0.5s"),),
    )
    assert bool(outcome.issues) and outcome.reviewed == _pushed(tmp_path)
    assert outcome.detail.endswith(
        "; AaC/NewsFilter tracking failed: the tracker did not finish within 0.5s"
    )


def test_a_build_the_change_broke_resumes_the_update_session_and_is_pushed_again(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins, _fix(1))
    jenkins.job(JOB)
    architecture = "https://github.com/pvginkel/Architecture.git"
    jenkins.job("AaC/Architecture", architecture, builds=[(89, "SUCCESS")])
    downstream = {"builds": [[JOB, 42, "SUCCESS"], ["AaC/Architecture", 90, "FAILURE"]]}
    tracker.play({JOB: [downstream, _built(43)]})
    outcome = _deliver(f)
    clone = tmp_path / "clones" / "NewsFilter"
    (_, first), (_, second) = tracker.calls()
    assert second == _pushed(tmp_path) == _git(clone, "rev-parse", "HEAD")
    assert kc.verbs() == SESSION * 3
    assert kc.creates()[2] == [
        "--cwd", str(clone),
        "--resume", "sid-fake-1",
        "--agent", "update-architecture", "--model", "opus", "--reasoning-effort", "xhigh",
    ]
    log = tracker.logs / "AaC_Architecture_90.log"
    assert kc.prompts()[2] == (
        f"Since the push of your commits (up to {first}), Jenkins is red where it was green "
        "before them: `AaC/Architecture`. Assume your commits broke it; fix, commit, do not push. "
        "End with your two-line handoff, covering this round.\n\n"
        "The failed builds, each with its console log:\n\n"
        f"- Job: AaC/Architecture\n  Build: #90 (FAILURE)\n  Log: {log}\n"
    )
    assert outcome.push == fleet.Push(
        first,
        (
            _tracked(
                JOB,
                1,
                fleet.Build(JOB, 42, "SUCCESS"),
                fleet.Build("AaC/Architecture", 90, "FAILURE", str(log), "SUCCESS"),
            ),
        ),
    )
    assert outcome.fixes == (
        fleet.FixRound(
            ("AaC/Architecture",),
            HANDED_OFF,
            (_git(clone, "log", "-1", "--format=%h %s"),),
            None,
            fleet.Push(second, (_tracked(JOB, 0, fleet.Build(JOB, 43, "SUCCESS")),)),
            "sid-fake-2",
        ),
    )
    assert (outcome.status, outcome.reviewed, outcome.issues) == (fleet.UPDATED, second, ())
    assert jenkins.paths.count("/job/AaC/job/Architecture/api/json") == 1


def test_the_fix_loop_stops_after_two_rounds_and_a_job_still_red_is_unresolved(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins, _fix(1), _fix(2), _fix(3))
    jenkins.job(JOB)
    tracker.play({JOB: [_built(n, result="FAILURE") for n in (42, 43, 44)]})
    outcome = _deliver(f)
    pushes = [commit for _, commit in tracker.calls()]
    assert len(pushes) == 3
    assert pushes[-1] == _pushed(tmp_path)
    assert kc.verbs() == SESSION * 4
    assert [c[c.index("--resume") + 1] for c in kc.creates() if "--resume" in c] == [
        "sid-fake-1",
        "sid-fake-2",
    ]
    assert [fix.push.commit for fix in outcome.fixes if fix.push] == pushes[1:]
    assert (outcome.reviewed, bool(outcome.issues)) == (pushes[-1], True)
    assert outcome.detail.endswith("; AaC/NewsFilter still red after 2 fix rounds")
    assert _state(f)[ID]["reviewed"] == pushes[-1]


def test_a_fix_round_that_commits_nothing_ends_the_loop_unresolved(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins, NOTHING)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    outcome = _deliver(f)
    assert len(tracker.calls()) == 1
    assert kc.verbs() == SESSION * 3
    [fix] = outcome.fixes
    assert (fix.jobs, fix.commits, fix.failure, fix.push) == (
        (JOB,),
        (),
        "the update session made no commit",
        None,
    )
    assert outcome.detail.endswith(
        "; fix round 1: the update session made no commit; "
        "AaC/NewsFilter still red after 1 fix round"
    )


def test_an_update_session_whose_id_is_unknown_is_not_resumed(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_KC_STATUS", "refuse")
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    outcome = _deliver(f)
    assert kc.verbs() == SESSION * 2
    assert bool(outcome.issues)
    assert outcome.detail.endswith(
        "; fix round 1: the update session has no id to resume; "
        "AaC/NewsFilter still red after 1 fix round"
    )


STOPPED = "0 deltas applied, 1 commit, stopped: the validator is unreachable.\nSkipped: none\n"


@pytest.mark.parametrize(
    "turn, failure, committed",
    [
        ({"sleep": 30}, "update session timed out after 3 s", False),
        (
            {"commit": _edit("fix 1"), "response": "partial", "exit": 2},
            "update session exited 2",
            True,
        ),
        (
            {"write": {"scratch.txt": "notes\n"}, **_fix(1)},
            "the update session left uncommitted changes in {clone}",
            True,
        ),
        (
            {"commit": _edit("fix 1"), "response": STOPPED},
            "the update session stopped: the validator is unreachable",
            True,
        ),
        (
            {"commit": _edit("fix 1"), "response": "Fixed it!\n"},
            "the update session's final two lines are not its handoff",
            True,
        ),
    ],
    ids=["timeout", "non-zero", "dirty", "stopped", "no-handoff"],
)
def test_a_fix_round_that_does_not_finish_cleanly_stops_short_of_a_push(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    monkeypatch: pytest.MonkeyPatch,
    turn: dict[str, Any],
    failure: str,
    committed: bool,
) -> None:
    monkeypatch.setattr(fleet, "UPDATE", dataclasses.replace(fleet.UPDATE, timeout=3))
    monkeypatch.setattr(fleet, "INTERRUPT_GRACE", 1)
    f = _updated(tmp_path, kc, jenkins, turn)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    outcome = _deliver(f)
    clone = tmp_path / "clones" / "NewsFilter"
    pushed = _pushed(tmp_path)
    failure = failure.format(clone=clone)
    if committed:
        failure += f"; its commits stay unpushed in {clone}"
    assert len(tracker.calls()) == 1
    unfinished = "sleep" in turn or turn.get("exit", 0) != 0
    resumed = ["create-headless", "send", "end"] if unfinished else SESSION
    assert kc.verbs() == SESSION * 2 + resumed
    [fix] = outcome.fixes
    assert (fix.jobs, fix.failure, fix.push) == ((JOB,), failure, None)
    assert bool(fix.commits) is committed
    assert (_git(clone, "rev-parse", "HEAD") != pushed) is committed
    assert outcome.reviewed == pushed
    assert outcome.detail.endswith(
        f"; fix round 1: {failure}; AaC/NewsFilter still red after 1 fix round"
    )


def test_a_fix_round_whose_push_is_rejected_keeps_its_commits_in_the_clone(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins, _fix(1))
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    once = tmp_path / "pushed-once"
    hook = tmp_path / "remotes" / f"{REPO}.git" / "hooks" / "pre-receive"
    hook.write_text(
        f"#!/bin/sh\nif [ -e {once} ]; then echo 'protected branch' >&2; exit 1; fi\n"
        f"touch {once}\n"
    )
    hook.chmod(0o755)
    outcome = _deliver(f)
    clone = tmp_path / "clones" / "NewsFilter"
    pushed = _pushed(tmp_path)
    assert once.exists() and len(tracker.calls()) == 1
    assert kc.verbs() == SESSION * 3
    [fix] = outcome.fixes
    assert fix.failure is not None and fix.failure.startswith("git push failed: ")
    assert fix.failure.endswith(f"; its commits stay unpushed in {clone}")
    assert (fix.push, fix.session_id, len(fix.commits)) == (None, "sid-fake-2", 1)
    assert _git(clone, "rev-parse", "HEAD") != pushed == outcome.reviewed
    assert outcome.detail.endswith(
        f"; fix round 1: {fix.failure}; AaC/NewsFilter still red after 1 fix round"
    )


def test_a_downstream_build_red_before_the_run_is_pre_existing_and_the_run_needs_force(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helm = "IaC/HelmCharts"
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB, starts=(helm,))
    jenkins.job(APP, last="UNSTABLE")
    jenkins.job(helm, "https://github.com/pvginkel/HelmCharts.git", builds=[(99, "FAILURE")])
    chain = {"builds": [[JOB, 42, "SUCCESS"], [helm, 100, "FAILURE"]]}
    tracker.play({JOB: [chain], APP: [_built(7, APP)]})
    head = _pushed(tmp_path)
    assert fleet.run(["update"], f, NOW) == fleet.RED_EXIT == 3
    assert capsys.readouterr().err == (
        "Jenkins is red before the run:\n"
        "  NewsFilter/NewsFilter UNSTABLE\n"
        "  IaC/HelmCharts FAILURE, started by AaC/NewsFilter\n"
        "nothing was done: fix them, or run again with --force\n"
    )
    assert kc.calls() == [] and tracker.calls() == [] and _pushed(tmp_path) == head
    assert not (f.spec_repo / fleet.STATE_FILE).exists()
    assert "/job/AaC/job/NewsFilter/1/consoleText" in jenkins.paths
    jenkins.job(APP)
    assert fleet.run(["update", "--force"], f, NOW) == 1
    err = capsys.readouterr().err
    assert err.startswith(
        "Jenkins is red before the run:\n"
        "  IaC/HelmCharts FAILURE, started by AaC/NewsFilter\n"
        "running anyway (--force): a build red after a push counts against its producer only "
        "where its own job was green before\n"
    )
    assert kc.verbs() == SESSION * 2
    assert tracker.calls() == [(JOB, _pushed(tmp_path)), (APP, _pushed(tmp_path))]
    report = (f.spec_repo / fleet.report_file(NOW)).read_text()
    assert (
        "\nRed before the run, run with `--force`: `IaC/HelmCharts` FAILURE "
        "(started by `AaC/NewsFilter`).\n\n## newsfilter — updated\n"
    ) in report
    assert (
        f"- Builds:\n  - `{JOB}`: red — `{JOB}` #42 SUCCESS, `IaC/HelmCharts` #100 FAILURE "
        f"(FAILURE before the push; log: {tracker.logs / 'IaC_HelmCharts_100.log'})\n"
        f"  - `{APP}`: green — `{APP}` #7 SUCCESS\n"
    ) in report
    assert report.endswith(
        "## Unresolved\n\n"
        "- `newsfilter`: IaC/HelmCharts via AaC/NewsFilter red, pre-existing: FAILURE before "
        "the push\n"
    )


@pytest.mark.parametrize("cause", ["no token", "unreachable"])
def test_jenkins_the_tool_cannot_read_before_the_run_stops_it(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cause: str,
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    head = _pushed(tmp_path)
    if cause == "no token":
        monkeypatch.delenv("JENKINS_TOKEN")
    else:
        jenkins.down = True
    assert fleet.run(["update"], f, NOW) == fleet.RED_EXIT
    listing = f"{JENKINS}/api/json?tree=jobs%5BfullName%2Cjobs%5BfullName%5D%5D"
    reason = (
        "Jenkins: JENKINS_TOKEN is not set"
        if cause == "no token"
        else f"Jenkins: cannot reach {listing}: <urlopen error no route to host>"
    )
    assert capsys.readouterr().err == f"Jenkins could not be read before the run: {reason}\n"
    assert kc.calls() == [] and tracker.calls() == [] and _pushed(tmp_path) == head


def test_a_failed_builds_prior_result_the_tool_cannot_read_is_operational(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    jenkins.no_history = True
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    outcome = _deliver(f)
    log = str(tracker.logs / "AaC_NewsFilter_42.log")
    history = (
        f"{JENKINS}/job/AaC/job/NewsFilter/api/json?tree=builds%5Bnumber%2Cresult%5D%7B0%2C50%7D"
    )
    reason = f"the results before the push could not be read: Jenkins: HTTP 500 for {history}"
    assert kc.verbs() == SESSION * 2
    assert outcome.push == fleet.Push(
        _pushed(tmp_path),
        (fleet.Tracked(JOB, 1, (fleet.Build(JOB, 42, "FAILURE", log),), reason),),
    )
    assert outcome.issues == (f"AaC/NewsFilter tracking failed: {reason}",)


@pytest.mark.parametrize("cause", ["no token", "unreachable"])
def test_jenkins_the_tool_cannot_read_leaves_the_commits_unpushed(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    monkeypatch: pytest.MonkeyPatch,
    cause: str,
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    head = _pushed(tmp_path)
    if cause == "no token":
        monkeypatch.delenv("JENKINS_TOKEN")
    else:
        jenkins.down = True
    outcome = _deliver(f)
    clone = tmp_path / "clones" / "NewsFilter"
    assert _pushed(tmp_path) == head
    assert tracker.calls() == []
    assert (outcome.status, outcome.reviewed, bool(outcome.issues)) == (fleet.FAILED, None, True)
    assert outcome.detail.endswith(f"; the commits stay unpushed in {clone}")
    assert outcome.detail.startswith(
        "Jenkins: JENKINS_TOKEN is not set"
        if cause == "no token"
        else f"Jenkins: cannot reach {JENKINS}/api/json"
    )
    assert outcome.update is not None and outcome.update.commits


def test_a_rejected_push_is_unresolved_and_tracks_nothing(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    head = _pushed(tmp_path)
    hook = tmp_path / "remotes" / f"{REPO}.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(0o755)
    outcome = _deliver(f)
    assert _pushed(tmp_path) == head
    assert tracker.calls() == []
    assert (outcome.status, outcome.reviewed, bool(outcome.issues)) == (fleet.FAILED, None, True)
    assert outcome.detail.startswith("git push failed: ")


# ---- fleet.py update: the gaps a generated producer's build reports ----

GENERATED = {"generated": True, "sources": ["*/architecture.yaml"]}
GAP_A = "app: image 'queue' (in app/queue)"
GAP_B = "app: image 'cron' (in app/cron)"


def _generated(tmp_path: Path, repo: str, *later: dict[str, str]) -> tuple[str, str]:
    """A generated producer's repo whose sources changed first, then a commit per `later`: its
    watermark and its head."""
    remote = Remote(tmp_path, repo)
    watermark = remote.commit(
        {".architecturerc": yaml.safe_dump(GENERATED), "app/architecture.yaml": "images: {}\n"}
    )
    head = watermark
    for files in later:
        head = remote.commit(files)
    return watermark, head


def test_the_gaps_are_the_gap_lines_of_the_last_successful_build_each_once(
    jenkins: FakeJenkins,
) -> None:
    console = (
        f"gap: {GAP_A}",
        "  gap: indented, not a gap line",
        f"gap: {GAP_B}",
        f"gap: {GAP_A}",
        "no gap: here",
    )
    jenkins.job(JOB, builds=[(43, "FAILURE"), (42, "SUCCESS")], console=console)
    jenkins.job(APP, builds=[(1, "FAILURE")], console=(f"gap: {GAP_A}",))
    client = fleet.Jenkins.from_env()
    assert client.gaps(JOB) == (GAP_A, GAP_B)
    assert "/job/AaC/job/NewsFilter/42/consoleText" in jenkins.paths
    assert client.gaps(APP) == ()


def test_a_gap_no_run_has_judged_runs_the_update_session_without_triage(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    _, head = _generated(tmp_path, REPO)
    f = _fleet(tmp_path, NEWSFILTER)
    jenkins.job(JOB, console=(f"gap: {GAP_A}", f"gap: {GAP_B}"))
    handoff = "1 delta applied, 1 commit, validation by the AaC build.\nSkipped: none\n"
    mapped = {"app/architecture.yaml": "images:\n  queue: app:queue\n"}
    kc.play({"commit": mapped, "response": handoff})
    tracker.play({JOB: [_built(2)]})
    assert fleet.run(["update"], f, NOW) == 0
    assert [create[3] for create in kc.creates()] == ["update-architecture"]
    assert kc.prompts() == [
        "Bring producer `newsfilter`'s architecture sources up to date with the gaps its AaC "
        "build reports; no commit is past the base. Commit per the repo's cadence, do not push. "
        "End with your two-line handoff.\n\n"
        "- Producer id: newsfilter\n"
        "- Mode: generated\n"
        "- Sources: `*/architecture.yaml`\n"
        f"- Base commit: {head}\n"
        "- Default branch: main\n"
        f"- Gaps the last successful `{JOB}` build reports, in scope whatever the range:\n"
        f"  - {GAP_A}\n"
        f"  - {GAP_B}\n"
        "\nThe repo's instructions, verbatim from its `.architecturerc`:\n\n(none)\n"
    ]
    pushed = _pushed(tmp_path)
    assert pushed != head
    assert _state(f) == {
        ID: {
            "reviewed": pushed,
            "gaps": [GAP_A, GAP_B],
            "date": "2026-09-11",
            "outcome": "updated: 1 delta applied, 1 commit, validation by the AaC build. "
            "Skipped: none",
        }
    }
    report = (f.spec_repo / fleet.report_file(NOW)).read_text()
    assert (
        "## newsfilter — updated\n\n"
        f"- Repo: `{REPO}`\n"
        "- Triage: not run — the build reports a gap no run has judged\n"
        f"- Gaps the last successful `{JOB}` build reports:\n"
        f"  - {GAP_A}\n"
        f"  - {GAP_B}\n"
        "- Handoff: 1 delta applied, 1 commit, validation by the AaC build.\n"
    ) in report


@pytest.mark.parametrize("committed", [False, True], ids=["no-commit", "a-commit"])
def test_gaps_a_run_has_judged_need_no_session_of_their_own_and_are_kept_while_reported(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, committed: bool
) -> None:
    later = [{"src/app.py": "app\n"}] if committed else []
    watermark, head = _generated(tmp_path, REPO, *later)
    f = _fleet(tmp_path, NEWSFILTER)
    state = f.spec_repo / fleet.STATE_FILE
    state.parent.mkdir(parents=True)
    entry = {"reviewed": watermark, "gaps": [GAP_A, GAP_B], "date": "2026-09-01", "outcome": "x"}
    state.write_text(yaml.safe_dump({ID: entry}))
    jenkins.job(JOB, console=(f"gap: {GAP_A}",))
    kc.play(SKIP)
    outcome = _update(f)
    assert (outcome.status, outcome.reviewed, outcome.gaps) == (
        fleet.SKIPPED if committed else fleet.CURRENT,
        head,
        (GAP_A,),
    )
    assert [create[3] for create in kc.creates()] == (["triage-architecture"] if committed else [])
    assert _state(f)[ID]["gaps"] == [GAP_A]


def test_scan_counts_a_generated_producers_new_gaps(
    tmp_path: Path, jenkins: FakeJenkins, capsys: pytest.CaptureFixture[str]
) -> None:
    base, _ = _generated(tmp_path, REPO, {"src/app.py": "app\n"})
    _generated(tmp_path, "pvginkel/PaperClock")
    f = _fleet(tmp_path, NEWSFILTER, PAPER_CLOCK)
    jenkins.job(JOB, console=(f"gap: {GAP_A}",))
    jenkins.job(
        "AaC/PaperClock",
        "https://github.com/pvginkel/PaperClock.git",
        console=(f"gap: {GAP_A}", f"gap: {GAP_B}"),
    )
    assert fleet.run(["scan"], f, NOW) == 0
    assert capsys.readouterr().out.splitlines() == [
        "newsfilter   pvginkel/NewsFilter  stale              "
        f"1 commit since {base[:12]}: 1 file changed, 1 insertion(+); 1 new gap",
        "paper-clock  pvginkel/PaperClock  stale              2 new gaps",
    ]


def test_a_generated_producer_whose_gaps_jenkins_cannot_serve_fails(
    tmp_path: Path, kc: FakeKc
) -> None:
    _generated(tmp_path, REPO)
    reason = (
        f"Jenkins: HTTP 404 for {JENKINS}/job/AaC/job/NewsFilter/api/json"
        "?tree=lastSuccessfulBuild%5Bnumber%5D"
    )
    assert _update(_fleet(tmp_path, NEWSFILTER)) == fleet.Outcome(
        PRODUCER, fleet.FAILED, reason, issues=(reason,)
    )
    assert kc.calls() == []


# ---- fleet.py update: the report, the state and the specs repo ----

GOLDEN = Path(__file__).resolve().parent / "golden"


def _canned() -> list[fleet.Outcome]:
    """One of every outcome a run reaches, as `update` builds them, with stable shas."""
    app = "NewsFilter/NewsFilter"
    clone = fleet.Clone(Path("/tmp/architecture-update/repos/NewsFilter"), "main", "b" * 40)
    handoff = fleet.Handoff(2, 1, "validator clean", None, "the queue's retry topology")
    session = fleet.UpdateResult(clone, "sid-1", handoff, ("1111111 architecture: the queue",))
    broke = _tracked(
        JOB,
        1,
        fleet.Build(JOB, 42, "SUCCESS"),
        fleet.Build(
            "AaC/Architecture", 90, "FAILURE", "/tmp/jenkins/AaC_Architecture_90.log", "SUCCESS"
        ),
    )
    never_built = _tracked(
        app, 1, fleet.Build(app, 7, "FAILURE", "/tmp/jenkins/NewsFilter_7.log")
    )
    fixed = fleet.FixRound(
        ("AaC/Architecture",),
        fleet.Handoff(1, 1, "validator clean", None, "none"),
        ("2222222 architecture: the queue's retry limit",),
        None,
        fleet.Push("d" * 40, (_tracked(JOB, 0, fleet.Build(JOB, 43, "SUCCESS")), never_built)),
        "sid-1",
    )
    issue = "NewsFilter/NewsFilter red; it had no completed build before the push"
    refused = "unpushed commits in /tmp/architecture-update/repos/PaperClock: push or discard"
    nothing = fleet.Handoff(0, 0, "validation by the AaC build", None, "none")
    return [
        fleet.Outcome(
            fleet.Producer(ID, REPO, JOB),
            fleet.UPDATED,
            f"{handoff.text}; {issue}",
            reviewed="d" * 40,
            issues=(issue,),
            triage=fleet.Verdict(True, "The app now consumes a queue."),
            update=session,
            push=fleet.Push("c" * 40, (broke, never_built)),
            fixes=(fixed,),
        ),
        fleet.Outcome(
            fleet.Producer("paper-clock", "pvginkel/PaperClock", "AaC/PaperClock"),
            fleet.FAILED,
            refused,
            issues=(refused,),
        ),
        fleet.Outcome(
            fleet.Producer("dhcp-app", "pvginkel/DHCPApp", "AaC/DHCPApp"),
            fleet.NOTHING,
            nothing.text,
            reviewed="e" * 40,
            triage=fleet.Verdict(True, "The backend gained a lease exporter."),
            update=fleet.UpdateResult(clone, "sid-2", nothing, ()),
        ),
        fleet.Outcome(
            fleet.Producer("helm-charts", "pvginkel/HelmCharts", "AaC/HelmCharts"),
            fleet.NOTHING,
            "0 deltas applied, 0 commits, validation by the AaC build. "
            "Skipped: kube-coder-tunnel-reclaim (a generator change)",
            reviewed="9" * 40,
            gaps=(
                "kubecoder: image 'kube-coder-tunnel-reclaim' "
                "(in kubecoder-controller/tunnel-reclaim)",
            ),
            update=fleet.UpdateResult(
                clone,
                "sid-3",
                fleet.Handoff(
                    0,
                    0,
                    "validation by the AaC build",
                    None,
                    "kube-coder-tunnel-reclaim (a generator change)",
                ),
                (),
            ),
        ),
        fleet.Outcome(
            fleet.Producer("somfy-remote", "pvginkel/SomfyRemote", "AaC/SomfyRemote"),
            fleet.SKIPPED,
            "Only CI housekeeping.",
            reviewed="f" * 40,
            triage=fleet.Verdict(False, "Only CI housekeeping."),
        ),
        fleet.Outcome(
            fleet.Producer("kitchen-display", "pvginkel/KitchenDisplay", "AaC/KitchenDisplay"),
            fleet.CURRENT,
            reviewed="a" * 40,
        ),
        fleet.Outcome(
            fleet.Producer("home-automation-fleet", None, "AaC/Home Assistant Fleet"),
            fleet.UNMANAGED,
        ),
    ]


def test_the_report_and_the_state_read_as_their_goldens(tmp_path: Path) -> None:
    f = _fleet(tmp_path)
    outcomes = _canned()
    for outcome in outcomes:
        if outcome.producer.repo is not None:
            fleet.record_state(f.spec_repo, outcome, NOW.date().isoformat())
    report = fleet.write_report(f, outcomes, NOW, [])
    assert report == f.spec_repo / "architecture-updates" / "2026-09-11T1430.md"
    assert report.read_text() == (GOLDEN / "report.md").read_text()
    assert (f.spec_repo / fleet.STATE_FILE).read_text() == (GOLDEN / "state.yaml").read_text()


def test_a_run_commits_and_pushes_the_report_and_the_state_and_nothing_else(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42)]})
    staged = f.spec_repo / "slices" / "003" / "plan.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("the dev pipeline's own work\n")
    _git(f.spec_repo, "add", "slices")
    assert fleet.run(["update"], f, NOW) == 0
    assert _git(f.spec_repo, "show", "--name-only", "--format=%s", "HEAD").splitlines() == [
        "Architecture update 2026-09-11T1430",
        "",
        str(fleet.report_file(NOW)),
        str(fleet.STATE_FILE),
    ]
    assert _git(f.spec_repo, "rev-parse", "HEAD") == _git(
        tmp_path / "specs.git", "rev-parse", "main"
    )
    assert _git(f.spec_repo, "status", "--porcelain") == "A  slices/003/plan.md"
    report = (f.spec_repo / fleet.report_file(NOW)).read_text()
    assert "## newsfilter — updated" in report
    assert f"- Builds:\n  - `{JOB}`: green — `{JOB}` #42 SUCCESS\n" in report
    assert report.endswith("## Unresolved\n\nNothing.\n")


def test_the_update_sessions_judgment_calls_are_reported_apart_and_do_not_fail_the_run(
    tmp_path: Path,
    kc: FakeKc,
    jenkins: FakeJenkins,
    tracker: FakeTracker,
    capsys: pytest.CaptureFixture[str],
) -> None:
    f = _updated(tmp_path, kc, jenkins, _fix(1))
    judged = "2 deltas applied, 1 commit, validator clean.\nSkipped: the queue's retry topology\n"
    kc.play(
        UPDATE,
        {"commit": _edit("the queue"), "response": judged},
        {"commit": _edit("fix 1"), "response": judged.replace("retry topology", "dead letters")},
    )
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE"), _built(43)]})
    assert fleet.run(["update"], f, NOW) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == ["unresolved: 0", "judgment calls: 2"]
    assert _state(f)[ID]["outcome"] == (
        "updated: 2 deltas applied, 1 commit, validator clean. "
        "Skipped: the queue's retry topology"
    )
    report = (f.spec_repo / fleet.report_file(NOW)).read_text()
    assert "\n1 producer: 1 updated. Nothing unresolved, 2 judgment calls.\n" in report
    assert report.endswith(
        "## Judgment calls\n\n"
        "- `newsfilter`: the queue's retry topology\n"
        "- `newsfilter`: the queue's dead letters\n\n"
        "## Unresolved\n\nNothing.\n"
    )


def test_a_specs_repo_the_run_cannot_push_leaves_the_report_committed(
    tmp_path: Path, kc: FakeKc, capsys: pytest.CaptureFixture[str]
) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path, NEWSFILTER)
    hook = tmp_path / "specs.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(0o755)
    assert fleet.run(["update"], f, NOW) == fleet.UNPUBLISHED_EXIT == 4
    out, err = capsys.readouterr()
    assert out.splitlines()[-2:] == ["unresolved: 0", "judgment calls: 0"]
    assert "publishing the report failed: git push failed: " in err
    assert _git(f.spec_repo, "log", "-1", "--format=%s") == "Architecture update 2026-09-11T1430"
    assert (f.spec_repo / fleet.report_file(NOW)).exists()


def test_a_run_over_a_producer_without_a_repo_commits_the_report_alone(
    tmp_path: Path, kc: FakeKc
) -> None:
    f = _fleet(tmp_path, HA_FLEET)
    assert fleet.run(["update"], f, NOW) == 0
    assert not (f.spec_repo / fleet.STATE_FILE).exists()
    assert _git(f.spec_repo, "show", "--name-only", "--format=%s", "HEAD").splitlines() == [
        "Architecture update 2026-09-11T1430",
        "",
        str(fleet.report_file(NOW)),
    ]
