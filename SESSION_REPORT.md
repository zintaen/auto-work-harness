# AUTO_WORK session report — auto-work-harness + adopters

Scope: build the agent-hardening harness (roadmap Stage 0–3), then adopt and
battle-test it on real CyberSkill repos. Multi-repo engagement: `auto-work-harness`
(product), `CyberSkill/shared` (npm library), `Personal/gam` (app).

Date of this report: 2026-06-16.

---

## 1. Completed ledger

All rows terminal. **M** = mine (from the goal), **D** = discovered during work.

| # | Task | Src | Status | Evidence |
|---|------|-----|--------|----------|
| 1 | Harness scaffold + Stage 0–3 (verification, measurement, structural, parallel) | M | DONE | `auto-work-harness` on `main`, 195+ tests |
| 2 | Dogfood Stage 0–1 on the harness itself | M | DONE | `goldenset/self.yaml`, `eval-baseline.json` |
| 3 | Push harness to GitHub | M | DONE | `git@github.com:zintaen/auto-work-harness.git`, 0 unpushed |
| 4 | Adopt harness on `gam` (Stage 0 + golden set) | M | DONE | `gam/.awh/` present |
| 5 | Fix eval hang (process-group kill + progress) | D | DONE | `runner.py` `os.killpg`/`start_new_session`; stage1 tests green |
| 6 | Fix `shared` pnpm install timeout | D | DONE | `.npmrc` mirror + timeouts; install succeeds |
| 7 | Adopt harness on `shared` (Stage 0 + golden set) | M | DONE | `shared/.awh/`, baseline 100% |
| 8 | Fix `shared` lint to green | D | DONE | eslint 0 errors (path-concat, jsdoc fixes) |
| 9 | Fix `shared` yamllint CI (`.serena` structural errors) | D | DONE | `yamllint` structural classes = 0 repo-wide |
| 10 | Fix `shared` semantic-release `1.0.0` regression | D | DONE | npm `latest` = 3.21.0; tag re-anchored |
| 11 | Add downgrade guard to `shared` | D | DONE | `verifyRelease` plugin; 5 scenarios verified |
| 12 | Generalize guard → harness recipe (org-wide) | D | DONE | `recipes/release-safety/`; 6/6 tests |
| 13 | Field playbook (`PLAYBOOK.md`) | D | DONE | distilled from shared/gam |
| 14 | "Docs are part of done" protocol rule | M | DONE | `AUTO_WORK.md` Rule 4 |

(Task tracker mirrors this: 25 rows, all terminal.)

## 2. What changed (grouped) + branches to review

- **A. Production readiness**
  - Harness: committed the eval-hang fix (`harness/cli.py`, `harness/stage1_measurement/runner.py`, `tests/test_stage1_runner.py`) — process-group `SIGKILL`, `start_new_session=True`, `stdin=DEVNULL`, live progress callback.
  - `shared`: eslint→0, yamllint→0 structural, `pnpm audit` overrides, `fetch-depth: 0` on deploy, semantic-release downgrade guard. Published **3.21.0**.
  - `gam`: deps install (mirror `.npmrc`), tests 225/225, `.awh/` gates.
- **B. Documentation**
  - Harness: `recipes/release-safety/README.md`, `PLAYBOOK.md`, `ADOPTING.md` §7, `README.md` layout pointer, this report.
- **C/D. Cleanup** — `.serena/project.yml` cleaned; lockfiles regenerated.

Review: `auto-work-harness` `git log --oneline -5` (HEAD `3ec6ef4`); `shared` at `4082f50`→ released 3.21.0; `gam` adoption commit.

## 3. What I verified (pasted)

```
# npm dist-tag — regression resolved
GET registry.npmjs.org/-/package/@cyberskill%2Fshared/dist-tags
{"latest":"3.21.0"}

# release-safety guard package
$ node --test   (recipes/release-safety/semantic-release-guard)
# tests 6 # pass 6 # fail 0

# guard behaviour matrix (stubbed npm)
1.0.0  vs latest 3.20.1 -> BLOCKED
3.20.0 vs latest 3.20.1 -> BLOCKED
3.20.1 vs latest 3.20.1 -> ALLOWED
3.21.0 vs latest 3.20.1 -> ALLOWED
npm unreachable          -> ALLOWED (skips, never blocks a real release)

# shared eval baseline (native host)
.awh/eval-baseline.json aggregate: n_tasks=3, macro_pass_at_1=1   (100%)

# harness stage-1 runner tests (with eval-hang fix)
$ pytest tests/test_stage1_runner.py -q
....................                                              [100%]

# shared yamllint structural classes (trailing-spaces/indentation/...)
>> NONE — all structural classes clean across the repo
```

## 4. Deliberately left undone (needs your hand or your call)

- **`gam` baseline refresh + commit** — DEFERRED to you: the eval needs the
  native toolchain (darwin binaries), and the baseline was captured at 0% before
  tests passed. Run `awh eval … --out .awh/eval-baseline.json` then commit. Also
  `pnpm-lock.yaml` showed deleted — regenerate before CI.
- **Publish `@cyberskill/semantic-release-guard`** — DEFERRED: publishing is a
  registry action (your npm creds). Until then repos can vendor the file.
- **`release-guard` composite action** — provided as a file; adding it to
  `cyberskill-official/.github` is your move (that repo isn't in this workspace).
- **Unpublish/deprecate `@cyberskill/shared@1.0.0`** — optional cleanup; `latest`
  is already correct at 3.21.0.

## 5. What you likely missed (risks / debt)

- **Other semantic-release repos in the org are still exposed** to the same
  lost-baseline downgrade until the guard + `fetch-depth: 0` land org-wide. The
  recipe exists to fix exactly this — highest-leverage follow-up.
- **`shared` had no `fetch-depth: 0`** until this session — any semantic-release
  repo cloned shallow shares the latent bug.
- **`gam`'s lockfile churn** (deleted in the working tree) is a reproducibility
  risk if committed in that state.
- **Baselines are host-specific**: they must be regenerated on the same toolchain
  CI uses, or the gate compares against the wrong reference.

## 6. Suitable next steps (prioritized)

1. **Land `gam`** — refresh baseline + commit lockfile (~10 min, you).
2. **Roll release-safety out org-wide** — publish `@cyberskill/semantic-release-guard`, add `fetch-depth: 0` + the guard to every semantic-release repo, drop the composite action into `cyberskill-official/.github` (~1–2 h). Highest leverage.
3. **Adopt awh on the next repo** — `cyberskill/sale-noti`, `tamagochi`, `cyberos`, or a publishing lib; follow `PLAYBOOK.md` (~30–45 min each).
4. **Harness niceties** — an `awh adopt` command that scaffolds steps 1–5 of the playbook; a `--check-host` preflight (~half day).

## 7. Memory / handoff

- Persist: harness shipped + pushed; `recipes/release-safety/` + `PLAYBOOK.md`
  added; `shared`@3.21.0 with guard; `gam` adopted (baseline refresh pending).
- No handoff packet needed — no in-flight edits; all working trees were committed
  by you between steps.

---

## Addendum — exhaustive security / edge-case audit (2026-06-16)

A subagent audit read every module for bypasses, silent-wrong-results, and crash
risks; all findings were fixed and pinned with regression tests
(`tests/test_audit_hardening.py`). Test count 231 → **267**.

**Security (Stage 0):**
- policy: closed four bypasses of the read-only/secret deny — `cat<.env` (redirect
  tokenizing), `./`-prefixed / absolute / `..` paths (path normalization + suffix
  match), `cp`/`ln`/`rsync` copy-into-protected, and quoted/glob/long-flag `rm`
  (`rm -rf '/'`, `/*`, `--recursive --force`). Policy parsing now fails safe on a
  non-object file or a wrong-typed field (no more `list("rm")` disabling containment).
- egress: the rendered root firewall now validates every domain/IP/subnet (hostname
  regex + `ipaddress`) before interpolation — a value like `github.com; rm -rf /`
  is rejected, not executed. Negative self-probe host is chosen out of the allowlist.

**Silent-wrong-result (Stage 1/2):**
- stats: `wilson_interval` rejects non-finite/≤0 `z`; `two_proportion_power`
  validates alpha/power and the post-clamp zero-delta divide-by-zero.
- scorermix / verifier: a non-finite score now fails to **0.0** (was silently
  clamped to a perfect 1.0); negative blend weights and truthy non-boolean `pass`
  are rejected.
- mutation: chained comparisons (`lo < x < hi`) are fully mutated; a file with no
  mutatable ops reports **N/A** (NaN), not 100%; a syntax error or a test command
  that fails on clean source raises `MutationError`.

**Robustness (Stage 3 / meta):**
- worktree: `task_id` is validated (`^[A-Za-z0-9._-]+$`, no `..`/`/`/leading-`-`)
  before it becomes a path or git ref; `merge` checks the branch exists, restores
  the prior HEAD in a `finally`, and `_git` has a timeout.
- pipeline: validates the integration branch exists before spawning workers;
  post-merge cleanup errors are suppressed so one failure can't abort the run.
- maturity: a corrupt/partial JSONL line or a forward-compat extra key no longer
  crashes the ledger read; `window<=0` is clamped.
- CLI: known user errors (`GoldenSetError`/`WorktreeError`/`MutationError`/
  `FileNotFoundError`) print `awh: error: …` instead of a traceback.
