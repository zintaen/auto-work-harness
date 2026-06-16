"""Property-based tests (Hypothesis) — the guardrail an agent can't satisfy by
memorizing test inputs.

These assert *invariants* of the statistical core across the whole input space.
PBT defines properties the agent must actually satisfy (not example outputs it can
special-case), per the Stage-2 recommendation. They double as the worked example
for adding PBT to your own modules.
"""

from __future__ import annotations

import pytest

# PBT lives in the `dev` extra. If hypothesis isn't installed (runtime-only
# `pip install -e .`), skip this module cleanly instead of crashing collection
# for the whole suite. Run `make install` to get the dev deps and actually run PBT.
pytest.importorskip("hypothesis")

from hypothesis import assume, given
from hypothesis import strategies as st

from harness.common.stats import (
    inv_norm_cdf,
    pass_at_k,
    pass_hat_k,
    two_proportion_power,
    wilson_interval,
)


@st.composite
def n_c_k(draw):
    n = draw(st.integers(min_value=1, max_value=60))
    c = draw(st.integers(min_value=0, max_value=n))
    k = draw(st.integers(min_value=1, max_value=n))
    return n, c, k


class TestPassKProperties:
    @given(n_c_k())
    def test_bounded_unit_interval(self, nck):
        n, c, k = nck
        assert 0.0 <= pass_at_k(n, c, k) <= 1.0
        assert 0.0 <= pass_hat_k(n, c, k) <= 1.0

    @given(n_c_k())
    def test_pessimistic_le_optimistic(self, nck):
        n, c, k = nck
        assert pass_hat_k(n, c, k) <= pass_at_k(n, c, k) + 1e-9

    @given(st.integers(1, 60), st.integers(0, 60))
    def test_pass_at_k_monotonic_in_k(self, n, c):
        c = min(c, n)
        prev = -1.0
        for k in range(1, n + 1):
            v = pass_at_k(n, c, k)
            assert v >= prev - 1e-9
            prev = v

    @given(st.integers(1, 60), st.integers(0, 60))
    def test_pass_at_1_is_c_over_n(self, n, c):
        c = min(c, n)
        assert abs(pass_at_k(n, c, 1) - c / n) < 1e-12

    @given(st.integers(1, 60), st.integers(0, 60))
    def test_all_correct_saturates(self, n, c):
        assume(c >= 1)
        c = min(c, n)
        assert pass_at_k(n, c, n) == 1.0  # any correct sample => pass@n is 1


class TestWilsonProperties:
    @given(st.integers(0, 500), st.integers(1, 500))
    def test_contains_point_and_in_unit(self, s, n):
        s = min(s, n)
        iv = wilson_interval(s, n)
        assert 0.0 <= iv.low <= iv.point <= iv.high <= 1.0 + 1e-12


class TestInvNorm:
    @given(st.floats(min_value=1e-6, max_value=1 - 1e-6))
    def test_symmetry(self, p):
        assert abs(inv_norm_cdf(p) + inv_norm_cdf(1 - p)) < 1e-6


class TestPowerProperties:
    @given(
        st.floats(min_value=0.05, max_value=0.95),
        st.floats(min_value=0.01, max_value=0.2),
    )
    def test_seeds_positive_and_monotone(self, baseline, mde):
        n_big = two_proportion_power(baseline, mde, 0.05, 0.8)
        n_small = two_proportion_power(baseline, mde / 2, 0.05, 0.8)
        assert n_big >= 1
        assert n_small >= n_big  # detecting a smaller effect never needs fewer seeds
