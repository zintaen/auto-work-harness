# auto-work-harness

Verification, measurement, and orchestration hardening for autonomous coding
agents — a working, tested implementation of the **Stage 0 → 3 roadmap** in
*Pushing Autonomous Coding Agents Further (2025–2026)*.

It is built to wrap an existing single-agent unattended setup (e.g. `AUTO_WORK.md`
+ `agent_handoff.py`) and upgrade its "evidence gate" from a prompt-enforced
convention into **structurally enforced infrastructure** — because the strongest
empirical finding in the field is that environment-level controls cut reward
hacking and silent failure far more reliably than any prompt.

> Design principle (Anthropic, 2026): *"Design for containment at the environment
> layer first, then steer behavior at the model layer."*

Status: **195 tests passing, ruff-clean.** Pure standard library at the core (no
numpy/scipy) so it runs anywhere the agent runs. See `ROADMAP_MAPPING.md` for the
component-by-component trace to the source recommendations.

## The four stages

**Stage 0 — deterministic gates & containment** (`harness/stage0_verification/`, `sandbox/`)
A PreToolUse **deny** engine (destructive commands, secret reads, read-only test
edits), a Stop/SubagentStop **evidence gate** that reruns your suite and refuses
to end the turn while it's red, OS-level **read-only test/scoring** locking, and a
**default-deny egress** sandbox (devcontainer + iptables, macOS Seatbelt, an
allowlist proxy that holds the token so the agent never sees a key).

**Stage 1 — the measurement pillar** (`harness/common/stats.py`, `harness/stage1_measurement/`)
Trustworthy `pass@k` / `pass^k` / Wilson-interval / power-analysis math, a YAML
**golden set**, a **multi-seed** runner, and a **block-on-regression** gate
(regression vs. baseline, never an absolute threshold).

**Stage 2 — structural verification depth** (`harness/stage2_structural/`)
A single-call **LLM-as-judge verifier** (rubric, 0–1 + pass/fail, fresh-context
backend, fail-closed), a **60/30/10** deterministic/judge/human scorer mix,
property-based tests (Hypothesis), and a dependency-free **mutation tester** that
catches tautological tests.

**Stage 3 — selective parallelism** (`harness/stage3_parallel/`)
A **git worktree-per-task** manager (collision guard, clean conflict-abort,
per-worktree isolation) and a **planner → parallel workers → verifier → serialized
merge** pipeline. Writes never go agent-to-agent; the orchestrator merges.

## Install

```bash
make install          # pip install -e ".[dev]"  (pytest, hypothesis, ruff)
make verify           # ruff + full test suite  (this is the AUTO_WORK gate)
```

## Try each stage

```bash
# Stage 0 — lock tests read-only + render the egress firewall
python3 -m harness.cli lock . --write-policy
python3 -m harness.cli firewall --out sandbox/devcontainer/init-firewall.sh

# Stage 1 — multi-seed eval + how many seeds you actually need
python3 -m harness.cli eval harness/goldenset/tasks/example_tasks.yaml --seeds 8
python3 -m harness.cli power --baseline 0.5 --mde 0.015     # the SWE-bench noise floor

# Stage 2 — mutation score for a suite
python3 scripts/mutation_demo.py

# Stage 3 — isolated worktrees
python3 -m harness.cli worktree create --repo . --task-id feature-x
```

## Wiring into AUTO_WORK

1. `./install.sh /path/to/your/project` writes a Claude Code `settings.json` that
   fires the Stage-0 hooks, plus a `.awh/gate.sh` stub.
2. Edit `.awh/gate.sh` to run that project's real `test + lint + typecheck`. The
   Stop hook runs it and **blocks the agent from stopping** until it's green —
   the structural version of AUTO_WORK's "EVIDENCE, NOT CONFIDENCE" rule.
3. Set `AWH_GATE_CMD="make verify"` (or your command) in the agent's environment;
   the devcontainer in `sandbox/` does this and applies default-deny egress so an
   unattended `--dangerously-skip-permissions` run is actually safe.
4. In CI, the golden-set **eval gate** blocks merges on regression vs. baseline.

## Repository layout

```
harness/
  common/stats.py            pass@k, pass^k, Wilson CI, power analysis
  stage0_verification/       policy, hooks/, readonly, egress, settings template
  stage1_measurement/        goldenset, runner (pass@k report + gate), promptfoo/
  stage2_structural/         verifier, scorermix, mutation
  stage3_parallel/           worktree, pipeline
  goldenset/tasks/           example golden set (replace with your own)
  cli.py                     `awh` entry point
sandbox/                     devcontainer + iptables, Seatbelt profile, egress proxy
scripts/mutation_demo.py     end-to-end mutation demonstration (used by CI)
tests/                       195 tests (unit, Hypothesis PBT, real-repo git tests)
```

## Caveats (carried from the survey)

- Same-uid `chmod` read-only is a **speed bump**, not a security boundary; the hard
  guarantee is the read-only bind mount / different uid in `sandbox/`.
- A **permitted domain can still exfiltrate** (Anthropic saw it); keep the egress
  allowlist minimal and watch credentialed egress to allowed hosts.
- **Egress proxies need real review** — a SOCKS5 bypass lived in Claude Code's proxy
  for ~5.5 months; the bundled proxy matches hosts exactly and is unit-tested for it.
- Several cited tools are fast-moving; pin versions before standardizing.
