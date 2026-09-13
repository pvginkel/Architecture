# The central architecture update

A producer repo drifts: it grows a queue, drops a service, changes what it consumes — and its
`docs/architecture/*.yaml` quietly stops describing it. The central architecture update is how that
drift is found and repaired. One tool in this repo, `tooling/fleet.py`, run on demand from the
Architecture environment, takes each registered producer through a judgement and, where the
judgement calls for it, an editing session in a throwaway clone; it pushes what the session commits,
follows the builds the push starts, and writes one report to the specs repo.

Nothing is installed into any `~/.claude/` and no producer repo is asked to invoke anything. The
producer-side kit lives under this repo's `.claude/` and is copied into each clone per run.

## The pieces

| Path | What it is |
| --- | --- |
| `tooling/fleet.py` | the tool: `scan`, `stage <Repo>`, `update [<id>…]` |
| `.claude/agents/triage-architecture.md` | the fast-path judge (Sonnet, 600 s): does anything in the range change what the architecture must say? |
| `.claude/agents/update-architecture.md` | the editor (Opus, `xhigh`, 3600 s): applies the deltas and commits. One agent — hand-authored and generated mode come from the caller's prompt |
| `.claude/skills/seed-architecture/SKILL.md` | first-version authoring, for a repo that has no artifact yet |
| `.claude/architecture/` | `producer-manual.md` (the vocabulary the agents read on startup), `architecture.yaml` (the starter skeleton), `arch-validate.py` (the only copy) |
| `.claude/skills/architecture-update/SKILL.md` | the operator's entry point here: runs the tool and sends the one notification |
| `pipeline-producers.yaml` | the registry — which producers exist, which GitHub repo each one is, and which Jenkins job builds its artifact |

The **kit** is `.claude/agents/`, `.claude/skills/seed-architecture/` and `.claude/architecture/`
(`KIT_DIRS` in `fleet.py`). The `architecture-update` skill drives the fleet from here and is
deliberately not part of it.

## The producer's half of the contract

- **`repo:` in `pipeline-producers.yaml`** — GitHub `owner/name`, closed-schema and checked by
  `collect.py` at startup. A producer without one is *not fleet-managed* and the tool never touches
  it; today that is only `home-automation-fleet`, whose artifact a scheduled job generates from the
  live Home Assistant state rather than from sources in a repo.
- **`jenkinsJob:`** — the job that builds and archives the artifact, which every producer has. After
  a push the tool tracks it first; a push that does not start it (no push trigger, or disabled)
  leaves the producer unresolved with that said, because a run cannot otherwise tell a
  verified-green producer from one whose artifact build was never followed. This repo is a producer
  too — `architecture`, marked `self: true` — and its job is the `AaC/Architecture` pipeline itself,
  which the Jenkinsfile therefore copies locally rather than from an archive and leaves out of its
  own upstream triggers; the tool tracks it after a push like any other.
- **`.architecturerc` at the repo root** — optional. `generated` (default `false`), `sources` (git
  pathspecs, default `:(glob)**/docs/architecture/**`) and `instructions` (free text handed verbatim
  to both sessions, and authoritative over the agents' own files on anything specific to that repo).
  The file is read from the remote head without a checkout; an unknown key, a wrong type or
  unparseable YAML fails that producer instead of being worked around.

- **`gap:` lines, for a generated producer.** Its generator prints each thing it could not map on a
  console line of its own, `gap: <what>`, in the `jenkinsJob` build, and the build stays green.
  HelmCharts' `gen_architecture.py` does this, for an image no annotation maps, for instance. The
  tool reads the lines from that job's last successful build.

A hand-authored producer is cross-checked before any session: the first YAML among its sources that
carries a top-level `producer:` must name the registry id. A wrong `repo:` therefore surfaces as a
failed producer, not as an update session editing another repo's artifact.

The producer-facing statement of the same contract is the manual's *Staying current* section and
[`USAGE.md`](../USAGE.md)'s *Keeping an artifact current*; a change to `.architecturerc`'s shape
moves all three.

## What a run does, per producer

`update` walks the registry in order — or just the ids named on the command line — one producer at
a time:

1. **Clone.** `/tmp/architecture-update/repos/<Repo>`, blob-less, fetched when it is already there,
   checked out at `origin/HEAD`. A clone holding uncommitted changes or unpushed commits is refused
   rather than reset: checking out `origin/HEAD` would throw that work away.
2. **Stage the kit.** The kit's files are copied into the clone's `.claude/` and listed in
   `.git/info/exclude`, so the clone stays clean and no staged file can end up in a session's
   commit. A repo that tracks its own file at a kit path with different content is refused before
   anything is copied — a producer's own agent is never overwritten. (This repo is a producer too,
   and what gets staged is this checkout's `.claude/` on disk, not what it has pushed: an
   uncommitted or unpushed kit edit refuses producer `architecture` until it is pushed.)
3. **Pick the base, read the gaps.** The watermark is the last commit that touched the sources at
   `origin/HEAD`; the base is the later of that and the producer's `reviewed` commit in the state
   file. A generated producer's gaps are the `gap:` lines of its `jenkinsJob`'s last successful
   build. A gap is new when the state file does not list it. A base equal to the head with no new
   gap means *current*: nothing to judge, no session.
4. **Triage.** A `triage-architecture` session answers `VERDICT: update` or `VERDICT: skip` with one
   line of reason. `skip` ends the producer and advances `reviewed` to the head; an answer that
   cannot be parsed counts as `update`, so a confused judge costs a session rather than a miss. A
   new gap skips triage: there is something to model whatever the commits say.
5. **Update.** An `update-architecture` session applies the deltas and commits per the repo's
   cadence — it never pushes. It is handed every gap the build reports, each in scope whatever the
   range, so a gap that predates the base is not left behind. It ends with a two-line handoff: what
   it applied, and what it deliberately skipped. A session that leaves the clone dirty, ends
   without its handoff, or reports that it stopped, fails that producer.
6. **Push and track**, below.

Both sessions are headless `kc` sessions driven as the dev plugin's `run_kc_session` drives them:
`create-headless` in the clone with the staged agent, `send` under the timeout this tool enforces
(SIGINT, then a kill 15 s later), `status` for the session id, and `end` from a `finally`. A missing
agent definition stops the producer before dispatch, because `create-headless --agent` with an
unknown name starts a plain session instead of failing.

## The push, the builds and the fix rounds

The session's commits are pushed to the repo's default branch, and every job the push starts is
followed to its end with `track_build.py <job> --hash <sha>`, which follows the downstream chain
too. The tracker's own default of 30 s for how long it waits for the build to appear is far too
short under a loaded queue, so the tool passes `--appear-timeout APPEAR_TIMEOUT` instead; and
since the tracker then polls for completion without a deadline, the call is bounded by
`TRACK_TIMEOUT`, a tracker killed at it being operational like any other that could not finish.
Without that bound one build that never completes parks the whole sequential run.

Which jobs those are is decided once per run from Jenkins' REST API: every enabled job whose SCM
checks out the repo and which carries a GitHub push trigger, the registry's `jenkinsJob` first. A
timer-driven, hand-run or disabled job on the same repo is left out on purpose — it will never build
the pushed commit, and the tracker would wait for a build that never appears. When the job left out
is the registry's own, the producer is unresolved: its commits are pushed all the same, but its
artifact build went unverified and the report says so.

Attribution is per build, by that build's own job. The tracker follows a chain — the tracked job's
build and every build it started downstream, `IaC/HelmCharts` for most of the fleet — and a failed
build anywhere in it is compared with its own job's last completed result before this producer's
first build of that job in the run, read from Jenkins' build history and remembered across the fix
rounds. Green before and red now is the update's doing: the tool resumes the same update session
(`--resume`) with those builds, their jobs and console logs, and the rule "assume your commits broke
it; fix, commit, do not push", then pushes and tracks again — two rounds at most. Red before is
recorded as pre-existing and left alone, a job with no completed build before is reported as such,
and a tracker that could not finish — or a prior result the tool could not read — is operational.
All are unresolved, none is fixed here.

Before the first producer, the run reads the last completed result of every job it would track for
the producers it is about to run, and of every job those builds started (off their console logs, as
the tracker discovers downstream). Any red stops the run with exit 3 and the list — before anything
is cloned or pushed — so the operator can run a fixup session first; `--force` runs anyway, and the
report's header records what was red. The accepted trade-off is that one red build anywhere the
fleet's pushes reach blocks the run until it is fixed or forced. Without the check a downstream job
that was already red would exit the tracker 1 for a producer whose own job was green, and the update
would be blamed, fix-rounded twice and its session's guesses pushed to the producer repo.

Jenkins is `$JENKINS_URL` as `$JENKINS_USER`, defaulting in the tool's own constants exactly as
`track_build.py` does. `$JENKINS_TOKEN` is the only credential and must be in the environment —
without it the tool cannot read Jenkins, and the run stops at that check before the first producer.

`reviewed` advances to the pushed commit.

## The report and the state

Both live in the specs repo (`spec_repo` in `.aiworkflowrc`), under `architecture-updates/`:

- **`state.yaml`** — one entry per fleet-managed producer: `reviewed` (the commit its architecture
  was last judged at), `gaps` (the gaps its build reported then, absent while there are none),
  `date` and `outcome`. The gaps advance only with `reviewed`. That is what keeps a gap no session
  can close from costing a session every run: it is looked at again only when triage sends new
  commits to an update. The file is rewritten as each producer finishes, so a run that is killed
  keeps every producer it got through and the next run resumes from there.
- **`<YYYY-MM-DD>T<HHMM>.md`** — one per run: a section per producer (repo, triage verdict, the gaps
  its build reports, handoff, the commits and the commit they were pushed as, each tracked job's
  result with its builds and the log of a failed one, a block per fix round), then **Judgment
  calls**, closing with **Unresolved**.

Unresolved is the run's product and what decides the exit code — 0 when it is empty, 1 otherwise:
a failed producer, a red build, a session that did not finish. Exit 1 means something actually
failed. The sessions' own `Skipped:` judgement calls — what an agent deliberately left for a human —
sit in their own section, counted on the run's closing `judgment calls:` line, and do not touch the
exit code. The tool stages and commits the two paths **by name**, the specs repo's working tree
being shared with the dev pipeline, and pushes.

## Running it

The operator's entry point is the `architecture-update` skill: it starts `fleet.py update` in the
background under `timeout --signal=INT --kill-after=2m 12h` and, when the run exits, sends one
`notification` message by exit code: 0 or 1, the report path and the unresolved and judgment-call
counts; 3, that the run did not start because Jenkins was red before it (or could not be read) and
which jobs; 4, that the report is on disk but could not be committed and pushed to the specs repo;
124, that the run was killed rather than finished. SIGINT rather than SIGTERM is what lets the tool
end the headless session it is driving.

The tool itself is plain `python3`: the standard library and PyYAML only, so it runs in the dev
container without the Poetry environment. (Its tests run under Poetry, with the rest of tooling's
suite.)

```bash
python3 tooling/fleet.py scan                 # every producer: stale (with a count), current,
                                              # not fleet-managed, or failed with the reason
python3 tooling/fleet.py stage NewsFilter     # clone or fetch one repo and stage the kit; no session
python3 tooling/fleet.py update newsfilter    # one producer, end to end
```

`scan` starts no session and writes nothing outside the clones, so it is both the way to see what a
full run would do and the way a misconfiguration — a wrong `repo:`, a malformed `.architecturerc`, a
clone with local work — surfaces without spending a session on it. It reads a generated producer's
gaps from Jenkins, so it needs `$JENKINS_TOKEN` just as `update` does.

## Changing the kit

Edit the files under `.claude/` and commit; the next run stages that copy. There is no install step,
no snapshot and no version to keep in sync — which is the point of having no plugin. Two things hold
it together:

- The agents and the skill reference the manual and the validator as `.claude/architecture/…`, which
  is where they sit in a clone as well as here.
- `arch-validate.py` exists once, at `.claude/architecture/arch-validate.py`. The image's
  `build-service` stage copies it from there for `service/test/arch-validate.test.ts`, and
  `Jenkinsfile.ha-fleet` calls it; producer repos keep their own copy at `scripts/arch-validate.py`
  for their CI to call, re-copied from here when it changes.

A change to the schema, the enums or what a valid `architecture.yaml` looks like changes what
producers must write, and so what the manual and the skeleton say —
[`slice-doc-plan.md`](slice-doc-plan.md) has that obligation.
