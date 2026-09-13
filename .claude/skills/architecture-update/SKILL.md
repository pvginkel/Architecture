---
name: architecture-update
description: Run the central architecture update over the producer fleet from the Architecture repo. `tooling/fleet.py update` takes every registered producer that has commits past its watermark through a triage session and, unless triage says skip, an update session in a staged clone, pushes what the session commits, tracks the builds the push starts, and writes one report to the specs repo. Use when the operator asks to update the fleet's architecture, refresh the producers' architecture artifacts, run the central/fleet architecture update, or do the same for one named producer.
---

# architecture-update

Start `tooling/fleet.py update`, wait for it, and send the one notification the
operator gets. The tool does the work; this skill is the wrapper around it.

## Run it

From `/work/Architecture`, with `JENKINS_TOKEN` set in the environment — without
it every producer with commits fails before its push:

```bash
mkdir -p /tmp/architecture-update
LOG=/tmp/architecture-update/$(date +%Y-%m-%dT%H%M).log
timeout --signal=INT --kill-after=2m 12h \
  python3 tooling/fleet.py update > "$LOG" 2>&1
```

Start it **in the background** and end your turn: it re-invokes you when it
exits. Don't tail the log, don't poll it, don't re-run it to see how far it got.
A whole-fleet run takes hours.

- `--signal=INT` is what makes a killed run safe. On SIGINT the tool ends the
  headless session it is driving from a `finally`; SIGTERM would skip that and
  leave a session running.
- `12h` is the cap for the whole fleet — 30 producers, the tool's own timeouts
  being 600 s per triage session and 3600 s per update session.
- Name producer ids to take only those: `python3 tooling/fleet.py update newsfilter`.
- The tool reports every producer as it finishes and records its state then, so
  a run that is killed keeps what it has done; the next run picks up from there.

## Notify when it exits

A run that got to the end closes its log with

```
report: /work/ArchitectureSpecs/architecture-updates/<YYYY-MM-DD>T<HHMM>.md
unresolved: <n>
judgment calls: <m>
```

Read those three lines, then send **one** message with the `notification` MCP
tool and stop. `<n>` counts what failed; `<m>` counts what the update sessions
deliberately left for the operator (their `Skipped:` lines), which never
affects the exit code. What the message says, by exit code:

| Exit | Message |
|---|---|
| 0 | the run finished, the report path, nothing unresolved, `<m>` judgment calls to read |
| 1 | the run finished, the report path, `<n>` unresolved items waiting for the operator, `<m>` judgment calls |
| 4 | the run finished but its report is **not in the specs repo**: the report path on disk, both counts, and the log's last line, which says why the commit or push failed |
| 124 | the run was **killed** at the timeout, not finished: the log path, and that every producer it finished kept its state |
| other | the tool did not run: the log path and the last line of the log |

Don't summarise the report in the message — the operator reads it himself.
