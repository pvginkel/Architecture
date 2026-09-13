---
name: architecture-update
description: Run the central architecture update over the producer fleet from the Architecture repo. `tooling/fleet.py update` takes every registered producer that has commits past its watermark through a triage session and, unless triage says skip, an update session in a staged clone (a generated producer whose AaC build reports a gap no run has judged goes straight to the update session), pushes what the session commits, tracks the builds the push starts, and writes one report to the specs repo. Use when the operator asks to update the fleet's architecture, refresh the producers' architecture artifacts, run the central/fleet architecture update, or do the same for one named producer.
---

# architecture-update

Start `tooling/fleet.py update`, wait for it, and send the one notification the
operator gets. The tool does the work; this skill is the wrapper around it.

## Run it

From `/work/Architecture`, with `JENKINS_TOKEN` set in the environment — without
it the tool cannot read Jenkins and stops before the first producer (exit 3):

```bash
mkdir -p /tmp/architecture-update
LOG=/tmp/architecture-update/$(date +%Y-%m-%dT%H%M).log
timeout --signal=INT --kill-after=2m 12h \
  python3 tooling/fleet.py update > "$LOG" 2>&1
```

Start it **in the background** and end your turn: it re-invokes you when it
exits. Don't tail the log, don't poll it, don't re-run it to see how far it got.
A whole-fleet run takes from half an hour, when nearly every producer skips at
triage, to hours when many of them update.

- `--signal=INT` is what makes a killed run safe. On SIGINT the tool ends the
  headless session it is driving from a `finally`; SIGTERM would skip that and
  leave a session running.
- `12h` is the cap for the whole fleet, and it is a backstop, not a budget. The
  tool's own timeouts (600 s per triage session, 3600 s per update session)
  would allow some 35 h over 30 producers; what a sweep actually costs, measured,
  is about 50 s per producer that skips and about 10 min per producer that
  updates, push and build tracking included, so a run reaches 12 h only when it
  is stuck.
- Name producer ids to take only those: `python3 tooling/fleet.py update newsfilter`.
- Before the first producer the tool checks that every job it would track,
  and every job those jobs' last builds started, is green; any red stops it
  with exit 3 and the list. `--force` runs anyway — pass it only when the
  operator asks for it after seeing that list, never on your own.
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
| 3 | the run did **not start**: Jenkins was red before it (the log lists each red job, with the tracked job that started it) or could not be read; nothing was cloned or pushed. The operator fixes the builds first, or asks for a run with `--force` |
| 4 | the run finished but its report is **not in the specs repo**: the report path on disk, both counts, and the log's last line, which says why the commit or push failed |
| 124 | the run was **killed** at the timeout, not finished: the log path, and that every producer it finished kept its state |
| other | the tool did not run: the log path and the last line of the log |

Don't summarise the report in the message — the operator reads it himself.
