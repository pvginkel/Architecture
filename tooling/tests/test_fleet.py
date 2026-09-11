"""Tests for the architecture-update tool and the registry fields it reads.

The registry cases drive collect.py as a subprocess against a registry under
tmp_path: its startup check is what rejects a malformed `repo:`.

The fleet cases build each producer repo as a bare git repo under tmp_path,
served over file:// in place of GitHub; the clone area, the specs repo and the
kit are under tmp_path too.
"""

from __future__ import annotations

import ast
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import fleet

TOOLING = Path(__file__).resolve().parent.parent
COLLECT = TOOLING / "collect.py"
REGISTRY = TOOLING.parent / "pipeline-producers.yaml"

ID = "newsfilter"
REPO = "pvginkel/NewsFilter"

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
    proc = _collect(REGISTRY, tmp_path)
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
        spec_repo=tmp_path / "specs",
        remote_base=f"file://{tmp_path / 'remotes'}",
    )


def _scan(f: fleet.Fleet, reviewed: str | None = None) -> fleet.Scan:
    return fleet.scan_producer(f, fleet.Producer(ID, REPO), REPO, reviewed)


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


def test_architecturerc_sets_mode_sources_and_instructions(tmp_path: Path) -> None:
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
    result = _scan(_fleet(tmp_path))
    assert result.config == fleet.RepoConfig(
        generated=True, sources=("*/architecture.yaml",), instructions="Edit the annotations.\n"
    )
    assert (result.watermark, result.commits) == (watermark, 1)


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
    f = _fleet(tmp_path, {"id": ID, "repo": REPO})
    if reviewed_at is not None:
        state = f.spec_repo / "architecture-updates" / "state.yaml"
        state.parent.mkdir(parents=True)
        entry = {"reviewed": shas[reviewed_at], "date": "2026-09-11", "outcome": "skipped"}
        state.write_text(yaml.safe_dump({ID: entry}))
    [row] = fleet.scan(f)
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
    assert fleet.load_reviewed(tmp_path) == {}


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
        {"id": ID, "repo": REPO},
        {"id": "paper-clock", "repo": "pvginkel/PaperClock"},
        {"id": "home-automation-fleet"},
        {"id": "ginbov-nl", "repo": "pvginkel/Ginbov"},
    )
    assert fleet.run(["scan"], f) == 1
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
    assert fleet.run(["scan"], _fleet(tmp_path, {"id": "home-automation-fleet"})) == 0


def test_stage_takes_an_unregistered_repo_as_owner_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = Remote(tmp_path, "pvginkel/NewRepo").commit({"README.md": "readme\n"})
    assert fleet.run(["stage", "pvginkel/NewRepo"], _fleet(tmp_path)) == 0
    clone = tmp_path / "clones" / "NewRepo"
    assert (clone / ".claude" / "agents" / "triage-architecture.md").is_file()
    assert capsys.readouterr().out == f"staged {clone} at main {head[:12]}\n"


def test_stage_resolves_a_registered_repos_bare_name(tmp_path: Path) -> None:
    Remote(tmp_path, REPO).commit({"README.md": "readme\n"})
    assert fleet.run(["stage", "NewsFilter"], _fleet(tmp_path, {"id": ID, "repo": REPO})) == 0
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
    assert fleet.run(["stage", name], _fleet(tmp_path)) == 1
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
