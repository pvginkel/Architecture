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
NOW = datetime(2026, 9, 11, 14, 30)

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
    assert fleet.run(["scan"], _fleet(tmp_path, {"id": "home-automation-fleet"}), NOW) == 0


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
    f = _fleet(tmp_path, {"id": ID, "repo": REPO})
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
    try:
        time.sleep(turn.get("sleep", 0))
    except KeyboardInterrupt:
        record(interrupted=True)
        sys.exit(130)
    Path(args[args.index("--response-file") + 1]).write_text(turn.get("response", ""))
    sys.exit(turn.get("exit", 0))
elif verb == "status":
    record()
    if os.environ.get("FAKE_KC_NO_STATUS"):
        sys.exit(1)
    print(json.dumps({"sessionId": "sid-" + args[2], "state": "idle"}))
else:
    record()
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
PRODUCER = fleet.Producer(ID, REPO)


def _stale(tmp_path: Path, rc: dict[str, Any] | None = None) -> tuple[fleet.Fleet, str, str]:
    remote = Remote(tmp_path, REPO)
    files = {"docs/architecture/a.yaml": _envelope(ID)}
    if rc is not None:
        files[".architecturerc"] = yaml.safe_dump(rc)
    base = remote.commit(files)
    head = remote.commit({"src/app.py": "app\n"})
    return _fleet(tmp_path, {"id": ID, "repo": REPO}), base, head


def _state(f: fleet.Fleet) -> dict[str, Any]:
    state: dict[str, Any] = yaml.safe_load((f.spec_repo / fleet.STATE_FILE).read_text())
    return state


def _update(f: fleet.Fleet) -> fleet.Outcome:
    [outcome] = fleet.update(f, [PRODUCER], NOW)
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
    assert capsys.readouterr().out == (
        "newsfilter  pvginkel/NewsFilter  skipped            Only CI housekeeping.\n"
    )


def test_the_triage_prompt_carries_the_brief_and_the_instructions_verbatim(
    tmp_path: Path, kc: FakeKc
) -> None:
    instructions = "Annotations live in values.yaml.\n  Keep their indent.\n"
    rc = {"generated": True, "sources": ["*/architecture.yaml"], "instructions": instructions}
    remote = Remote(tmp_path, REPO)
    base = remote.commit(
        {".architecturerc": yaml.safe_dump(rc), "app/architecture.yaml": "images: {}\n"}
    )
    remote.commit({"src/app.py": "app\n"})
    kc.play(SKIP)
    _update(_fleet(tmp_path, {"id": ID, "repo": REPO}))
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
    tmp_path: Path, kc: FakeKc
) -> None:
    f, base, _ = _stale(tmp_path)
    handoff = "1 delta applied, 1 commit, validator clean.\nSkipped: none\n"
    edit = {"docs/architecture/a.yaml": _envelope(ID) + "# the queue\n"}
    kc.play(UPDATE, {"commit": edit, "response": handoff})
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
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (fleet.UPDATED, pushed, False)
    assert outcome.detail == "1 delta applied, 1 commit, validator clean. Skipped: none"
    assert outcome.triage == fleet.Verdict(True, "The app now consumes a queue.")
    assert outcome.update is not None
    assert outcome.update.session_id == "sid-fake-1"
    assert outcome.update.commits == (_git(clone, "log", "-1", "--format=%h %s"),)
    assert outcome.update.commits[0].endswith(" architecture: docs/architecture/a.yaml")
    assert outcome.push == fleet.Push(pushed, ())
    assert _state(f) == {
        ID: {"reviewed": pushed, "date": "2026-09-11", "outcome": f"updated: {outcome.detail}"}
    }


def test_an_update_with_nothing_to_apply_advances_reviewed(tmp_path: Path, kc: FakeKc) -> None:
    f, _, head = _stale(tmp_path)
    kc.play(UPDATE, NOTHING)
    outcome = _update(f)
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (fleet.NOTHING, head, False)
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
    assert outcome.unresolved
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
        {"id": ID, "repo": REPO},
        {"id": "paper-clock", "repo": "pvginkel/PaperClock"},
        {"id": "home-automation-fleet"},
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
    ]


def test_a_clone_missing_an_agent_stops_the_producer_before_any_session(
    tmp_path: Path, kc: FakeKc
) -> None:
    f, _, _ = _stale(tmp_path)
    (f.kit / "agents/update-architecture.md").unlink()
    assert _update(f) == fleet.Outcome(
        PRODUCER,
        fleet.FAILED,
        "agent definition(s) missing from the clone: .claude/agents/update-architecture.md",
        unresolved=True,
    )
    assert kc.calls() == []


def test_a_current_producer_runs_no_session(tmp_path: Path, kc: FakeKc) -> None:
    remote = Remote(tmp_path, REPO)
    remote.commit({"src/app.py": "app\n"})
    head = remote.commit({"docs/architecture/a.yaml": _envelope(ID)})
    f = _fleet(tmp_path, {"id": ID, "repo": REPO})
    assert _update(f) == fleet.Outcome(PRODUCER, fleet.CURRENT, reviewed=head)
    assert kc.calls() == []
    assert _state(f) == {ID: {"reviewed": head, "date": "2026-09-11", "outcome": "current"}}


def test_update_takes_only_the_named_producers(
    tmp_path: Path, kc: FakeKc, capsys: pytest.CaptureFixture[str]
) -> None:
    Remote(tmp_path, REPO).commit({"docs/architecture/a.yaml": _envelope(ID)})
    Remote(tmp_path, "pvginkel/PaperClock").commit(
        {"docs/architecture/a.yaml": _envelope("paper-clock")}
    )
    f = _fleet(
        tmp_path, {"id": ID, "repo": REPO}, {"id": "paper-clock", "repo": "pvginkel/PaperClock"}
    )
    assert fleet.run(["update", "paper-clock"], f, NOW) == 0
    assert capsys.readouterr().out == "paper-clock  pvginkel/PaperClock  current\n"
    assert list(_state(f)) == ["paper-clock"]


def test_update_rejects_an_unknown_producer_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = _fleet(tmp_path, {"id": ID, "repo": REPO})
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
    f = _fleet(tmp_path, {"id": ID, "repo": REPO}, {"id": "paper-clock", "repo": "x/PaperClock"})
    update_producer = fleet.update_producer

    def killed_at_the_second(
        fl: fleet.Fleet, producer: fleet.Producer, reviewed: str | None, jenkins: fleet.Jenkins
    ) -> fleet.Outcome:
        if producer.id == "paper-clock":
            raise Killed
        return update_producer(fl, producer, reviewed, jenkins)

    monkeypatch.setattr(fleet, "update_producer", killed_at_the_second)
    with pytest.raises(Killed):
        fleet.run(["update"], f, NOW)
    assert list(_state(f)) == [ID]


# ---- fleet.py update: the push, the tracked builds, the fix loop ----

JENKINS = "https://jenkins.example.invalid"
TOKEN = "test-token"
JOB = "AaC/NewsFilter"
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
</flow-definition>
"""


class FakeJenkins:
    """Canned Jenkins REST responses under a placeholder host, in place of urlopen.

    A job carries its SCM URL, its last completed result (None: never built)
    and the trigger in its config; the folders are the job names' prefixes, at
    any depth.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.jobs: dict[str, tuple[str, str | None, str]] = {}
        self.paths: list[str] = []
        self.remote: Path | None = None
        self.remote_at_read: list[str] = []
        self.down = False
        monkeypatch.setenv("JENKINS_URL", JENKINS)
        monkeypatch.setenv("JENKINS_TOKEN", TOKEN)
        monkeypatch.delenv("JENKINS_USER", raising=False)
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def job(
        self, name: str, scm: str = SCM, last: str | None = "SUCCESS", trigger: str = PUSH_TRIGGER
    ) -> None:
        self.jobs[name] = (scm, last, trigger)

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
        name = "/".join(parts[1:-1:2])
        body: Any
        if path.endswith("/config.xml") and name in self.jobs:
            scm, _, trigger = self.jobs[name]
            return io.BytesIO(JOB_CONFIG.format(url=scm, trigger=trigger).encode())
        if path.endswith("/api/json") and name in self.jobs:
            assert tree == "lastCompletedBuild[result]"
            if self.remote is not None:
                self.remote_at_read.append(_git(self.remote, "rev-parse", "main"))
            last = self.jobs[name][1]
            body = {"lastCompletedBuild": None if last is None else {"result": last}}
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
import json, os, sys
from pathlib import Path

job, commit = sys.argv[1], sys.argv[sys.argv.index("--hash") + 1]
log = Path(os.environ["FAKE_TRACKER_LOG"])
calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
turns = json.loads(Path(os.environ["FAKE_TRACKER_PLAN"]).read_text())[job]
turn = turns[sum(call["job"] == job for call in calls)]
with log.open("a") as f:
    f.write(json.dumps({"job": job, "hash": commit}) + "\\n")
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
    jenkins.remote = remote.bare
    kc.play(UPDATE, {"commit": _edit("the queue"), "response": HANDOFF}, *fixes)
    return _fleet(tmp_path, {"id": ID, "repo": REPO, "jenkinsJob": JOB})


def _deliver(f: fleet.Fleet) -> fleet.Outcome:
    [outcome] = fleet.update(f, fleet.load_registry(f.registry), NOW)
    return outcome


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
    assert fleet.tracked_jobs(None, "pvginkel/PaperClock", client) == ["Standalone"]
    assert fleet.tracked_jobs("AaC/Home Assistant Fleet", "pvginkel/Architecture", client) == []


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
    assert jenkins.remote_at_read == [before, before]
    assert tracker.calls() == [(JOB, pushed), (APP, pushed)]
    assert outcome.push == fleet.Push(
        pushed,
        (
            fleet.Tracked(JOB, "SUCCESS", 0, (fleet.Build(JOB, 42, "SUCCESS"),), ""),
            fleet.Tracked(APP, "SUCCESS", 0, (fleet.Build(APP, 7, "SUCCESS"),), ""),
        ),
    )
    assert (outcome.status, outcome.reviewed, outcome.unresolved, outcome.fixes) == (
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
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    jenkins.job(scheduled, trigger=TIMER_TRIGGER)
    tracker.play({JOB: [_built(42)], scheduled: [{"error": "no build of the commit appeared"}]})
    outcome = _deliver(f)
    assert tracker.calls() == [(JOB, _pushed(tmp_path))]
    assert "/job/AaC/job/Home Assistant Fleet/config.xml" in jenkins.paths
    assert "/job/AaC/job/Home Assistant Fleet/api/json" not in jenkins.paths
    assert (outcome.unresolved, outcome.detail) == (
        False,
        "1 delta applied, 1 commit, validator clean. Skipped: none",
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
    assert (outcome.reviewed, outcome.unresolved, outcome.fixes) == (
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
        _pushed(tmp_path),
        (fleet.Tracked(JOB, "SUCCESS", 3, (), "error: authentication failed (401)"),),
    )
    assert outcome.unresolved and outcome.reviewed == _pushed(tmp_path)
    assert outcome.detail.endswith(
        "; AaC/NewsFilter tracking failed: error: authentication failed (401)"
    )


def test_a_build_the_change_broke_resumes_the_update_session_and_is_pushed_again(
    tmp_path: Path, kc: FakeKc, jenkins: FakeJenkins, tracker: FakeTracker
) -> None:
    f = _updated(tmp_path, kc, jenkins, _fix(1))
    jenkins.job(JOB)
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
        "before them: `AaC/NewsFilter`. Assume your commits broke it; fix, commit, do not push. "
        "End with your two-line handoff, covering this round.\n\n"
        "The failed builds, each with its console log:\n\n"
        f"- Job: AaC/Architecture\n  Build: #90 (FAILURE)\n  Log: {log}\n"
    )
    assert outcome.push == fleet.Push(
        first,
        (
            fleet.Tracked(
                JOB,
                "SUCCESS",
                1,
                (
                    fleet.Build(JOB, 42, "SUCCESS"),
                    fleet.Build("AaC/Architecture", 90, "FAILURE", str(log)),
                ),
                "",
            ),
        ),
    )
    assert outcome.fixes == (
        fleet.FixRound(
            (JOB,),
            HANDED_OFF,
            (_git(clone, "log", "-1", "--format=%h %s"),),
            None,
            fleet.Push(
                second, (fleet.Tracked(JOB, "SUCCESS", 0, (fleet.Build(JOB, 43, "SUCCESS"),), ""),)
            ),
            "sid-fake-2",
        ),
    )
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (
        fleet.UPDATED,
        second,
        False,
    )


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
    assert (outcome.reviewed, outcome.unresolved) == (pushes[-1], True)
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
    monkeypatch.setenv("FAKE_KC_NO_STATUS", "1")
    f = _updated(tmp_path, kc, jenkins)
    jenkins.job(JOB)
    tracker.play({JOB: [_built(42, result="FAILURE")]})
    outcome = _deliver(f)
    assert kc.verbs() == SESSION * 2
    assert outcome.unresolved
    assert outcome.detail.endswith(
        "; fix round 1: the update session has no id to resume; "
        "AaC/NewsFilter still red after 1 fix round"
    )


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
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (fleet.FAILED, None, True)
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
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (fleet.FAILED, None, True)
    assert outcome.detail.startswith("git push failed: ")
