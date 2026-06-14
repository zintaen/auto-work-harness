# Held-out composition tests (SpecBench pattern)

SpecBench (Zhao et al., arXiv 2605.21384) decomposes a task into **spec + visible
tests + held-out composition tests** to catch exploits like "a 2,900-line
hash-table 'compiler' that memorizes test inputs." The agent optimizes against the
*visible* tests; the *held-out* tests — which compose the unit behaviours in ways
the agent never saw — are what actually decide pass/fail.

## Layout

```
feature/
├── SPEC.md                      # what to build (the agent sees this)
├── src/widget.py                # the agent edits this
├── tests_visible/               # the agent sees + runs these
│   └── test_widget_unit.py
└── tests_heldout/               # the agent NEVER sees these (graded separately)
    └── test_widget_composition.py
```

## How the harness enforces "never sees"

1. **Stage 0 read-only / hidden** — `harness.stage0_verification.readonly.lock_tests`
   with `scoring_globs=("tests_heldout/**",), hidden=True` chmod-seals the held-out
   suite unreadable; the PreToolUse `deny_write_globs` also blocks edits to it.
2. **Stage 0 sandbox** — for a hard guarantee, bind-mount `tests_heldout/` read-only
   owned by a different uid (see `sandbox/`), so even a same-uid `chmod` can't undo it.
3. **Stage 1 scoring** — the eval `check:` command runs the held-out suite, not the
   visible one, so the golden-set pass/fail reflects composition, not memorization.

## Why both PBT and held-out tests

- **Property-based** (`tests/test_stage2_pbt.py`) — invariants across the whole
  input space; can't be satisfied by memorizing inputs.
- **Held-out composition** — real end-to-end behaviours the agent couldn't see.
- **Mutation** (`harness.stage2_structural.mutation`) — proves the *visible* tests
  aren't tautological in the first place.

Together they close the three reward-hacking routes the survey documents: editing
tests, special-casing inputs, and writing weak tests that game coverage.
