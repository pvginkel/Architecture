#!/usr/bin/env python3
"""The central architecture update: scans and stages the producer repos.

    python3 tooling/fleet.py scan            each registered producer: stale, current,
                                             not fleet-managed, or failed with the reason
    python3 tooling/fleet.py stage <Repo>    clone or fetch one repo and stage the kit into
                                             it; starts no session

It runs with the dev container's python3, so it imports only the standard
library and PyYAML.

A producer's clone is `/tmp/architecture-update/repos/<Repo>`: blob-less,
fetched when present, checked out at `origin/HEAD`, with this repo's kit (the
KIT_DIRS under `.claude/`) copied into the clone's `.claude/` and listed in its
`.git/info/exclude`. What varies per repo comes from its `.architecturerc` at
`origin/HEAD`; the commit each producer was last reviewed at comes from the
specs repo's `architecture-updates/state.yaml`.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CLONES = Path("/tmp/architecture-update/repos")
GITHUB = "https://github.com"

KIT_DIRS = ("agents", "skills/seed-architecture", "architecture")

RC_FILE = ".architecturerc"
RC_KEYS = frozenset({"generated", "sources", "instructions"})
DEFAULT_SOURCES = (":(glob)**/docs/architecture/**",)

STATE_FILE = Path("architecture-updates/state.yaml")

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
REPO_ARG = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?")

STALE = "stale"
CURRENT = "current"
UNMANAGED = "not fleet-managed"
FAILED = "failed"


class ProducerError(Exception):
    """A producer the run reports as failed, with the reason, and moves past."""


@dataclass(frozen=True)
class Fleet:
    """Where the tool reads and writes; the tests point every path at tmp_path."""

    registry: Path
    kit: Path
    clones: Path
    spec_repo: Path
    remote_base: str

    @classmethod
    def default(cls) -> Fleet:
        return cls(
            registry=REPO_ROOT / "pipeline-producers.yaml",
            kit=REPO_ROOT / ".claude",
            clones=CLONES,
            spec_repo=spec_repo_from(REPO_ROOT / ".aiworkflowrc"),
            remote_base=GITHUB,
        )

    def url(self, repo: str) -> str:
        return f"{self.remote_base}/{repo}.git"


@dataclass(frozen=True)
class Producer:
    id: str
    repo: str | None


@dataclass(frozen=True)
class RepoConfig:
    generated: bool = False
    sources: tuple[str, ...] = DEFAULT_SOURCES
    instructions: str = ""


@dataclass(frozen=True)
class Clone:
    path: Path
    branch: str
    head: str


@dataclass(frozen=True)
class Scan:
    producer: Producer
    clone: Clone
    config: RepoConfig
    watermark: str
    base: str
    commits: int
    shortstat: str

    @property
    def current(self) -> bool:
        return self.base == self.clone.head


@dataclass(frozen=True)
class ScanRow:
    producer: str
    repo: str
    status: str
    detail: str


def spec_repo_from(aiworkflowrc: Path) -> Path:
    with aiworkflowrc.open("rb") as f:
        spec_repo: str = tomllib.load(f)["spec_repo"]
    return (aiworkflowrc.parent / spec_repo).resolve()


def load_registry(path: Path) -> list[Producer]:
    return [Producer(p["id"], p.get("repo")) for p in yaml.safe_load(path.read_text())["producers"]]


def load_reviewed(spec_repo: Path) -> dict[str, str]:
    """Each producer's `reviewed` commit; a missing state file means none is reviewed.

    The state file maps producer id to the producer's last review:

        newsfilter:
          reviewed: <commit its architecture was last reviewed at>
          date: <YYYY-MM-DD>
          outcome: <the last run's outcome for it>
    """
    path = spec_repo / STATE_FILE
    if not path.exists():
        return {}
    state = yaml.safe_load(path.read_text())
    return {producer: entry["reviewed"] for producer, entry in state.items()}


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _failure(args: tuple[str, ...], proc: subprocess.CompletedProcess[str]) -> ProducerError:
    lines = proc.stderr.strip().splitlines()
    return ProducerError(
        f"git {args[0]} failed: {lines[-1] if lines else f'exit {proc.returncode}'}"
    )


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=_git_env(), capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise _failure(args, proc)
    return proc.stdout


def is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    args = ("merge-base", "--is-ancestor", ancestor, descendant)
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=_git_env(), capture_output=True, text=True, check=False
    )
    if proc.returncode not in (0, 1):
        raise _failure(args, proc)
    return proc.returncode == 0


def parse_repo_config(text: str) -> RepoConfig:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ProducerError(f"{RC_FILE}: not valid YAML: {' '.join(str(e).split())}") from None
    if not isinstance(data, dict):
        raise ProducerError(f"{RC_FILE}: must be a mapping")
    unknown = sorted(str(k) for k in data if k not in RC_KEYS)
    if unknown:
        raise ProducerError(f"{RC_FILE}: unknown key(s): {', '.join(unknown)}")
    generated = data.get("generated", False)
    if not isinstance(generated, bool):
        raise ProducerError(f"{RC_FILE}: `generated` must be true or false")
    sources = data.get("sources", list(DEFAULT_SOURCES))
    if (
        not isinstance(sources, list)
        or not sources
        or not all(isinstance(s, str) and s for s in sources)
    ):
        raise ProducerError(f"{RC_FILE}: `sources` must be a non-empty list of pathspecs")
    instructions = data.get("instructions", "")
    if not isinstance(instructions, str):
        raise ProducerError(f"{RC_FILE}: `instructions` must be text")
    return RepoConfig(generated, tuple(sources), instructions)


def read_repo_config(clone: Path, head: str) -> RepoConfig:
    if not git(clone, "ls-tree", "--name-only", head, "--", RC_FILE).strip():
        return RepoConfig()
    return parse_repo_config(git(clone, "show", f"{head}:{RC_FILE}"))


def kit_files(kit: Path) -> list[Path]:
    """The kit's files, relative to `kit` (this repo's `.claude/`)."""
    return sorted(
        path.relative_to(kit)
        for top in KIT_DIRS
        for path in (kit / top).rglob("*")
        if path.is_file()
    )


def _dirty(clone: Path) -> list[str]:
    return git(clone, "status", "--porcelain").splitlines()


def stage_kit(kit: Path, clone: Path) -> None:
    """Copy the kit into `clone/.claude/` and exclude it; refuse a conflicting tracked file."""
    staged = []
    for rel in kit_files(kit):
        dest = clone / ".claude" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kit / rel, dest)
        staged.append(f"/.claude/{rel.as_posix()}")
    exclude = clone / ".git" / "info" / "exclude"
    text = exclude.read_text() if exclude.exists() else ""
    listed = set(text.splitlines())
    missing = [path for path in staged if path not in listed]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(text + "".join(f"{path}\n" for path in missing))
    dirty = _dirty(clone)
    if dirty:
        raise ProducerError(
            "the repo tracks kit files with different content: "
            + "; ".join(line.strip() for line in dirty)
        )


def prepare(fleet: Fleet, repo: str) -> Clone:
    """Clone or fetch `repo`, check out `origin/HEAD` and stage the kit.

    A clone carrying local work (uncommitted changes, unpushed commits) is
    refused: checking out `origin/HEAD` would drop it.
    """
    path = fleet.clones / repo.split("/")[1]
    if path.exists():
        git(path, "fetch", "--quiet", "origin")
        if _dirty(path):
            raise ProducerError(
                f"uncommitted changes in {path}: commit and push or discard by hand"
            )
        if git(path, "rev-list", "HEAD", "--branches", "--not", "--remotes").strip():
            raise ProducerError(f"unpushed commits in {path}: push or discard by hand")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        git(path.parent, "clone", "--quiet", "--filter=blob:none", fleet.url(repo), path.name)
    branch = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    branch = branch.removeprefix("origin/")
    head = git(path, "rev-parse", "origin/HEAD").strip()
    git(path, "checkout", "--quiet", "-B", branch, head)
    stage_kit(fleet.kit, path)
    return Clone(path, branch, head)


def source_files(clone: Clone, sources: tuple[str, ...]) -> list[str]:
    """The files the sources match at `origin/HEAD`, in path order."""
    return git(
        clone.path, "diff", "--name-only", "--no-renames", EMPTY_TREE, clone.head, "--", *sources
    ).splitlines()


def check_envelope(clone: Clone, files: list[str], producer: str) -> None:
    """Fail a producer whose first source artifact names another producer.

    Sources also hold notes and data files (`SEED-NOTES.md`, a generator's
    input YAML), so the first YAML file with a top-level `producer:` decides.
    """
    for path in files:
        if not path.endswith((".yaml", ".yml")):
            continue
        try:
            doc = yaml.safe_load(git(clone.path, "show", f"{clone.head}:{path}"))
        except yaml.YAMLError as e:
            raise ProducerError(f"{path}: not valid YAML: {' '.join(str(e).split())}") from None
        if isinstance(doc, dict) and "producer" in doc:
            if doc["producer"] != producer:
                raise ProducerError(
                    f"{path} declares `producer: {doc['producer']}`, "
                    f"the registry entry is {producer}: is its `repo` right?"
                )
            return
    raise ProducerError("no source declares a `producer:` envelope")


def pick_base(clone: Clone, watermark: str, reviewed: str | None) -> str:
    """The later of the watermark and the reviewed commit."""
    if reviewed is None:
        return watermark
    if not is_ancestor(clone.path, reviewed, clone.head):
        raise ProducerError(f"reviewed commit {reviewed} is not in origin/HEAD's history")
    return reviewed if is_ancestor(clone.path, watermark, reviewed) else watermark


def scan_producer(fleet: Fleet, producer: Producer, repo: str, reviewed: str | None) -> Scan:
    clone = prepare(fleet, repo)
    config = read_repo_config(clone.path, clone.head)
    files = source_files(clone, config.sources)
    if not files:
        raise ProducerError(f"no sources at origin/HEAD: {', '.join(config.sources)}")
    if not config.generated:
        check_envelope(clone, files, producer.id)
    watermark = git(clone.path, "log", "-1", "--format=%H", clone.head, "--", *config.sources)
    base = pick_base(clone, watermark.strip(), reviewed)
    if base == clone.head:
        return Scan(producer, clone, config, watermark.strip(), base, 0, "")
    commits = git(clone.path, "rev-list", "--count", "--no-merges", f"{base}..{clone.head}")
    shortstat = git(clone.path, "diff", "--shortstat", base, clone.head)
    return Scan(
        producer, clone, config, watermark.strip(), base, int(commits), shortstat.strip()
    )


def scan(fleet: Fleet) -> Iterator[ScanRow]:
    reviewed = load_reviewed(fleet.spec_repo)
    for producer in load_registry(fleet.registry):
        if producer.repo is None:
            yield ScanRow(producer.id, "-", UNMANAGED, "")
            continue
        try:
            result = scan_producer(fleet, producer, producer.repo, reviewed.get(producer.id))
        except ProducerError as e:
            yield ScanRow(producer.id, producer.repo, FAILED, str(e))
            continue
        if result.current:
            yield ScanRow(producer.id, producer.repo, CURRENT, "")
        else:
            noun = "commit" if result.commits == 1 else "commits"
            detail = f"{result.commits} {noun} since {result.base[:12]}: {result.shortstat}"
            yield ScanRow(producer.id, producer.repo, STALE, detail)


def resolve_repo(fleet: Fleet, name: str) -> str:
    """`owner/name` as given, or a bare name looked up in the registry."""
    if not REPO_ARG.fullmatch(name):
        raise ProducerError(f"{name}: expected a repo name or owner/name")
    if "/" in name:
        return name
    for producer in load_registry(fleet.registry):
        if producer.repo is not None and producer.repo.split("/")[1] == name:
            return producer.repo
    raise ProducerError(f"{name} is not a registered repo; name it as <owner>/{name}")


def cmd_scan(fleet: Fleet) -> int:
    producers = load_registry(fleet.registry)
    id_width = max(len(p.id) for p in producers)
    repo_width = max(len(p.repo or "-") for p in producers)
    failed = False
    for row in scan(fleet):
        line = f"{row.producer:<{id_width}}  {row.repo:<{repo_width}}  {row.status:<17}"
        print(f"{line}  {row.detail}".rstrip(), flush=True)
        failed |= row.status == FAILED
    return 1 if failed else 0


def cmd_stage(fleet: Fleet, name: str) -> int:
    try:
        clone = prepare(fleet, resolve_repo(fleet, name))
    except ProducerError as e:
        print(f"stage {name}: {e}", file=sys.stderr)
        return 1
    print(f"staged {clone.path} at {clone.branch} {clone.head[:12]}")
    return 0


def run(argv: list[str], fleet: Fleet) -> int:
    parser = argparse.ArgumentParser(prog="fleet.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "scan", help="report each registered producer: stale, current, not fleet-managed, failed"
    )
    stage = commands.add_parser(
        "stage", help="clone or fetch a repo and stage the kit into it; starts no session"
    )
    stage.add_argument("repo", metavar="<Repo>", help="a registered repo's name, or owner/name")
    args = parser.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(fleet)
    return cmd_stage(fleet, args.repo)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], Fleet.default()))
