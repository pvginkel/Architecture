#!/usr/bin/env python3
"""The central architecture update: scans, stages and updates the producer repos.

    python3 tooling/fleet.py scan            each registered producer: stale, current,
                                             not fleet-managed, or failed with the reason
    python3 tooling/fleet.py stage <Repo>    clone or fetch one repo and stage the kit into
                                             it; starts no session
    python3 tooling/fleet.py update [<id>…]  each stale producer, or the named ones, one at a
                                             time: a triage session, then unless it says skip
                                             an update session in the clone

It runs with the dev container's python3, so it imports only the standard
library and PyYAML.

A producer's clone is `/tmp/architecture-update/repos/<Repo>`: blob-less,
fetched when present, checked out at `origin/HEAD`, with this repo's kit (the
KIT_DIRS under `.claude/`) copied into the clone's `.claude/` and listed in its
`.git/info/exclude`. What varies per repo comes from its `.architecturerc` at
`origin/HEAD`; the commit each producer was last reviewed at comes from the
specs repo's `architecture-updates/state.yaml`, which `update` rewrites as each
producer finishes.

The sessions are headless `kc` sessions driven as the dev plugin's
`run_kc_session` drives them: `create-headless` in the clone with the staged
agent, `send` under a timeout this tool enforces, `status` for the session
id, and `end` always.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
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
SKIPPED = "skipped"
NOTHING = "nothing to apply"
UPDATED = "updated"

VERDICT = re.compile(r"VERDICT: (update|skip)")
HANDOFF = re.compile(
    r"(\d+) deltas? applied, (\d+) commits?, "
    r"(validator clean|validation by the AaC build|stopped: (.+))\."
)
SKIPPED_LINE = re.compile(r"Skipped: (.+)")


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
class Agent:
    """A headless session's staged agent, model, reasoning effort and timeout in seconds."""

    name: str
    model: str
    effort: str | None
    timeout: int


TRIAGE = Agent("triage-architecture", "sonnet", None, 600)
UPDATE = Agent("update-architecture", "opus", "xhigh", 3600)

# Seconds a send has to wind down after SIGINT before it is killed.
INTERRUPT_GRACE = 15


@dataclass(frozen=True)
class Session:
    """A driven session: `failure` says why it did not finish (None when it did), `session_id`
    is the claude session a later round resumes."""

    failure: str | None
    response: str
    session_id: str | None


@dataclass(frozen=True)
class Verdict:
    update: bool
    reason: str


@dataclass(frozen=True)
class Handoff:
    """The update agent's final two lines."""

    deltas: int
    commits: int
    validation: str
    stopped: str | None
    skipped: str

    @property
    def text(self) -> str:
        deltas = f"{self.deltas} delta{'' if self.deltas == 1 else 's'}"
        commits = f"{self.commits} commit{'' if self.commits == 1 else 's'}"
        return f"{deltas} applied, {commits}, {self.validation}. Skipped: {self.skipped}"


@dataclass(frozen=True)
class UpdateResult:
    """What the update session left: `commits` are `<short sha> <subject>`, oldest first."""

    clone: Clone
    session_id: str | None
    handoff: Handoff | None
    commits: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    """One producer's result from `update`; `reviewed` is the commit its state advances to,
    None to leave the recorded one."""

    producer: Producer
    status: str
    detail: str = ""
    reviewed: str | None = None
    unresolved: bool = False
    triage: Verdict | None = None
    update: UpdateResult | None = None

    @property
    def state_outcome(self) -> str:
        return f"{self.status}: {self.detail}" if self.detail else self.status


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
          date: <YYYY-MM-DD of the last run that judged it>
          outcome: <that run's outcome for it>

    `reviewed` is absent until a run advances it.
    """
    path = spec_repo / STATE_FILE
    if not path.exists():
        return {}
    state = yaml.safe_load(path.read_text())
    return {producer: entry["reviewed"] for producer, entry in state.items() if "reviewed" in entry}


def record_state(spec_repo: Path, outcome: Outcome, date: str) -> None:
    """Rewrite one producer's state entry, keeping its `reviewed` unless the outcome advances it.

    The file is replaced in one step, so a run killed mid-write leaves the
    previous state whole.
    """
    path = spec_repo / STATE_FILE
    state = yaml.safe_load(path.read_text()) if path.exists() else {}
    reviewed = outcome.reviewed or state.get(outcome.producer.id, {}).get("reviewed")
    entry = {"reviewed": reviewed} if reviewed else {}
    state[outcome.producer.id] = {**entry, "date": date, "outcome": outcome.state_outcome}
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f"{path.name}.tmp")
    staging.write_text(yaml.safe_dump({k: state[k] for k in sorted(state)}, sort_keys=False))
    os.replace(staging, path)


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


def _git_mode(path: Path) -> str:
    return "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"


def kit_conflicts(kit: Path, clone: Path, files: list[Path]) -> list[str]:
    """The kit paths the clone's HEAD tracks with another blob or mode than the kit's."""
    paths = {f".claude/{rel.as_posix()}": kit / rel for rel in files}
    tracked = {}
    for line in git(clone, "ls-tree", "-r", "HEAD", "--", *paths).splitlines():
        entry, path = line.split("\t", 1)
        mode, _, blob = entry.split()
        tracked[path] = (mode, blob)
    names = sorted(tracked)
    blobs = git(clone, "hash-object", "--no-filters", "--", *(str(paths[n]) for n in names))
    return [
        name
        for name, blob in zip(names, blobs.split(), strict=True)
        if tracked[name] != (_git_mode(paths[name]), blob)
    ]


def stage_kit(kit: Path, clone: Path) -> None:
    """Copy the kit into `clone/.claude/` and exclude it; refuse a conflicting tracked file.

    The refusal comes before any copy, so a refused clone keeps its tracked
    files and every later run reports the same conflict.
    """
    files = kit_files(kit)
    conflicts = kit_conflicts(kit, clone, files)
    if conflicts:
        raise ProducerError(
            "the repo tracks kit files that differ from the kit: " + ", ".join(conflicts)
        )
    staged = []
    for rel in files:
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
            "staging the kit left the clone dirty: " + "; ".join(line.strip() for line in dirty)
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


def _kc(cwd: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kc", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout
    )


def _last_line(proc: subprocess.CompletedProcess[str]) -> str:
    lines = (proc.stderr or proc.stdout).strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode}"


def _send(name: str, prompt: str, cwd: Path, timeout: int) -> tuple[int | None, str]:
    """Send one prompt and wait for the turn: its exit code (None when it timed out) and response.

    `kc session send` interrupts the turn on SIGINT, so a send still running
    when this returns, for any reason, is interrupted and then killed if it
    outlives INTERRUPT_GRACE.
    """
    with tempfile.TemporaryDirectory(prefix="fleet-send-") as tmp:
        prompt_file = Path(tmp) / "prompt"
        response_file = Path(tmp) / "response"
        prompt_file.write_text(prompt)
        proc = subprocess.Popen(
            [
                "kc", "session", "send", name,
                "--prompt-file", str(prompt_file),
                "--response-file", str(response_file),
                "-v",
            ],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
        )
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, ""
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=INTERRUPT_GRACE)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        return code, response_file.read_text() if response_file.exists() else ""


def _session_id(name: str, cwd: Path) -> str | None:
    status = _kc(cwd, "session", "status", name, "--output=json", timeout=60)
    if status.returncode != 0:
        return None
    session_id: str = json.loads(status.stdout).get("sessionId") or ""
    return session_id or None


def run_session(cwd: Path, agent: Agent, prompt: str) -> Session:
    """Drive one headless session in `cwd` to the end of its turn, and end it."""
    args = ["session", "create-headless", "--cwd", str(cwd), "--agent", agent.name]
    args += ["--model", agent.model]
    if agent.effort:
        args += ["--reasoning-effort", agent.effort]
    created = _kc(cwd, *args)
    if created.returncode != 0 or not created.stdout.strip():
        return Session(f"did not start: {_last_line(created)}", "", None)
    name = created.stdout.strip().splitlines()[-1].strip()
    try:
        code, response = _send(name, prompt, cwd, agent.timeout)
        if code is None:
            return Session(f"timed out after {agent.timeout} s", "", None)
        if code != 0:
            return Session(f"exited {code}", response, None)
        return Session(None, response, _session_id(name, cwd))
    finally:
        ended = _kc(cwd, "session", "end", name, timeout=60)
        if ended.returncode != 0:
            print(f"kc session end {name} failed: {_last_line(ended)}", file=sys.stderr)


def _final_lines(response: str) -> list[str]:
    return [line.strip() for line in response.splitlines() if line.strip()][-2:]


def parse_verdict(response: str) -> Verdict:
    """The triage agent's final two lines, `VERDICT: update|skip` and a line of reason.

    Anything else counts as update.
    """
    lines = _final_lines(response)
    if len(lines) == 2 and (verdict := VERDICT.fullmatch(lines[0])):
        return Verdict(verdict[1] == "update", lines[1])
    return Verdict(True, "no parseable verdict; counted as update")


def parse_handoff(response: str) -> Handoff | None:
    """The update agent's final two lines, or None when they are not its handoff."""
    lines = _final_lines(response)
    if len(lines) != 2:
        return None
    summary, skipped = HANDOFF.fullmatch(lines[0]), SKIPPED_LINE.fullmatch(lines[1])
    if not (summary and skipped):
        return None
    return Handoff(int(summary[1]), int(summary[2]), summary[3], summary[4], skipped[1])


def _brief(scan: Scan) -> str:
    return (
        f"- Producer id: {scan.producer.id}\n"
        f"- Mode: {'generated' if scan.config.generated else 'hand-authored'}\n"
        f"- Sources: {' '.join(f'`{s}`' for s in scan.config.sources)}\n"
        f"- Base commit: {scan.base}\n"
    )


def _instructions(scan: Scan) -> str:
    return (
        f"\nThe repo's instructions, verbatim from its `{RC_FILE}`:\n\n"
        f"{scan.config.instructions or '(none)'}\n"
    )


def triage_prompt(scan: Scan) -> str:
    noun = "commit" if scan.commits == 1 else "commits"
    return (
        f"Does anything in {scan.base}..HEAD ({scan.commits} {noun}) change what producer "
        f"`{scan.producer.id}`'s architecture must say? End with your two-line verdict.\n\n"
        + _brief(scan)
        + _instructions(scan)
    )


def update_prompt(scan: Scan) -> str:
    return (
        f"Bring producer `{scan.producer.id}`'s architecture sources up to date with the commits "
        f"in {scan.base}..HEAD. Commit per the repo's cadence, do not push. End with your "
        "two-line handoff.\n\n"
        + _brief(scan)
        + f"- Default branch: {scan.clone.branch}\n"
        + _instructions(scan)
    )


def check_agents(clone: Path) -> None:
    """Refuse a clone missing an agent: `create-headless --agent` with an unknown name
    starts a plain session instead of failing."""
    missing = [
        f".claude/agents/{agent.name}.md"
        for agent in (TRIAGE, UPDATE)
        if not (clone / ".claude" / "agents" / f"{agent.name}.md").is_file()
    ]
    if missing:
        raise ProducerError(f"agent definition(s) missing from the clone: {', '.join(missing)}")


def _dispatch(scan: Scan, agent: Agent, prompt: str) -> Session:
    print(
        f"{scan.producer.id}: {agent.name} session in {scan.clone.path}",
        file=sys.stderr,
        flush=True,
    )
    return run_session(scan.clone.path, agent, prompt)


def judge(scan: Scan) -> Outcome:
    """Triage the stale producer and, unless triage says skip, run the update session."""
    producer, clone = scan.producer, scan.clone
    triage = _dispatch(scan, TRIAGE, triage_prompt(scan))
    if triage.failure:
        return Outcome(producer, FAILED, f"triage session {triage.failure}", unresolved=True)
    verdict = parse_verdict(triage.response)
    if not verdict.update:
        return Outcome(producer, SKIPPED, verdict.reason, reviewed=clone.head, triage=verdict)
    session = _dispatch(scan, UPDATE, update_prompt(scan))
    if session.failure:
        detail = f"update session {session.failure}"
        return Outcome(producer, FAILED, detail, unresolved=True, triage=verdict)
    handoff = parse_handoff(session.response)
    log = git(clone.path, "log", "--reverse", "--format=%h %s", f"{clone.head}..HEAD")
    result = UpdateResult(clone, session.session_id, handoff, tuple(log.splitlines()))
    if _dirty(clone.path):
        detail = f"the update session left uncommitted changes in {clone.path}"
    elif handoff is None:
        detail = "the update session's final two lines are not its handoff"
    elif handoff.stopped:
        detail = f"the update session stopped: {handoff.stopped}"
    elif result.commits:
        return Outcome(producer, UPDATED, handoff.text, triage=verdict, update=result)
    else:
        return Outcome(
            producer, NOTHING, handoff.text, reviewed=clone.head, triage=verdict, update=result
        )
    return Outcome(producer, FAILED, detail, unresolved=True, triage=verdict, update=result)


def update_producer(fleet: Fleet, producer: Producer, reviewed: str | None) -> Outcome:
    if producer.repo is None:
        return Outcome(producer, UNMANAGED)
    try:
        result = scan_producer(fleet, producer, producer.repo, reviewed)
        if result.current:
            return Outcome(producer, CURRENT, reviewed=result.clone.head)
        check_agents(result.clone.path)
        return judge(result)
    except ProducerError as e:
        return Outcome(producer, FAILED, str(e), unresolved=True)


def update(fleet: Fleet, producers: list[Producer], now: datetime) -> Iterator[Outcome]:
    """Each producer in turn; its state is recorded before its outcome is yielded."""
    reviewed = load_reviewed(fleet.spec_repo)
    for producer in producers:
        outcome = update_producer(fleet, producer, reviewed.get(producer.id))
        if producer.repo is not None:
            record_state(fleet.spec_repo, outcome, now.date().isoformat())
        yield outcome


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


def cmd_update(fleet: Fleet, producers: list[Producer], now: datetime) -> int:
    id_width = max((len(p.id) for p in producers), default=0)
    repo_width = max((len(p.repo or "-") for p in producers), default=0)
    unresolved = False
    for outcome in update(fleet, producers, now):
        p = outcome.producer
        line = f"{p.id:<{id_width}}  {p.repo or '-':<{repo_width}}  {outcome.status:<17}"
        print(f"{line}  {outcome.detail}".rstrip(), flush=True)
        unresolved |= outcome.unresolved
    return 1 if unresolved else 0


def run(argv: list[str], fleet: Fleet, now: datetime) -> int:
    parser = argparse.ArgumentParser(prog="fleet.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "scan", help="report each registered producer: stale, current, not fleet-managed, failed"
    )
    stage = commands.add_parser(
        "stage", help="clone or fetch a repo and stage the kit into it; starts no session"
    )
    stage.add_argument("repo", metavar="<Repo>", help="a registered repo's name, or owner/name")
    update_cmd = commands.add_parser(
        "update", help="triage and update each stale producer, or the named ones, in turn"
    )
    update_cmd.add_argument("ids", nargs="*", metavar="<id>", help="a registered producer id")
    args = parser.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(fleet)
    if args.command == "stage":
        return cmd_stage(fleet, args.repo)
    producers = load_registry(fleet.registry)
    unknown = sorted(set(args.ids) - {p.id for p in producers})
    if unknown:
        update_cmd.error(f"unknown producer id(s): {', '.join(unknown)}")
    named = [p for p in producers if p.id in args.ids] if args.ids else producers
    return cmd_update(fleet, named, now)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], Fleet.default(), datetime.now()))
