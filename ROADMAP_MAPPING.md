# Roadmap → implementation mapping

Every component traces to a recommendation (and its primary source) in
*Pushing Autonomous Coding Agents Further: A 2025–2026 State-of-the-Art Survey and Roadmap*.

## Stage 0 — Harden what you have (verification infrastructure first)

| Roadmap recommendation | Source | Implementation |
|---|---|---|
| Convert the evidence gate from prompt- to **hook-enforced** (Stop/SubagentStop runs the suite and refuses turn-end on failure) | Claude Code hooks; exit-2 semantics | `harness/stage0_verification/hooks/stop_gate.py` (loop-guarded), `settings.template.json` |
| `PreToolUse` **deny rules** for destructive commands and secret reads; deny wins over allow | Anthropic containment 2026 (`~/.aws/credentials` exfil 24/25); METR | `harness/stage0_verification/policy.py`, `hooks/pretooluse_deny.py` |
| Make **test/scoring files read-only** (middle ground) or hidden | ImpossibleBench arXiv:2510.20270 (>79% of cheats are test edits); METR | `harness/stage0_verification/readonly.py` + `deny_write_globs` in the policy |
| **Default-deny egress sandbox**, credentials injected by a proxy outside the agent namespace | Anthropic sandboxing (Oct 2025, −84% prompts); SOCKS5 bypass caution | `harness/stage0_verification/egress.py`, `sandbox/` (devcontainer, Seatbelt, proxy) |

## Stage 1 — Build the measurement pillar (before any multi-agent work)

| Roadmap recommendation | Source | Implementation |
|---|---|---|
| Estimate pass@1 from **multiple independent seeds**; report pass@k AND pass^k | KTH arXiv 2602.07150 (60k trajectories, >1.5pt std @ T=0); τ-bench pass^k | `harness/common/stats.py`, `stage1_measurement/runner.py` |
| **Power analysis** to size the number of seeds | KTH study | `stats.seeds_for_power` / `awh power` |
| **Custom golden set** (~20–50 tasks) from your repos; grow from prod failures | Anthropic + production write-ups | `stage1_measurement/goldenset.py`, `harness/goldenset/tasks/` |
| Gate PRs on **regression vs. baseline**, not absolute score | KTH discipline | `runner.gate`, CI `eval` step |
| Alternative CI harness | promptfoo (MIT) | `stage1_measurement/promptfoo/` |

## Stage 2 — Structural verification depth

| Roadmap recommendation | Source | Implementation |
|---|---|---|
| **Property-based testing** so the agent can't pass by memorizing inputs | Anthropic red-team PBT; arXiv 2510.25297 caveat | `tests/test_stage2_pbt.py` (Hypothesis) |
| **Mutation testing** to catch tautological/weak tests | survey (mutation complements PBT) | `harness/stage2_structural/mutation.py`, `scripts/mutation_demo.py` |
| **Held-out composition tests** the agent never sees | SpecBench arXiv 2605.21384 | `examples/specbench_demo.md` (+ Stage 0 hidden mode) |
| **LLM-as-judge verifier** — single call, rubric, 0–1 + pass/fail; a *separate* agent reviewing diffs vs spec | Anthropic judge post; "never validate your own code in the same context window" | `harness/stage2_structural/verifier.py` |
| Scorer mix ~**60/30/10** deterministic/judge/human; never judge-only | production write-ups | `harness/stage2_structural/scorermix.py` |

## Stage 3 — Selective multi-agent / parallelism (only after 0–2)

| Roadmap recommendation | Source | Implementation |
|---|---|---|
| **git worktree-per-task** parallelism; structural collision guard; migration owner; per-worktree port/DB isolation | Augment; incident.io ("4–5 parallel agents"); GitButler/Cursor failure modes | `harness/stage3_parallel/worktree.py` |
| **planner → parallel workers (isolated worktrees) → verifier**; writes serialized through integration; filesystem-artifact handoff | Augment Intent; Anthropic orchestrator-worker | `harness/stage3_parallel/pipeline.py` |
| Read parallelizes, write doesn't; merge via orchestrator, never agent-to-agent | LangChain heuristic; Cognition | enforced by `Pipeline` phase split |

## Deliberately NOT built (roadmap "avoid as premature / low-ROI")

- Multi-agent **debate** for coding correctness (budget-normalized evidence shows it rarely beats a strong single agent).
- **Automated prompt optimization** (GEPA/DSPy/TextGrad) before a trustworthy eval set exists — the harness builds the eval set first; optimization is a later lever.
- **Chatty real-time agent-to-agent coordination** on shared files — replaced by hard worktree isolation.
