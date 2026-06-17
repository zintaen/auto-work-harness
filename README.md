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

Status: **290 tests passing, ruff-clean.** The Stage-0 policy and egress gates have
been through a dedicated security/edge-case audit (path-normalization and redirect
bypasses, command-injection in the rendered firewall, fail-safe policy parsing) — see
`tests/test_audit_hardening.py`. Pure standard library at the core (no
numpy/scipy) so it runs anywhere the agent runs. See `ROADMAP_MAPPING.md` for the
component-by-component trace to the source recommendations.

## Start here

| You have… | Follow | Then |
|-----------|--------|------|
| a **new project** (PRD + SRD, empty repo) | **[`NEW_PROJECT.md`](NEW_PROJECT.md)** — turn the SRD into an executable golden set and build under gates | `goldenset/new-project.template.yaml` |
| an **existing repo** to harden | **[`PLAYBOOK.md`](PLAYBOOK.md)** — 6-step field guide (+ [`ADOPTING.md`](ADOPTING.md) per-stage reference) | `ROADMAP_MAPPING.md` |
| a **release/npm repo** to protect | **[`recipes/release-safety/`](recipes/release-safety/README.md)** — downgrade guard + CI tripwire | — |
| to ask **"is it fine-tuned enough?"** | `awh maturity` — convergence verdict over adoptions | — |

### New project vs existing repo — same harness, one difference

Both paths install the **same** Stage 0–3 gates (`install.sh`), run the **same**
`awh eval` regression gate, and feed the **same** `awh maturity` tracker. The only
real difference is where the golden set comes from and which way it starts:

| | **New project** (greenfield) | **Existing repo** (harden) |
|---|---|---|
| Guide | [`NEW_PROJECT.md`](NEW_PROJECT.md) | [`PLAYBOOK.md`](PLAYBOOK.md) + [`ADOPTING.md`](ADOPTING.md) |
| Golden set comes from | the SRD's acceptance criteria, made executable | the repo's real lint / typecheck / test |
| Baseline starts | **RED** (~0 — features don't exist yet) | **GREEN** (repo already passes) |
| The job | burn the score **up** to 1.0 | **hold** the line — block regressions |
| Anti-cheat | held-out `tests_acceptance/**` sealed (`awh lock --hidden`) | lock `tests/**` read-only |
| Mode | spec-completion | ratchet / no-regression |

Everything else — the PreToolUse deny hooks, the Stop evidence-gate, mutation,
worktrees, release-safety, maturity — is **identical**. Pick the row, follow that
guide; the gates don't change.

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
make install          # pip install -e ".[dev]"  (pytest, hypothesis, ruff, bandit)
make verify           # ruff + full test suite  (this is the AUTO_WORK gate)
```

**To put the harness to work in a project, run `awh adopt`** — the one-command
Stage-0 scaffold:

```bash
awh adopt /path/to/repo   # installs the gate hooks + seeds .awh/ (gate, golden set, policy)
```

It's idempotent (never clobbers your files) and prints the exact baseline +
maturity steps to finish. For the full field guide see [`PLAYBOOK.md`](PLAYBOOK.md)
(existing repo) or [`NEW_PROJECT.md`](NEW_PROJECT.md) (greenfield); [`ADOPTING.md`](ADOPTING.md)
is the per-stage reference. This repo is dogfooded on itself: see
`.claude/settings.json`, `.awh/`, `goldenset/self.yaml`, and the committed
`eval-baseline.json`.

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

## Maturity — is it fine-tuned enough? (`awh maturity`)

The harness *evolves* when adopting a real repo forces a change to the harness
itself (a new gate, a recipe, a fix). It is **ready** when adopting *new* repos
stops forcing those changes — an empirical convergence signal, not a gut feeling.

`awh maturity` reads an evolution ledger (`evolution-log.jsonl`, one line per
adoption) and reports a verdict:

```
$ awh maturity
auto-work-harness — maturity / self-evolution
  adoptions recorded : 3 across 3 repo(s)
  evolution events   : 2
  clean streak       : 0 consecutive no-change adoption(s)
  recent rate        : 67% over last 3
  VERDICT            : STILL_EVOLVING
    -> need 3 more clean adoption(s) and rate <= 20% to call it READY.
```

Record one line per adoption (the last step of `PLAYBOOK.md`):

```
awh maturity log --repo CyberSkill/foo --outcome green                       # clean
awh maturity log --repo CyberSkill/bar --category recipe:x --note "why"       # forced a change
```

`harness_changed` is auto-derived from the harness git sha between runs, so even
a plain `log` records the curve. **READY** = `--ready-streak` clean adoptions
(default 3) *and* recent evolution rate ≤ `--max-rate` (default 20%). Use
`awh maturity --gate` in CI to fail until READY.

## Repository layout

```
harness/
  common/stats.py            pass@k, pass^k, Wilson CI, power analysis
  stage0_verification/       policy, hooks/, readonly, egress, settings template
  stage1_measurement/        goldenset, runner (pass@k report + gate), promptfoo/
  stage2_structural/         verifier, scorermix, mutation
  stage3_parallel/           worktree, pipeline
  goldenset/tasks/           example golden set (replace with your own)
  adopt.py                   `awh adopt` — one-command Stage-0 scaffold
  maturity.py                self-evolution / convergence ledger
  cli.py                     `awh` entry point
sandbox/                     devcontainer + iptables, Seatbelt profile, egress proxy
scripts/mutation_demo.py     end-to-end mutation demonstration (used by CI)
tests/                       290 tests (unit, Hypothesis PBT, real-repo git, audit-hardening)
recipes/                     reusable hardening patterns folded back from real adoptions
  release-safety/            semantic-release downgrade guard (plugin + CI tripwire)
```

## Caveats (carried from the survey)

- Same-uid `chmod` read-only is a **speed bump**, not a security boundary; the hard
  guarantee is the read-only bind mount / different uid in `sandbox/`.
- A **permitted domain can still exfiltrate** (Anthropic saw it); keep the egress
  allowlist minimal and watch credentialed egress to allowed hosts.
- **Egress proxies need real review** — a SOCKS5 bypass lived in Claude Code's proxy
  for ~5.5 months; the bundled proxy matches hosts exactly and is unit-tested for it.
- Several cited tools are fast-moving; pin versions before standardizing.
