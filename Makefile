# auto-work-harness — developer + gate targets.
# `make verify` is the AUTO_WORK evidence gate (wire it via AWH_GATE_CMD).
PY ?= python3
export PYTHONPATH := .

.PHONY: install lint format format-check security test pbt eval mutation verify all ci clean

install:
	$(PY) -m pip install --break-system-packages -e ".[dev]"

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

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
	$(PY) -m ruff format --check .

# Stage 0 dogfood: scan our own source with bandit (config in pyproject [tool.bandit]).
security:
	$(PY) -m bandit -c pyproject.toml -r harness sandbox scripts -q

# The evidence gate: structure-first, fast, deterministic.
# Includes format-check so a format drift can't slip through to the eval gate.
verify: lint format-check test

all: verify eval mutation

ci: verify
	$(PY) scripts/mutation_demo.py

# Remove ALL regenerable artifacts (caches, build, bytecode, OS cruft).
# Uses `find` so __pycache__ is cleaned recursively (a plain **/ glob misses nested dirs).
clean:
	rm -rf .pytest_cache .ruff_cache .hypothesis .mypy_cache eval-runs *.evalreport.json
	rm -rf .coverage .coverage.* *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
	find . -name .DS_Store -delete 2>/dev/null || true
