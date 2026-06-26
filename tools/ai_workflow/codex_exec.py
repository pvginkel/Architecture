#!/usr/bin/env python3
"""Codex exec wrapper — runs `codex exec` and parses JSONL output.

Unlike claude_session.py, this does not manage sessions. It runs a single
codex exec invocation, streams progress to stderr, and returns the final
text response.

Usage:
    # Prompt via file
    python scripts/codex_exec.py --prompt-file tmp/prompt.md --model gpt-5.4

    # Prompt via stdin
    cat tmp/prompt.md | python scripts/codex_exec.py --model gpt-5.4

    # Save response to file
    python scripts/codex_exec.py --prompt-file tmp/prompt.md --response-file tmp/out.txt

    # Run in a specific directory
    python scripts/codex_exec.py --prompt-file tmp/prompt.md --cd /work/MyProject
"""

import argparse
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_MODEL = "gpt-5.4"


# ---------------------------------------------------------------------------
# Stream progress reporting
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _command_description(command: str) -> str:
    """Extract a readable description from a codex command string.

    Codex wraps commands as `/bin/bash -lc "actual command"`, so we
    strip that wrapper to show only the inner command.
    """
    prefix = '/bin/bash -lc "'
    if command.startswith(prefix) and command.endswith('"'):
        command = command[len(prefix):-1]
    return _truncate(command)


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


class StreamProcessor:
    def __init__(self):
        self.start_time: float | None = None
        self.pending_commands: dict[str, str] = {}  # item_id -> command desc

    def _elapsed(self) -> str:
        if self.start_time is None:
            self.start_time = time.monotonic()
        elapsed = time.monotonic() - self.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        if minutes:
            return f"[{minutes}m{seconds:02d}s]"
        return f"[{seconds}s]"

    def process_line(self, raw: str) -> list[str]:
        raw = raw.strip()
        if not raw:
            return []
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return []

        typ = obj.get("type")
        ts = self._elapsed()

        if typ == "thread.started":
            thread_id = obj.get("thread_id", "unknown")
            return [f"{ts} [init] Thread started ({thread_id[:12]}…)"]

        if typ == "turn.started":
            return [f"{ts} [turn] Started"]

        if typ == "item.started":
            item = obj.get("item", {})
            item_type = item.get("type")
            item_id = item.get("id", "")
            if item_type == "command_execution":
                command = item.get("command", "")
                desc = _command_description(command)
                self.pending_commands[item_id] = desc
                return [f"{ts} [exec] {desc}"]
            return []

        if typ == "item.completed":
            item = obj.get("item", {})
            item_type = item.get("type")
            item_id = item.get("id", "")

            if item_type == "command_execution":
                exit_code = item.get("exit_code")
                command = item.get("command", "")
                desc = self.pending_commands.pop(item_id, _command_description(command))
                status = "ok" if exit_code == 0 else f"exit {exit_code}"
                return [f"{ts} [exec done] {desc} ({status})"]

            if item_type == "agent_message":
                text = item.get("text", "")
                return [f"{ts} [message] {_truncate(text)}"]

            return []

        if typ == "turn.completed":
            usage = obj.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            return [f"{ts} [turn done] tokens: {input_tokens} in / {output_tokens} out"]

        return []


class ExecResult:
    """Parsed result from a codex exec JSONL stream."""
    def __init__(self):
        self.messages: list[str] = []
        self.thread_id: str | None = None
        self.is_error: bool = False
        self.input_tokens: int = 0
        self.output_tokens: int = 0


def _extract_result(lines: list[str]) -> ExecResult:
    """Parse collected JSONL lines into an ExecResult."""
    result = ExecResult()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        typ = obj.get("type")

        if typ == "thread.started":
            result.thread_id = obj.get("thread_id")

        elif typ == "item.completed":
            item = obj.get("item", {})
            if item.get("type") == "agent_message":
                text = item.get("text", "")
                if text:
                    result.messages.append(text)
            elif item.get("type") == "command_execution":
                if item.get("exit_code") not in (0, None):
                    result.is_error = True

        elif typ == "turn.completed":
            usage = obj.get("usage", {})
            result.input_tokens += usage.get("input_tokens", 0)
            result.output_tokens += usage.get("output_tokens", 0)

    return result


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

def _kill_process(pid: int) -> None:
    """Send SIGTERM to a process, then SIGKILL after 5s if still alive."""
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


def _build_cmd(args) -> list[str]:
    """Build the codex exec command."""
    cmd = [
        "codex", "exec",
        "--model", args.model,
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
    ]
    if args.cd:
        cmd.extend(["--cd", args.cd])
    return cmd


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    # Remove CLAUDECODE to avoid interference if running inside a Claude session
    env.pop("CLAUDECODE", None)
    return env


def _read_prompt(args) -> str:
    """Read the prompt from --prompt-file or stdin."""
    if args.prompt_file:
        prompt_file = Path(args.prompt_file)
        if not prompt_file.exists():
            print(f"Error: prompt file not found: {prompt_file}", file=sys.stderr)
            sys.exit(1)
        return prompt_file.read_text()

    if sys.stdin.isatty():
        print("Error: no prompt provided. Use --prompt-file or pipe via stdin.", file=sys.stderr)
        sys.exit(1)
    return sys.stdin.read()


def _run(cmd: list[str], timeout: int, prompt: str) -> tuple[int, ExecResult]:
    """Run codex exec, pipe prompt via stdin, parse JSONL output.

    Streams progress to stderr and returns (returncode, ExecResult).
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_build_env(),
    )

    # Send prompt via stdin and close
    proc.stdin.write(prompt)
    proc.stdin.close()

    processor = StreamProcessor()
    collected_lines: list[str] = []
    deadline = time.monotonic() + timeout

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)

            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break  # EOF

                collected_lines.append(line)

                for progress_line in processor.process_line(line):
                    print(progress_line, file=sys.stderr, flush=True)

            elif proc.poll() is not None:
                # Process exited, drain remaining output
                for line in proc.stdout:
                    collected_lines.append(line)
                    for progress_line in processor.process_line(line):
                        print(progress_line, file=sys.stderr, flush=True)
                break
    except subprocess.TimeoutExpired:
        _kill_process(proc.pid)
        proc.wait()
        raise
    except KeyboardInterrupt:
        _kill_process(proc.pid)
        proc.wait()
        raise

    proc.wait()
    result = _extract_result(collected_lines)
    return proc.returncode, result


def _write_response(result: ExecResult, response_file: str | None) -> None:
    """Write the agent's response to --response-file or stdout."""
    text = "\n\n".join(result.messages)
    if response_file:
        Path(response_file).write_text(text)
    else:
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run codex exec and parse JSONL output"
    )
    parser.add_argument("--prompt-file", help="Path to prompt file (reads stdin if omitted)")
    parser.add_argument("--response-file", help="Write response to this file (stdout if omitted)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--cd", help="Working directory for codex")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds (default: 600)")
    args = parser.parse_args()

    prompt = _read_prompt(args)
    cmd = _build_cmd(args)

    t0 = time.monotonic()
    try:
        returncode, result = _run(cmd, args.timeout, prompt)
    except subprocess.TimeoutExpired:
        print(f"Error: timed out after {args.timeout}s", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

    duration_ms = int((time.monotonic() - t0) * 1000)
    print(
        f"[done] {_format_duration(duration_ms)}, "
        f"{result.input_tokens} in / {result.output_tokens} out",
        file=sys.stderr,
    )

    if returncode != 0:
        print(f"Error: codex exited with code {returncode}", file=sys.stderr)
        if result.messages:
            _write_response(result, args.response_file)
        sys.exit(1)

    _write_response(result, args.response_file)


if __name__ == "__main__":
    main()
