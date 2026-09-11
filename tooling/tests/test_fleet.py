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
import dataclasses
import json
import os
import stat
import subprocess
import sys
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
    assert (outcome.status, outcome.reviewed, outcome.unresolved) == (fleet.UPDATED, None, False)
    assert outcome.detail == "1 delta applied, 1 commit, validator clean. Skipped: none"
    assert outcome.triage == fleet.Verdict(True, "The app now consumes a queue.")
    assert outcome.update is not None
    assert outcome.update.session_id == "sid-fake-1"
    assert outcome.update.commits == (_git(clone, "log", "-1", "--format=%h %s"),)
    assert outcome.update.commits[0].endswith(" architecture: docs/architecture/a.yaml")
    assert _state(f) == {ID: {"date": "2026-09-11", "outcome": f"updated: {outcome.detail}"}}


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
    f, _, _ = _stale(tmp_path)
    kc.play(UPDATE, turn)
    outcome = _update(f)
    detail = detail.format(clone=tmp_path / "clones" / "NewsFilter")
    assert (outcome.status, outcome.detail, outcome.reviewed) == (fleet.FAILED, detail, None)
    assert outcome.unresolved
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
        fl: fleet.Fleet, producer: fleet.Producer, reviewed: str | None
    ) -> fleet.Outcome:
        if producer.id == "paper-clock":
            raise Killed
        return update_producer(fl, producer, reviewed)

    monkeypatch.setattr(fleet, "update_producer", killed_at_the_second)
    with pytest.raises(Killed):
        fleet.run(["update"], f, NOW)
    assert list(_state(f)) == [ID]
