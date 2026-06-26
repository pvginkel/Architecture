#!/usr/bin/env python3
"""Claude session manager — wraps `claude` with explicit session tracking.

Three subcommands:
    start   — begins a new session in the given project directory
    resume  — continues an existing session using the stored session ID
    finish  — deletes the session state file for a project

Prompts can be passed via --prompt-file or piped via stdin.
The prompt is always delivered to claude via stdin to avoid shell escaping issues.

State files are saved to <project_root>/.claude/sessions/<project_name>.json
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

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SESSIONS_DIR = PROJECT_ROOT / ".claude" / "sessions"

# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------
# VALID_PROJECTS — every project name the orchestrator can dispatch: "root" is
# the orchestrator working tree; the rest are one entry per subproject directory
# under PROJECT_ROOT. EXTERNAL_PROJECTS maps a name to a directory outside the
# repo (unused here).
# ---------------------------------------------------------------------------

VALID_PROJECTS = ("root", "tooling", "viewer", "service")

EXTERNAL_PROJECTS = {}


# ---------------------------------------------------------------------------
# Stream progress reporting
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _tool_description(name: str, inp: dict) -> str:
    if name == "Bash":
        desc = inp.get("description")
        if desc:
            return desc
        return _truncate(inp.get("command", ""))
    if name == "Read":
        path = inp.get("file_path", "")
        basename = PurePosixPath(path).name
        parts = [basename]
        if inp.get("offset") or inp.get("limit"):
            try:
                start = int(inp.get("offset", 1))
            except (TypeError, ValueError):
                start = 1
            try:
                limit = int(inp.get("limit")) if inp.get("limit") else None
            except (TypeError, ValueError):
                limit = None
            if limit:
                parts.append(f"lines {start}-{start + limit - 1}")
            else:
                parts.append(f"from line {start}")
        return " ".join(parts) if len(parts) == 1 else f"{parts[0]} ({parts[1]})"
    if name == "Grep":
        pattern = _truncate(inp.get("pattern", ""), 50)
        path = inp.get("path", "")
        basename = PurePosixPath(path).name if path else ""
        if basename:
            return f'"{pattern}" in {basename}'
        return f'"{pattern}"'
    if name in ("Glob", "Write", "Edit"):
        path = inp.get("file_path", inp.get("pattern", ""))
        return PurePosixPath(path).name if path else name
    if name == "Agent":
        return inp.get("description", "subagent")
    return name


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


class StreamProcessor:
    def __init__(self):
        self.agents: dict[str, str] = {}
        self.pending_tools: dict[str, str] = {}
        self.start_time: float | None = None

    def _elapsed(self) -> str:
        if self.start_time is None:
            self.start_time = time.monotonic()
        elapsed = time.monotonic() - self.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        if minutes:
            return f"[{minutes}m{seconds:02d}s]"
        return f"[{seconds}s]"

    def _agent_prefix(self, task_id: str) -> str:
        name = self.agents.get(task_id, "agent")
        return f"[subagent: {name}] "

    def process_line(self, raw: str) -> list[str]:
        raw = raw.strip()
        if not raw:
            return []
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return []

        typ = obj.get("type")
        subtype = obj.get("subtype")
        ts = self._elapsed()

        if typ == "system" and subtype == "init":
            model = obj.get("model", "unknown")
            return [f"{ts} [init] Session started ({model})"]

        if typ == "system" and subtype == "task_started":
            task_id = obj.get("task_id", "")
            desc = obj.get("description", "agent")
            self.agents[task_id] = desc
            return []

        if typ == "system" and subtype == "task_progress":
            task_id = obj.get("task_id", "")
            prefix = self._agent_prefix(task_id)
            desc = obj.get("description", "")
            usage = obj.get("usage", {})
            tools = usage.get("tool_uses", 0)
            return [f"{ts} {prefix}[progress] {_truncate(desc)} ({tools} tools)"]

        if typ == "system" and subtype == "task_notification":
            task_id = obj.get("task_id", "")
            prefix = self._agent_prefix(task_id)
            status = obj.get("status", "unknown")
            usage = obj.get("usage", {})
            duration = usage.get("duration_ms", 0)
            tools = usage.get("tool_uses", 0)
            return [f"{ts} {prefix}[agent] {status} ({_format_duration(duration)}, {tools} tools)"]

        if typ == "assistant":
            if obj.get("parent_tool_use_id"):
                return []
            lines = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    lines.append(f"{ts} [text] {_truncate(block['text'])}")
                elif block.get("type") == "tool_use":
                    tool_id = block.get("id", "")
                    name = block["name"]
                    inp = block.get("input", {})
                    desc = _tool_description(name, inp)
                    self.pending_tools[tool_id] = name
                    lines.append(f"{ts} [tool_use: {name}] {desc}")
            return lines

        if typ == "user" and not obj.get("parent_tool_use_id"):
            lines = []
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "tool_result" and block.get("is_error"):
                    tool_id = block.get("tool_use_id", "")
                    tool_name = self.pending_tools.get(tool_id, "unknown")
                    content = block.get("content", "")
                    if isinstance(content, str):
                        error_text = content
                    elif isinstance(content, list):
                        error_text = " ".join(
                            b.get("text", "") for b in content if b.get("type") == "text"
                        )
                    else:
                        error_text = str(content)
                    lines.append(f"{ts} [tool_error: {tool_name}] {_truncate(error_text)}")
            return lines

        if typ == "rate_limit_event":
            info = obj.get("rate_limit_info", {})
            if info.get("status") != "allowed":
                return [f"{ts} [rate_limit] {info.get('status', 'unknown')}"]
            return []

        if typ == "result":
            duration = _format_duration(obj.get("duration_ms", 0))
            if obj.get("is_error"):
                result_text = _truncate(obj.get("result", ""))
                return [f"{ts} [result] Failed ({duration}): {result_text}"]
            return [f"{ts} [result] Done ({duration})"]

        return []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_dir(name: str) -> str:
    """Resolve a project name to its absolute directory path.

    'root' resolves to the monorepo root itself.
    Internal projects (backend, frontend, portal) live under PROJECT_ROOT.
    External projects (sse-gateway) live at configured paths outside the monorepo.
    """
    if name == "root":
        return str(PROJECT_ROOT)
    if name in EXTERNAL_PROJECTS:
        path = EXTERNAL_PROJECTS[name]
        if not path.exists():
            print(
                f"Error: external project directory not found: {path}\n"
                f"The '{name}' project is expected at {path}.",
                file=sys.stderr,
            )
            sys.exit(1)
        return str(path)
    return str(PROJECT_ROOT / name)


def _state_path(name: str) -> Path:
    return SESSIONS_DIR / f"{name}.json"


def _load_state(name: str) -> dict:
    path = _state_path(name)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _save_state(name: str, state: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_state_path(name), "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _read_prompt(args) -> str:
    """Read the prompt from --prompt-file or stdin."""
    if args.prompt_file:
        prompt_file = Path(args.prompt_file)
        if not prompt_file.exists():
            print(f"Error: prompt file not found: {prompt_file}", file=sys.stderr)
            sys.exit(1)
        return prompt_file.read_text()

    # Read from stdin
    if sys.stdin.isatty():
        print("Error: no prompt provided. Use --prompt-file or pipe via stdin.", file=sys.stderr)
        sys.exit(1)
    return sys.stdin.read()


def _build_cmd(session_id: str | None = None) -> list[str]:
    """Build the claude command. Prompt is delivered via stdin."""
    cmd = [
        "claude",
        "--print",
        "--verbose",
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
    ]
    if session_id:
        cmd.extend(["--resume", session_id])
    return cmd


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def _kill_process(pid: int) -> None:
    """Send SIGTERM to a process, then SIGKILL after 5s if still alive.

    The process runs inside a PID namespace, so killing it causes the
    kernel to unconditionally clean up all descendants.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return  # already gone
    for _ in range(10):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)  # check if still alive
        except OSError:
            return  # gone
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


class StreamResult:
    """Parsed result from a stream-json session."""
    def __init__(self):
        self.result_text: str = ""
        self.session_id: str | None = None
        self.is_error: bool = False


def _run(cmd: list[str], project: str, timeout: int,
         state: dict, state_name: str, prompt: str) -> tuple[int, StreamResult]:
    """Run cmd inside a PID namespace. Pipes prompt via stdin.

    Reads stream-json stdout line by line, printing progress to stderr.
    Returns (returncode, StreamResult).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=project,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_build_env(),
    )
    state["pid"] = proc.pid
    _save_state(state_name, state)

    # Send prompt and close stdin
    proc.stdin.write(prompt)
    proc.stdin.close()

    processor = StreamProcessor()
    result = StreamResult()
    deadline = time.monotonic() + timeout

    try:
        # Read stdout line by line for progress reporting
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)

            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break  # EOF

                # Extract result/session_id from the result event
                stripped = line.strip()
                if stripped:
                    try:
                        obj = json.loads(stripped)
                        if obj.get("type") == "result":
                            result.result_text = obj.get("result", "")
                            result.session_id = obj.get("session_id")
                            result.is_error = obj.get("is_error", False)
                        elif obj.get("type") == "system" and obj.get("subtype") == "init":
                            result.session_id = obj.get("session_id")
                    except json.JSONDecodeError:
                        pass

                # Print progress to stderr
                for progress_line in processor.process_line(line):
                    print(progress_line, file=sys.stderr, flush=True)

            elif proc.poll() is not None:
                # Process exited, drain remaining output
                for line in proc.stdout:
                    for progress_line in processor.process_line(line):
                        print(progress_line, file=sys.stderr, flush=True)
                    stripped = line.strip()
                    if stripped:
                        try:
                            obj = json.loads(stripped)
                            if obj.get("type") == "result":
                                result.result_text = obj.get("result", "")
                                result.session_id = obj.get("session_id")
                                result.is_error = obj.get("is_error", False)
                        except json.JSONDecodeError:
                            pass
                break
    except subprocess.TimeoutExpired:
        _kill_process(proc.pid)
        proc.wait()
        raise
    except KeyboardInterrupt:
        _kill_process(proc.pid)
        proc.wait()
        state["pid"] = None
        raise

    proc.wait()
    state["pid"] = None
    return proc.returncode, result


def _write_response(result_text: str, response_file: str | None) -> None:
    """Write the agent's response to --response-file or stdout."""
    if response_file:
        Path(response_file).write_text(result_text)
    else:
        print(result_text)


def cmd_start(args) -> None:
    prompt = _read_prompt(args)
    name = args.project
    project_path = _project_dir(name)
    cmd = _build_cmd()

    invocation = {
        "command": "start",
        "prompt": prompt,
        "started_at": _now_iso(),
        "ended_at": None,
        "duration_ms": 0,
        "result_preview": "",
        "is_error": False,
        "timed_out": False,
    }
    state = {
        "session_id": None,
        "project": name,
        "pid": None,
        "started_at": _now_iso(),
        "status": "running",
        "invocations": [invocation],
    }
    _save_state(name, state)

    t0 = time.monotonic()
    try:
        returncode, result = _run(cmd, project_path, args.timeout, state, name, prompt)
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - t0) * 1000)
        invocation["ended_at"] = _now_iso()
        invocation["duration_ms"] = duration_ms
        invocation["timed_out"] = True
        state["status"] = "timeout"
        _save_state(name, state)
        print(f"Error: timed out after {args.timeout}s", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        duration_ms = int((time.monotonic() - t0) * 1000)
        invocation["ended_at"] = _now_iso()
        invocation["duration_ms"] = duration_ms
        state["status"] = "interrupted"
        _save_state(name, state)
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

    duration_ms = int((time.monotonic() - t0) * 1000)
    invocation["ended_at"] = _now_iso()
    invocation["duration_ms"] = duration_ms
    invocation["result_preview"] = result.result_text[:500] if result.result_text else ""

    if returncode != 0:
        invocation["is_error"] = True
        state["status"] = "error"
        state["session_id"] = result.session_id
        _save_state(name, state)
        print(result.result_text, file=sys.stderr)
        sys.exit(1)

    state["session_id"] = result.session_id
    state["status"] = "completed"
    _save_state(name, state)
    _write_response(result.result_text, args.response_file)


def cmd_resume(args) -> None:
    prompt = _read_prompt(args)
    name = args.project

    state = _load_state(name)
    if not state or not state.get("session_id"):
        print(
            f"Error: no existing session for project '{name}'. "
            f"Run 'start' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    session_id = state["session_id"]
    project_path = _project_dir(name)
    cmd = _build_cmd(session_id)

    invocation = {
        "command": "resume",
        "prompt": prompt,
        "started_at": _now_iso(),
        "ended_at": None,
        "duration_ms": 0,
        "result_preview": "",
        "is_error": False,
        "timed_out": False,
    }
    state["status"] = "running"
    state["invocations"].append(invocation)
    _save_state(name, state)

    t0 = time.monotonic()
    try:
        returncode, result = _run(cmd, project_path, args.timeout, state, name, prompt)
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - t0) * 1000)
        invocation["ended_at"] = _now_iso()
        invocation["duration_ms"] = duration_ms
        invocation["timed_out"] = True
        state["status"] = "timeout"
        _save_state(name, state)
        print(f"Error: timed out after {args.timeout}s", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        duration_ms = int((time.monotonic() - t0) * 1000)
        invocation["ended_at"] = _now_iso()
        invocation["duration_ms"] = duration_ms
        state["status"] = "interrupted"
        _save_state(name, state)
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

    duration_ms = int((time.monotonic() - t0) * 1000)
    invocation["ended_at"] = _now_iso()
    invocation["duration_ms"] = duration_ms
    invocation["result_preview"] = result.result_text[:500] if result.result_text else ""

    if result.session_id:
        state["session_id"] = result.session_id

    if returncode != 0:
        invocation["is_error"] = True
        state["status"] = "error"
        _save_state(name, state)
        print(result.result_text, file=sys.stderr)
        sys.exit(1)

    state["status"] = "completed"
    _save_state(name, state)
    _write_response(result.result_text, args.response_file)


def cmd_finish(args) -> None:
    name = args.project
    path = _state_path(name)
    if not path.exists():
        print(f"No session file for '{name}'. Nothing to do.")
        return
    state = _load_state(name)
    pid = state.get("pid")
    if pid:
        print(f"Killing process {pid} (PID namespace will clean up descendants)...", file=sys.stderr)
        _kill_process(pid)
    path.unlink()
    print(f"Session for '{name}' removed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude session manager with explicit session tracking"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, handler in [("start", cmd_start), ("resume", cmd_resume)]:
        sub = subparsers.add_parser(name)
        sub.add_argument("--project", required=True, choices=VALID_PROJECTS, help="Project name")
        sub.add_argument("--prompt-file", help="Path to plain text file containing the prompt (reads stdin if omitted)")
        sub.add_argument("--response-file", help="Write agent response to this file (writes to stdout if omitted)")
        sub.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default: 3600)")
        sub.set_defaults(func=handler)

    finish_sub = subparsers.add_parser("finish")
    finish_sub.add_argument("--project", required=True, choices=VALID_PROJECTS, help="Project name")
    finish_sub.set_defaults(func=cmd_finish)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
