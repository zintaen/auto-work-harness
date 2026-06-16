# Building a NEW project from a PRD + SRD with auto-work-harness

Step-by-step for greenfield work: you have a **PRD** (product requirements) and an
**SRD** (system/software requirements) as markdown, an empty repo, and you want an
agent to implement it *under verification gates* so "done" is provable, not vibes.

> Adopting the harness into an **existing** repo instead? See
> [`PLAYBOOK.md`](PLAYBOOK.md) (field guide) and [`ADOPTING.md`](ADOPTING.md)
> (per-stage reference). Same gates — you just derive the golden set from the
> repo's existing checks rather than from an SRD.

---

## The idea in one paragraph

Turn the **SRD's acceptance criteria into an executable golden set** — a suite of
checks that starts almost entirely **RED**. The agent (Claude Code under your
`AUTO_WORK.md` protocol) does the implementing; the harness enforces the rules:
Stage 0 hooks stop the agent from ending a turn while checks are red and block it
from editing the acceptance tests to cheat (the SpecBench held-out pattern), and
Stage 1 `awh eval` turns "how done are we?" into a single climbing number. The
build is finished when the golden set is **GREEN and stays green**.

```
PRD/SRD.md ──derive──▶ golden set (RED) ──agent implements under gates──▶ golden set (GREEN) = done
                         ▲                         │
                         └──── awh eval measures ──┘   (burn-up from ~0 → 1.0)
```

---

## Prerequisites

```bash
# install the harness once; puts `awh` on PATH
cd ~/Projects/auto-work-harness && make install
awh --version
```

Decide the stack up front (language, **build**, **lint**, **typecheck**, **test**
commands). You will reuse those four commands throughout.

---

## Step 1 — Bootstrap the repo to a green baseline

```bash
mkdir my-project && cd my-project
git init
mkdir -p docs tests tests_acceptance
cp /path/to/PRD.md docs/PRD.md
cp /path/to/SRD.md docs/SRD.md

# scaffold your stack so an EMPTY build + test run green, e.g.:
#  Node/TS : pnpm init ; add vitest+eslint+typescript ; scripts: build/lint/typecheck/test
#  Python  : uv init   ; add pytest+ruff+mypy
git add -A && git commit -m "chore: scaffold + PRD/SRD"
```

Get to "it builds and an empty test suite passes" **before** involving the agent —
the harness measures regressions against a baseline, so the baseline must start
green on the plumbing even though the features don't exist yet.

## Step 2 — Derive the acceptance golden set from the SRD

This is the heart of greenfield. Two test layers (SpecBench pattern — see
[`examples/specbench_demo.md`](examples/specbench_demo.md)):

- **Visible tests** (`tests/`) — unit/integration tests the agent sees and runs as
  it works.
- **Held-out acceptance tests** (`tests_acceptance/`) — end-to-end checks written
  straight from the SRD acceptance criteria that the agent must **not read or
  edit**. These decide "done" and can't be gamed by memorizing inputs.

Write one acceptance test per SRD requirement, named for the requirement id
(`FR-3.2`, `NFR-1`, …) so the eval report maps 1:1 to the spec. Then declare the
golden set (copy [`goldenset/new-project.template.yaml`](goldenset/new-project.template.yaml)):

```yaml
---
# .awh/goldenset.yaml — derived from docs/SRD.md. RED until implemented; that's the target.
tasks:
  - id: build
    description: project builds
    cmd: "pnpm build"
    weight: 1.0
    timeout_sec: 300
  - id: typecheck
    cmd: "pnpm exec tsc --noEmit"
    weight: 1.0
    timeout_sec: 240
  - id: lint
    cmd: "pnpm lint"
    weight: 1.0
    timeout_sec: 240
  - id: acceptance              # the SRD, made executable (held-out suite)
    description: SRD acceptance criteria pass
    cmd: "pnpm test:acceptance"
    weight: 5.0
    timeout_sec: 600
```

Weight the `acceptance` task heavily so the eval score tracks real progress, not
plumbing.

## Step 3 — Wire the Stage-0 gates

```bash
~/Projects/auto-work-harness/install.sh "$(pwd)"
```

Writes `.claude/settings.json` (PreToolUse deny + **Stop evidence-gate** +
PostToolUse format) and a `.awh/gate.sh` stub. Edit `.awh/gate.sh` to your **fast**
checks (build+lint+typecheck+visible tests — *not* the slow acceptance suite, which
the eval runs):

```sh
#!/usr/bin/env sh
set -e
pnpm lint && pnpm exec tsc --noEmit && pnpm test
```

Now the Stop hook reruns this gate and refuses to let the agent end a turn while
it's red.

## Step 4 — Seal the acceptance tests (anti-cheat)

So the agent implements *toward* the spec instead of editing it:

```bash
awh lock "$(pwd)" --scoring "tests_acceptance/**" --hidden --write-policy
```

This chmod-seals the held-out suite unreadable and writes `.awh/policy.json`
`deny_write_globs` so the PreToolUse hook blocks edits to it. For a hard guarantee
on untrusted runs, also bind-mount `tests_acceptance/` read-only under a different
uid via [`sandbox/`](sandbox/README.md).

## Step 5 — Capture the RED baseline

```bash
awh eval .awh/goldenset.yaml --seeds 1 --out .awh/eval-baseline.json
git add -A && git commit -m "test: acceptance golden set + RED baseline"
```

A low score is expected and correct — most acceptance tasks fail. That's the
starting line.

## Step 6 — Drive the implementation (the agent loop)

Run your agent (Claude Code under `~/Projects/AUTO_WORK.md`) on the repo with a
prompt like:

> Implement `docs/PRD.md` + `docs/SRD.md`. The executable spec is
> `.awh/goldenset.yaml`; acceptance tests live in `tests_acceptance/` — **do not
> read or edit them**. Work feature by feature until
> `awh eval .awh/goldenset.yaml` reaches 1.0. `.awh/gate.sh` must be green to end
> any turn.

The gates enforce the contract: can't stop on red, can't touch the acceptance
suite, can't exfiltrate. You supply direction; the harness supplies the guardrails.

## Step 7 — Measure progress (burn-up + regression gate)

Re-run anytime; the score climbs from ~0 → 1.0 as requirements land:

```bash
awh eval .awh/goldenset.yaml --seeds 1 \
  --baseline .awh/eval-baseline.json --max-regression 0.0
```

With `--baseline` the command also **fails on any regression**, so a new feature
that breaks an earlier requirement is caught immediately. Refresh the baseline
(`--out`) as the score legitimately rises.

## Step 8 — (optional) Parallelize independent features — Stage 3

For independent workstreams, give each its own git worktree so parallel agents
can't collide:

```bash
awh worktree create FR-3 --base main
awh worktree create FR-4 --base main
# implement each in its own worktree, then serialized merge:
awh worktree merge FR-3 --into main
```

When you script the orchestration, the planner→worker→verifier pipeline
(`harness/stage3_parallel/pipeline.py`) runs workers in parallel and has a
**separate verifier** review each artifact before a serialized merge — never
validate code in the same context that wrote it.

## Step 9 — Ship + record

- Done when `awh eval .awh/goldenset.yaml` = 1.0 **and** `.awh/gate.sh` is green.
- Publishing to npm? Wire [`recipes/release-safety/`](recipes/release-safety/README.md)
  (downgrade guard + `fetch-depth: 0`).
- Log the build so the harness tracks its own convergence:
  `awh maturity log --repo my-project --outcome green`.

---

## Definition of done (greenfield)

- [ ] `awh eval .awh/goldenset.yaml` = **1.0** (every acceptance criterion passes)
- [ ] `.awh/gate.sh` green (build + lint + typecheck + visible tests)
- [ ] acceptance suite still **held-out + sealed** (never read/edited by the agent)
- [ ] RED→GREEN baseline committed; CI runs `awh eval --baseline`
- [ ] release-safety wired **if** the project publishes
- [ ] adoption logged via `awh maturity`

## Troubleshooting

- **Agent edits an acceptance test** → it wasn't sealed; re-run Step 4 and confirm
  `.awh/policy.json` lists `tests_acceptance/**` and the files are unreadable.
- **Eval hangs** → ensure each task has a `timeout_sec`; the runner SIGKILLs the
  whole process group on timeout.
- **Score won't reach 1.0 but features look done** → an acceptance test encodes a
  requirement the impl missed; read the per-task eval output to find which id fails.
- **Native toolchain in CI vs local** → generate the baseline on the same toolchain
  CI uses (see `PLAYBOOK.md` gotchas).
