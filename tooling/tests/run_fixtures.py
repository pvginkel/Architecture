"""Drive collect.py against every fixture under tests/fixtures/.

Each fixture is a directory containing:
    producers.yaml             (the registry)
    producer-artifacts/<id>/architecture.yaml ...   (the inputs)
    expected.yaml              (assertion config, see below)
    expected-dist/             (golden outputs, only for happy-path fixtures)

expected.yaml shape:
    exit_code: 0 | 1
    phase: <collector phase that should fail>     # only when exit_code != 0
    golden_dir: ./expected-dist                   # only when exit_code == 0;
                                                  # compare byte-for-byte

Exits 0 if every fixture matches its expectation, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
COLLECT = HERE.parent / "collect.py"
FIXTURES = HERE / "fixtures"


def run_fixture(fixture_dir: Path) -> tuple[bool, list[str]]:
    """Run the collector against `fixture_dir`. Return (passed, lines)."""
    expected = yaml.safe_load((fixture_dir / "expected.yaml").read_text())
    producers = fixture_dir / "producers.yaml"
    artifacts = fixture_dir / "producer-artifacts"

    with tempfile.TemporaryDirectory() as out_dir:
        out_path = Path(out_dir)
        proc = subprocess.run(
            [
                sys.executable,
                str(COLLECT),
                "--producers", str(producers),
                "--in", str(artifacts),
                "--out", str(out_path),
            ],
            capture_output=True,
            text=True,
        )
        lines: list[str] = [f"{fixture_dir.name}: exit={proc.returncode}"]

        exp_code = int(expected["exit_code"])
        if proc.returncode != exp_code:
            lines.append(f"  expected exit {exp_code}, got {proc.returncode}")
            lines.append(f"  --- stdout ---\n{proc.stdout}")
            lines.append(f"  --- stderr ---\n{proc.stderr}")
            return False, lines

        if exp_code != 0:
            phase = expected.get("phase")
            if phase and f"[{phase}]" not in proc.stderr:
                lines.append(f"  expected stderr to contain phase '[{phase}]'")
                lines.append(f"  --- stderr ---\n{proc.stderr}")
                return False, lines
            lines.append(f"  failed in phase '{phase}' as expected")
            return True, lines

        # exit_code == 0 → compare against golden if provided
        golden_dir = expected.get("golden_dir")
        if golden_dir:
            golden = (fixture_dir / golden_dir).resolve()
            actual = (out_path / "data" / "v0.1").resolve()
            diffs: list[str] = []
            for golden_file in sorted(golden.iterdir()):
                actual_file = actual / golden_file.name
                if not actual_file.exists():
                    diffs.append(f"missing output: {golden_file.name}")
                    continue
                gtext = golden_file.read_text()
                atext = actual_file.read_text()
                if gtext != atext:
                    diffs.append(f"diff in {golden_file.name}")
            if diffs:
                lines.extend(f"  {d}" for d in diffs)
                return False, lines
            lines.append(f"  golden output matches ({len(list(golden.iterdir()))} file(s))")
        else:
            lines.append("  succeeded as expected")
        return True, lines


def main() -> int:
    fixtures = sorted([d for d in FIXTURES.iterdir() if d.is_dir()])
    if not fixtures:
        print(f"no fixtures under {FIXTURES}", file=sys.stderr)
        return 1

    failed = 0
    for fixture in fixtures:
        passed, lines = run_fixture(fixture)
        marker = "PASS" if passed else "FAIL"
        for i, line in enumerate(lines):
            prefix = f"{marker} " if i == 0 else "     "
            print(prefix + line)
        if not passed:
            failed += 1

    if failed:
        print(f"\n{failed}/{len(fixtures)} fixture(s) failed", file=sys.stderr)
        return 1
    print(f"\nAll {len(fixtures)} fixture(s) passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
