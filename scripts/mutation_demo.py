#!/usr/bin/env python3
"""Demonstrate the Stage-2 mutation tester end to end (used by `make mutation`/CI).

Builds a tiny real module + a STRONG test in a temp dir, runs the mutate-run-restore
loop, and asserts the suite kills 100% of mutants. Exits non-zero if any mutant
survives — i.e. if the demo test suite were weak. Proves the tester works against
real subprocess execution, complementing the unit tests.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# make `harness` importable when run as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.stage2_structural.mutation import run_mutation  # noqa: E402

MODULE = """
def classify(x):
    if x < 0:
        return "neg"
    if x == 0:
        return "zero"
    return "pos"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
"""

STRONG_TEST = """
from m import classify, clamp
assert classify(-3) == "neg"
assert classify(0) == "zero"
assert classify(5) == "pos"
assert clamp(5, 0, 10) == 5
assert clamp(-1, 0, 10) == 0
assert clamp(99, 0, 10) == 10
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "m.py").write_text(MODULE)
        (root / "t.py").write_text(STRONG_TEST)
        # sys.executable, not a literal "python3", so the demo works wherever it runs.
        report = run_mutation(root / "m.py", f"{sys.executable} -B t.py", workdir=root)
        print(report.summary())
        if report.score < 1.0:
            print("FAIL: surviving mutants => the test suite is weak.", file=sys.stderr)
            return 1
        print(f"OK: strong suite killed all {report.total} mutants.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
