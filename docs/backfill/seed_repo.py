#!/usr/bin/env python3
"""Seed-architecture runner — launches a headless `claude` inside a cloned repo
to author its first architecture artifact via the /seed-architecture skill.

Generalized from DesignAssistant/scripts/claude_session.py: instead of a fixed
project enum it takes an arbitrary repo directory, runs one prompt to completion,
streams progress to a log file + stderr, and records the session id so a follow-up
turn can `--resume` if needed.

Usage:
    seed_repo.py start  --name electronics-inventory \
        --repo-dir tmp/backfill/ElectronicsInventory \
        --prompt-file docs/backfill/prompts/electronics-inventory.md \
        --timeout 5400
    seed_repo.py resume --name electronics-inventory \
        --repo-dir tmp/backfill/ElectronicsInventory --prompt-file <followup.md>

State + logs live under docs/backfill/runs/<name>.{session.json,log}.
The agent's final text is written to docs/backfill/runs/<name>.response.md.
"""

import argparse
import json
import os
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent          # docs/backfill
RUNS_DIR = SCRIPT_DIR / "runs"


# ---------------------------------------------------------------------------
# Stream progress reporting (verbatim behaviour from claude_session.py)
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 100) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _tool_description(name: str, inp: dict) -> str:
    if name == "Bash":
        return inp.get("description") or _truncate(inp.get("command", ""))
    if name == "Read":
        return PurePosixPath(inp.get("file_path", "")).name
    if name == "Grep":
        return f'"{_truncate(inp.get("pattern", ""), 50)}"'
    if name in ("Glob", "Write", "Edit"):
        path = inp.get("file_path", inp.get("pattern", ""))
        return PurePosixPath(path).name if path else name
    if name == "Agent":
        return inp.get("description", "subagent")
    if name == "Skill":
        return inp.get("skill", "skill")
    return name


def _format_duration(ms: float) -> str:
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


class StreamProcessor:
    def __init__(self):
        self.agents: dict[str, str] = {}
        self.pending_tools: dict[str, str] = {}
        self.start_time: float | None = None

    def _elapsed(self) -> str:
        if self.start_time is None:
            self.start_time = time.monotonic()
        minutes, seconds = divmod(int(time.monotonic() - self.start_time), 60)
        return f"[{minutes}m{seconds:02d}s]" if minutes else f"[{seconds}s]"

    def _agent_prefix(self, task_id: str) -> str:
        return f"[subagent: {self.agents.get(task_id, 'agent')}] "

    def process_line(self, raw: str) -> list[str]:
        raw = raw.strip()
        if not raw:
            return []
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return []

        typ, subtype, ts = obj.get("type"), obj.get("subtype"), self._elapsed()

        if typ == "system" and subtype == "init":
            return [f"{ts} [init] Session started ({obj.get('model', 'unknown')})"]
        if typ == "system" and subtype == "task_started":
            self.agents[obj.get("task_id", "")] = obj.get("description", "agent")
            return []
        if typ == "system" and subtype == "task_progress":
            prefix = self._agent_prefix(obj.get("task_id", ""))
            tools = obj.get("usage", {}).get("tool_uses", 0)
            return [f"{ts} {prefix}[progress] {_truncate(obj.get('description', ''))} ({tools} tools)"]
        if typ == "system" and subtype == "task_notification":
            prefix = self._agent_prefix(obj.get("task_id", ""))
            usage = obj.get("usage", {})
            return [f"{ts} {prefix}[agent] {obj.get('status', 'unknown')} "
                    f"({_format_duration(usage.get('duration_ms', 0))}, {usage.get('tool_uses', 0)} tools)"]
        if typ == "assistant":
            if obj.get("parent_tool_use_id"):
                return []
            lines = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    lines.append(f"{ts} [text] {_truncate(block['text'])}")
                elif block.get("type") == "tool_use":
                    name = block["name"]
                    self.pending_tools[block.get("id", "")] = name
                    lines.append(f"{ts} [tool: {name}] {_tool_description(name, block.get('input', {}))}")
            return lines
        if typ == "user" and not obj.get("parent_tool_use_id"):
            lines = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "tool_result" and block.get("is_error"):
                    name = self.pending_tools.get(block.get("tool_use_id", ""), "unknown")
                    content = block.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
                    lines.append(f"{ts} [tool_error: {name}] {_truncate(str(content))}")
            return lines
        if typ == "result":
            dur = _format_duration(obj.get("duration_ms", 0))
            if obj.get("is_error"):
                return [f"{ts} [result] Failed ({dur}): {_truncate(obj.get('result', ''))}"]
            return [f"{ts} [result] Done ({dur})"]
        return []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_path(name: str) -> Path:
    return RUNS_DIR / f"{name}.session.json"


def _load_state(name: str) -> dict:
    p = _state_path(name)
    return json.loads(p.read_text()) if p.exists() else {}


def _save_state(name: str, state: dict) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(name).write_text(json.dumps(state, indent=2) + "\n")


def _build_cmd(session_id: str | None) -> list[str]:
    cmd = ["claude", "--print", "--verbose",
           "--dangerously-skip-permissions",
           "--output-format", "stream-json"]
    if session_id:
        cmd.extend(["--resume", session_id])
    return cmd


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def _kill_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(10):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except OSError:
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class StreamResult:
    def __init__(self):
        self.result_text = ""
        self.session_id: str | None = None
        self.is_error = False


def _run(cmd, cwd, timeout, log_fh, prompt) -> tuple[int, StreamResult]:
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=_build_env(),
    )
    proc.stdin.write(prompt)
    proc.stdin.close()

    processor, result = StreamProcessor(), StreamResult()
    deadline = time.monotonic() + timeout

    def emit(line: str):
        for pl in processor.process_line(line):
            print(pl, file=sys.stderr, flush=True)
            log_fh.write(pl + "\n")
            log_fh.flush()

    def capture(line: str):
        s = line.strip()
        if not s:
            return
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            return
        if obj.get("type") == "result":
            result.result_text = obj.get("result", "")
            result.session_id = obj.get("session_id") or result.session_id
            result.is_error = obj.get("is_error", False)
        elif obj.get("type") == "system" and obj.get("subtype") == "init":
            result.session_id = obj.get("session_id")

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break
                capture(line)
                emit(line)
            elif proc.poll() is not None:
                for line in proc.stdout:
                    capture(line)
                    emit(line)
                break
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        _kill_process(proc.pid)
        proc.wait()
        raise

    proc.wait()
    return proc.returncode, result


def _dispatch(name: str, repo_dir: str, prompt: str, timeout: int, session_id: str | None) -> None:
    cwd = str(Path(repo_dir).resolve())
    if not Path(cwd).is_dir():
        sys.exit(f"Error: repo dir not found: {cwd}")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNS_DIR / f"{name}.log"

    state = _load_state(name)
    state.update({"name": name, "repo_dir": cwd, "status": "running", "updated_at": _now_iso()})
    state.setdefault("session_id", session_id)
    _save_state(name, state)

    t0 = time.monotonic()
    with open(log_path, "a") as log_fh:
        log_fh.write(f"\n===== {_now_iso()} {'resume' if session_id else 'start'} {name} =====\n")
        try:
            rc, result = _run(_build_cmd(session_id), cwd, timeout, log_fh, prompt)
        except subprocess.TimeoutExpired:
            state.update(status="timeout", updated_at=_now_iso())
            _save_state(name, state)
            sys.exit(f"Error: timed out after {timeout}s (see {log_path})")
        except KeyboardInterrupt:
            state.update(status="interrupted", updated_at=_now_iso())
            _save_state(name, state)
            sys.exit(130)

    if result.session_id:
        state["session_id"] = result.session_id
    state["duration_ms"] = int((time.monotonic() - t0) * 1000)
    state["updated_at"] = _now_iso()
    (RUNS_DIR / f"{name}.response.md").write_text(result.result_text or "")

    if rc != 0 or result.is_error:
        state["status"] = "error"
        _save_state(name, state)
        sys.exit(f"Session failed (rc={rc}). Response in {RUNS_DIR / (name + '.response.md')}, log in {log_path}")

    state["status"] = "completed"
    _save_state(name, state)
    print(f"OK: {name} completed in {_format_duration(state['duration_ms'])}. "
          f"Response: {RUNS_DIR / (name + '.response.md')}")


def cmd_start(args) -> None:
    _dispatch(args.name, args.repo_dir, Path(args.prompt_file).read_text(), args.timeout, None)


def cmd_resume(args) -> None:
    state = _load_state(args.name)
    sid = state.get("session_id")
    if not sid:
        sys.exit(f"Error: no session id for '{args.name}'; run start first.")
    _dispatch(args.name, args.repo_dir, Path(args.prompt_file).read_text(), args.timeout, sid)


def main() -> None:
    parser = argparse.ArgumentParser(description="Headless seed-architecture runner")
    subs = parser.add_subparsers(dest="command", required=True)
    for sub_name, handler in [("start", cmd_start), ("resume", cmd_resume)]:
        sub = subs.add_parser(sub_name)
        sub.add_argument("--name", required=True, help="Producer/run id (used for log + state filenames)")
        sub.add_argument("--repo-dir", required=True, help="Path to the cloned repo (becomes claude's cwd)")
        sub.add_argument("--prompt-file", required=True, help="Path to the prompt file")
        sub.add_argument("--timeout", type=int, default=5400, help="Timeout in seconds (default 5400)")
        sub.set_defaults(func=handler)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
