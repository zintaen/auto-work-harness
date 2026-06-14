#!/usr/bin/env python3
"""A deliberately flaky system-under-test for demoing the multi-seed eval runner.

It passes (exit 0) on a fixed fraction of seeds, so a single run looks fine but
pass^k reveals the inconsistency — exactly the failure the harness is built to
catch. Seed comes from $AWH_SEED (set by the runner).

    AWH_SEED=1 python3 examples/flaky_solver.py   # pass
    AWH_SEED=4 python3 examples/flaky_solver.py   # fail (seed % 4 == 0)
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    seed = int(os.environ.get("AWH_SEED", "0"))
    # passes on 3 of every 4 seeds
    return 0 if seed % 4 else 1


if __name__ == "__main__":
    sys.exit(main())
