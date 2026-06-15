#!/usr/bin/env sh
# Stage-0 evidence gate for auto-work-harness (dogfooded on itself).
# The Stop/SubagentStop hook runs this and BLOCKS turn-end on a non-zero exit.
set -e
echo "[awh-gate] make verify (ruff + full pytest suite)…"
make verify
