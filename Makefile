# auto-work-harness — developer + gate targets.
# `make verify` is the AUTO_WORK evidence gate (wire it via AWH_GATE_CMD).
PY ?= python3
export PYTHONPATH := .

.PHONY: install lint format format-check test pbt eval mutation verify all ci clean

install:
	$(PY) -m pip install --break-system-packages -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .

test:
	$(PY) -m pytest

pbt:
	$(PY) -m pytest tests/test_stage2_pbt.py -q

# Stage 1: run the example golden set multi-seed and print pass@k/pass^k.
eval:
	$(PY) -m harness.cli eval harness/goldenset/tasks/example_tasks.yaml --seeds 8 --label make-eval

# Stage 2: demonstrate the mutation tester on a real temp module (score must be 100%).
mutation:
	$(PY) scripts/mutation_demo.py

format-check:
	ruff format --check .

# The evidence gate: structure-first, fast, deterministic.
# Includes format-check so a format drift can't slip through to the eval gate.
verify: lint format-check test

all: verify eval mutation

ci: verify
	$(PY) scripts/mutation_demo.py

clean:
	rm -rf .pytest_cache .ruff_cache .hypothesis **/__pycache__ eval-runs *.evalreport.json
