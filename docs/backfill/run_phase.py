#!/usr/bin/env python3
"""Run a backfill phase: seed every producer in that phase concurrently
(capped), each via seed_repo.py in its cloned repo. One background task → one
completion notification for the whole phase.

Usage: run_phase.py B --max 4 --timeout 3600
"""

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # repo root
sys.path.insert(0, str(HERE))
from gen_prompts import PRODUCERS  # noqa: E402

SEED = HERE / "seed_repo.py"


def run_one(p: dict, timeout: int) -> tuple[str, int]:
    name = p["producer"]
    repo_dir = ROOT / "tmp" / "backfill" / p["clone_dir"]
    prompt = HERE / "prompts" / f"{name}.md"
    if not repo_dir.is_dir():
        print(f"SKIP {name}: clone missing ({repo_dir})", flush=True)
        return name, 99
    if not prompt.is_file():
        print(f"SKIP {name}: prompt missing ({prompt})", flush=True)
        return name, 98
    print(f"START {name}", flush=True)
    proc = subprocess.run(
        [str(SEED), "start", "--name", name, "--repo-dir", str(repo_dir),
         "--prompt-file", str(prompt), "--timeout", str(timeout)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    tail = (proc.stdout.strip().splitlines() or proc.stderr.strip().splitlines() or [""])[-1]
    print(f"{'DONE' if proc.returncode == 0 else 'FAIL'} {name} (rc={proc.returncode}) {tail}", flush=True)
    return name, proc.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["A", "B", "C"])
    ap.add_argument("--max", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    todo = [p for p in PRODUCERS if p["phase"] == args.phase]
    print(f"Phase {args.phase}: {len(todo)} producers, max {args.max} concurrent", flush=True)
    results = {}
    with ThreadPoolExecutor(max_workers=args.max) as ex:
        futs = {ex.submit(run_one, p, args.timeout): p["producer"] for p in todo}
        for f in as_completed(futs):
            name, rc = f.result()
            results[name] = rc

    ok = [n for n, rc in results.items() if rc == 0]
    bad = [f"{n}(rc={rc})" for n, rc in results.items() if rc != 0]
    print(f"\nPhase {args.phase} complete: {len(ok)} OK, {len(bad)} failed.", flush=True)
    if bad:
        print("Failed: " + ", ".join(bad), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
