# Recipe: release safety (semantic-release downgrade guard)

A reusable guard that stops semantic-release from publishing a version **lower**
than what is already on npm. Extracted from a real incident: `@cyberskill/shared`
was moved to a fresh GitHub repo, the move did not carry the version tags, and
semantic-release — which derives the current version from **git tags, not
`package.json`** — saw no baseline, defaulted to `1.0.0`, and republished
backwards over `3.20.1`, stealing the `latest` dist-tag.

This recipe folds that lesson back into the harness so **any** semantic-release
repo can adopt it in one step.

## Root cause, in one line

> semantic-release's notion of "current version" lives entirely in **git tags**.
> Move or rebuild history without `git push --tags` (or check out shallow with
> `fetch-depth: 1`) and it loses the baseline and can publish backwards.

So there are two non-negotiables for every semantic-release repo, independent of
this recipe:

1. **`fetch-depth: 0`** on the `actions/checkout` step (a shallow clone hides tags).
2. **Push tags** on any repo move/migration: `git push origin --tags` (or `--mirror`).

## Two layers of defense

| Layer | What it does | When it runs | Use it when |
|------|--------------|--------------|-------------|
| **Plugin** (`semantic-release-guard/`) | Blocks if the *computed* next version `<` npm `latest`. Precise, in-process. | semantic-release `verifyRelease`, before publish | Always — primary guard |
| **Composite action** (`composite-action/`) | Fails if the repo has **no version tags** but the package already exists on npm. Cheap root-cause tripwire, no semantic-release knowledge. | CI step, before the release job | Org-wide default, and for repos that can't add the plugin |

Run both for defense-in-depth: the action catches the lost-baseline *condition*
early and centrally; the plugin catches the *backwards version* precisely.

---

## Layer 1 — the plugin (`@cyberskill/semantic-release-guard`)

Dependency-free, ESM. Exposes a `verifyRelease` hook. It reads the consuming
repo's `package.json` name, asks npm for the current `latest`, and throws if the
computed version is lower. If npm is unreachable or the package is unpublished,
it **skips** (it is a safety net, never a flaky gate).

### Adopt it

**Option A — publish once, depend everywhere (recommended org-wide):**

```bash
# from this recipe folder, publish the tiny package once:
cd semantic-release-guard && npm publish    # @cyberskill/semantic-release-guard
```

Then in each repo:

```bash
pnpm add -D @cyberskill/semantic-release-guard
```

```js
// release.config.js — add BEFORE @semantic-release/npm
plugins: [
  '@semantic-release/commit-analyzer',
  '@semantic-release/release-notes-generator',
  '@cyberskill/semantic-release-guard',   // <-- gate
  '@semantic-release/changelog',
  '@semantic-release/npm',
  '@semantic-release/github',
  '@semantic-release/git',
]
```

**Option B — vendor it (no new package):** copy `semantic-release-guard/index.mjs`
into the repo (e.g. `scripts/guard-no-downgrade.mjs`) and reference it by path:
`'./scripts/guard-no-downgrade.mjs'`. This is what `@cyberskill/shared` does today.

### Test it

```bash
cd semantic-release-guard && node --test     # 6 tests: blocks 1.0.0 & patch downgrades, allows equal/forward, skips on npm error
```

---

## Layer 2 — the composite action (org-wide tripwire)

`composite-action/action.yml` fails a release if there are **zero `v*` tags** but
the package is already on npm — the precise lost-baseline signature — before
semantic-release even runs.

### Adopt it (`cyberskill-official/.github`)

1. Copy `composite-action/action.yml` to
   `cyberskill-official/.github/actions/release-guard/action.yml`.
2. In each repo's deploy workflow, ensure the checkout is full-depth and call the
   guard before the release step:

```yaml
- uses: actions/checkout@v6
  with:
    persist-credentials: false
    fetch-depth: 0                 # REQUIRED — shallow clones hide tags
- uses: cyberskill-official/.github/actions/release-guard@main
# ... env-deps / build ...
- run: pnpm exec semantic-release
```

> The tripwire is fail-closed: with a shallow checkout it sees zero tags and
> fails. That is intentional — better a blocked release than a silent downgrade —
> and it nudges every repo onto `fetch-depth: 0`.

---

## Recovering from a lost baseline (what we did for `shared`)

```bash
# 1) restore latest so consumers stop pulling the bad version
npm dist-tag add <pkg>@<good-version> latest

# 2) re-anchor the baseline tag at the real release commit, drop the bogus tag
git tag v<good-version> <commit> && git push origin v<good-version>
git tag -d v1.0.0 && git push origin :refs/tags/v1.0.0

# 3) add fetch-depth: 0 + the guard, push, re-run deploy  -> publishes the correct next version
# 4) clean up the bad version
npm unpublish <pkg>@1.0.0        # within 72h / 0 downloads; else `npm deprecate`
```
