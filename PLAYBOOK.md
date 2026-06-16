# Field Playbook — adopting auto-work-harness on a new repo

The opinionated, battle-tested sequence, distilled from real adoptions
(`@cyberskill/shared`, `gam`). For the full per-stage reference see
[`ADOPTING.md`](ADOPTING.md); this is the "what to actually do, in order, and the
traps we hit" version. Work top to bottom.

## The 6-step sequence

0. **Pre-flight** — the repo must already be green
1. **Stage 0** — deterministic gates (`install.sh`)
2. **Golden set** — your real checks
3. **Baseline** — on the native host
4. **Release safety** — only if it publishes
5. **Commit + verify CI**

---

### 0. Pre-flight

- **Adopt only a repo that already installs and passes locally.** The harness
  measures regressions against a baseline — a red repo yields a red baseline and
  a useless gate.
- **Slow/Asia npm CDN:** if `pnpm i` crawls (<50 KiB/s) or throws
  `BROKEN_METADATA_JSON`, add an `.npmrc` mirror. `.npmrc` is a credential-class
  file — create it by hand (the agent can't). Real, working config from `gam`:

  ```ini
  # .npmrc
  registry=https://registry.npmmirror.com
  fetch-timeout=600000
  fetch-retries=5
  fetch-retry-mintimeout=20000
  fetch-retry-maxtimeout=180000
  network-concurrency=5
  ```

- Write down the repo's **verify commands** (lint / typecheck / test) — you need
  them twice (in `gate.sh` and the golden set).

### 1. Stage 0 — deterministic gates

```bash
cd ~/Projects/auto-work-harness
./install.sh /path/to/repo
```

Writes into the target: `.claude/settings.json` (PreToolUse deny + Stop
evidence-gate + PostToolUse format) and `.awh/gate.sh` (a stub).

- **Edit `.awh/gate.sh`** to your real checks, e.g.
  `pnpm lint && pnpm exec tsc --noEmit && pnpm test`.
- Lock tests read-only so an agent can't "pass" by editing assertions:

  ```json
  // .awh/policy.json
  { "deny_write_globs": ["tests/**", "**/*.test.ts", "**/*.spec.ts"] }
  ```

### 2. Golden set

`.awh/goldenset.yaml` — 2–4 deterministic tasks. Deterministic ⇒ 1 seed is
enough; every task gets a `timeout_sec` so a hang is bounded. Keep it
yamllint-clean (`---` start, watch line length — CI lints it).

```yaml
---
tasks:
  - id: lint
    cmd: "pnpm lint"
    weight: 1.0
    timeout_sec: 240
  - id: typecheck
    cmd: "pnpm exec tsc --noEmit -p tsconfig.json"
    weight: 1.0
    timeout_sec: 240
  - id: unit
    cmd: "pnpm test"
    weight: 3.0
    timeout_sec: 300
```

### 3. Baseline — ON THE NATIVE HOST

The Linux CI/sandbox can't run darwin-native toolchains (rollup, esbuild,
vitest, Tauri). Generate the baseline on the Mac:

```bash
cd /path/to/repo
awh eval .awh/goldenset.yaml --seeds 1 --out .awh/eval-baseline.json
```

**Eyeball it before committing** — every task should pass
(`aggregate.macro_pass_at_1 == 1`). A baseline captured while the repo is red
(deps not installed, a failing test) silently neuters the gate. (This bit `gam`:
its first baseline was 0% because it was captured before the tests were fixed.)

### 4. Release safety — only if the repo publishes via semantic-release

See [`recipes/release-safety/`](recipes/release-safety/README.md). Minimum:

- `actions/checkout` with **`fetch-depth: 0`** (shallow clones hide tags →
  backwards publishes).
- Add **`@cyberskill/semantic-release-guard`** before `@semantic-release/npm`.
- On any repo move: **`git push origin --tags`**.

### 5. Commit + verify CI

- **Regenerate and commit the lockfile** — never leave `pnpm-lock.yaml` deleted;
  CI `--frozen-lockfile` installs will fail.
- If `pnpm audit --audit-level=moderate` flags transitive CVEs, pin them in
  `pnpm-workspace.yaml` `overrides` (real `shared` example below).
- **yamllint:** the org CI action uses *its own* config (it overrides the repo
  `.yamllint.yaml`), so tool-generated YAML (e.g. `.serena/project.yml`) must
  itself be clean — strip trailing spaces and indent sequence items.
- Commit `.claude/ .awh/ .npmrc pnpm-workspace.yaml` + the lockfile.

```yaml
# pnpm-workspace.yaml — pin audited transitive deps (real shared example)
overrides:
  esbuild: '>=0.28.1'
  minimatch: '>=10.2.5'
  next: 16.2.6
  path-to-regexp: 8.4.2
  postcss: '>=8.5.10'
  uuid: '>=14.0.0'
```

---

## Gotchas we actually hit

| Symptom | Cause | Fix |
|---|---|---|
| `pnpm i` crawls ~1 KiB/s, or `BROKEN_METADATA_JSON` | slow/unreliable npm CDN (VN/Asia) | `.npmrc` mirror + timeouts (step 0) |
| `awh eval` hangs past the timeout | a watcher/daemon grandchild held the output pipe open | fixed in harness: process-group `SIGKILL` + `start_new_session` + `stdin=DEVNULL` |
| Baseline reads 0% but the repo is fine | captured while the repo was red (deps/test) | regenerate after green; eyeball before commit |
| yamllint CI red on `.serena/project.yml` | org action overrides repo `.yamllint`; lints tool-generated files | clean the file (trailing space, sequence indent) |
| Published `1.0.0` over `3.x` | repo moved without version tags; semantic-release lost its baseline | restore tags + `fetch-depth: 0` + downgrade guard (recipe) |
| Can't push from the agent sandbox | no SSH creds in the sandbox | push from the host; deliver a `git bundle` if needed |

## Adoption ledger

| Repo | Stage 0 | Golden set | Baseline | Release-safe | Notes |
|---|---|---|---|---|---|
| auto-work-harness | ✅ | ✅ `self.yaml` | ✅ | n/a | dogfood |
| CyberSkill/shared | ✅ | ✅ | ✅ 100% | ✅ guard + `fetch-depth: 0` | publishes to npm |
| Personal/gam | ✅ | ✅ | ✅ (refresh after 225/225) | n/a | app, no publish |
| _next_ | | | | | |
