# Adopting auto-work-harness in a project

A step-by-step guide to wiring the four stages into any repository — Python, Node,
Rust, Go, mixed. The harness hooks are language-agnostic: they are small Python
scripts that gate *any* agent's tool use, and the eval gate runs *your* commands.

This repo is dogfooded on itself — see `.claude/settings.json`, `.awh/`,
`goldenset/self.yaml`, and `eval-baseline.json` here for a live reference.

---

## 0. Prerequisites

- Python 3.10+ on the machine the agent runs on (the hooks call `python3`).
- The harness checked out somewhere stable, e.g. `~/Projects/auto-work-harness`.
- For Stage 1 you only need a shell; for the egress sandbox (Stage 0) Docker or a
  macOS host.

Install the harness once:

```bash
cd ~/Projects/auto-work-harness && make install   # editable install + dev deps
```

---

## 1. Stage 0 — wire the deterministic gates (highest ROI, do this first)

From the harness repo, point the installer at your target project:

```bash
./install.sh /path/to/your/project
```

This writes, in the target:

- `.claude/settings.json` — fires three hooks on every Claude Code session:
  - **PreToolUse** (`pretooluse_deny.py`) — blocks destructive commands and secret
    reads/exfiltration before they run (exit 2 → blocked, reason returned to the model).
  - **Stop / SubagentStop** (`stop_gate.py`) — reruns your evidence gate and refuses
    to end the turn while it is red.
  - **PostToolUse** (`posttooluse_format.py`) — formats edited Python files.
- `.awh/gate.sh` — a stub. **Edit it to run your real checks**, e.g.:
  - Node:   `pnpm lint && pnpm test && pnpm typecheck`
  - Python: `make verify` (ruff + pytest)
  - Rust:   `cargo clippy -- -D warnings && cargo test`

Then (optional but recommended) protect your tests from being edited to "pass"
during agent runs. Either:

```bash
# A) policy-only (reversible, no chmod): add a .awh/policy.json
python3 -m harness.cli lock /path/to/project --write-policy   # also chmods + writes policy
```

or hand-write `.awh/policy.json`:

```json
{ "deny_write_globs": ["tests/**", "**/*.test.ts"] }
```

Reads of tests stay allowed (they must run); only writes are denied. For a hard
guarantee (a determined same-uid process can `chmod` back), run the agent inside
the **egress sandbox** in `sandbox/` (default-deny network + read-only test mounts).

**Verify it works** (you should see exit 2 + a reason):

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
  | python3 ~/Projects/auto-work-harness/harness/stage0_verification/hooks/pretooluse_deny.py; echo $?
```

---

## 2. Stage 1 — stand up the measurement gate

1. Write a golden set of ~20–50 tasks from your repo. Each task has a `cmd` (the
   work / system-under-test) and optionally a `check` (the end-state scorer — its
   exit code decides pass/fail). Minimal example (`goldenset/self.yaml` here):

   ```yaml
   tasks:
     - id: unit-suite
       cmd: "pnpm test"
       weight: 3.0
     - id: lint-clean
       cmd: "pnpm lint"
   ```

2. Record a baseline and commit it:

   ```bash
   awh eval goldenset/self.yaml --seeds 3 --out eval-baseline.json
   git add eval-baseline.json goldenset/
   ```

   Use ≥3 seeds; for non-deterministic agents size the seed count with
   `awh power --baseline <p> --mde <effect>` (the KTH discipline — don't trust an
   improvement smaller than your run-to-run noise).

3. Gate CI on **regression vs. baseline**, not an absolute score:

   ```bash
   awh eval goldenset/self.yaml --seeds 3 --baseline eval-baseline.json --max-regression 0.0
   ```

   Set `--max-regression` to your measured noise floor once you have one. See
   `.github/workflows/ci.yml` here for a working job.

---

## 3. Stage 2 — structural verification depth

- **Property-based tests**: add Hypothesis (Python) / fast-check (TS) / proptest
  (Rust) for modules with invariants. See `tests/test_stage2_pbt.py`.
- **Mutation testing**: prove your suite isn't tautological:
  ```bash
  awh mutate path/to/module.py --test-cmd "python3 -B path/to/test.py" --min-score 0.8
  ```
  (For large suites prefer mutmut / cosmic-ray / Stryker; this is the always-available baseline.)
- **LLM-as-judge verifier**: a *separate* reviewer of each diff vs. spec
  (`harness/stage2_structural/verifier.py`). Wire a real backend (a `str -> str`
  callable hitting your model) and keep the deterministic/judge/human blend ~60/30/10
  (`scorermix.py`). Never judge-only.

---

## 4. Stage 3 — parallelism (only after 0–2)

For independent work, isolate each task in its own git worktree and merge serially
through the integration branch:

```bash
awh worktree create --repo . --task-id feature-x
# … agent works in the worktree …
awh worktree merge --repo . --task-id feature-x --into main
```

Or drive the whole planner→workers→verifier flow programmatically with
`harness/stage3_parallel/pipeline.py` (parallel isolated workers, a verifier gate,
serialized merges — never agent-to-agent).

---

## 5. Per-language gate cheatsheet

| Stack | `.awh/gate.sh` | golden-set `cmd` examples |
|---|---|---|
| Python | `make verify` or `ruff check . && pytest` | `pytest -q`, `ruff check .`, `mypy .` |
| Node/TS | `pnpm lint && pnpm test && pnpm typecheck` | `pnpm test`, `pnpm lint`, `pnpm exec tsc --noEmit` |
| Rust | `cargo clippy -- -D warnings && cargo test` | `cargo test`, `cargo clippy -- -D warnings` |
| Tauri/desktop | run the JS gate; skip native `build` in CI sandboxes | `pnpm test`, `pnpm lint` (run `tauri build` on the host) |

---

## 6. Troubleshooting

- **Hook "does nothing"** — confirm `python3` is on PATH and the command path in
  `.claude/settings.json` resolves. Test the hook directly (Stage 0 above).
- **Stop hook never blocks** — it only fires when `.awh/gate.sh` exists or
  `AWH_GATE_CMD` is set; check `find .awh/gate.sh`.
- **Eval gate flaky** — increase `--seeds` and set `--max-regression` to your noise
  floor; a single run is provably noise.
- **Mutation run slow** — point it at one module at a time; it runs the suite once
  per mutant by design.

---

## 7. Release safety (semantic-release / npm repos)

If the repo publishes to npm via **semantic-release**, add the release-safety
recipe — it prevents the "lost baseline" downgrade where a moved/rebuilt repo
loses its version tags and republishes backwards (e.g. `1.0.0` over `3.20.1`).

See [`recipes/release-safety/`](recipes/release-safety/README.md). In short:

- Checkout must use **`fetch-depth: 0`** (a shallow clone hides tags — this alone
  causes the bug).
- Add the **`@cyberskill/semantic-release-guard`** plugin (or vendor
  `recipes/release-safety/semantic-release-guard/index.mjs`) before
  `@semantic-release/npm` — it aborts if the computed version `<` npm `latest`.
- Optionally add the **`release-guard` composite action** org-wide as a cheap
  tripwire (fails when a repo has no version tags but the package already exists).
- On any repo move: **`git push origin --tags`** (or `--mirror`).
