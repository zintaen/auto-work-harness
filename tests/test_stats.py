"""Tests for the statistical core (harness.common.stats).

Values are checked against closed-form expectations so the estimators can be
trusted as the basis for the eval gate.
"""

from __future__ import annotations

import math

import pytest

from harness.common.stats import (
    inv_norm_cdf,
    pass_at_k,
    pass_hat_k,
    seeds_for_power,
    two_proportion_power,
    wilson_interval,
)


class TestPassAtK:
    def test_all_correct_is_one(self):
        assert pass_at_k(5, 5, 1) == 1.0

    def test_none_correct_is_zero(self):
        assert pass_at_k(5, 0, 1) == 0.0

    def test_pass_at_1_equals_c_over_n(self):
        assert pass_at_k(10, 1, 1) == pytest.approx(0.1)
        assert pass_at_k(5, 2, 1) == pytest.approx(0.4)

    def test_k_exceeding_failures_saturates_to_one(self):
        # only 1 incorrect sample, k=2 -> every 2-subset contains a correct one
        assert pass_at_k(2, 1, 2) == 1.0

    def test_known_combinatorial_values(self):
        # 1 - (4/5)*(3/4) = 0.4
        assert pass_at_k(5, 1, 2) == pytest.approx(0.4)
        # 1 - (5/10)*(4/9) = 7/9
        assert pass_at_k(10, 5, 2) == pytest.approx(7 / 9)

    def test_monotonic_increasing_in_k(self):
        vals = [pass_at_k(20, 4, k) for k in range(1, 21)]
        assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:], strict=False))
        assert vals[-1] == 1.0  # pass@n with any correct sample is 1

    @pytest.mark.parametrize("n,c,k", [(5, 6, 1), (5, 2, 6), (0, 0, 1), (5, -1, 1), (5, 2, 0)])
    def test_invalid_inputs_raise(self, n, c, k):
        with pytest.raises(ValueError):
            pass_at_k(n, c, k)


class TestPassHatK:
    def test_all_correct_is_one(self):
        assert pass_hat_k(5, 5, 2) == 1.0

    def test_known_values(self):
        assert pass_hat_k(5, 2, 2) == pytest.approx(0.1)  # C(2,2)/C(5,2)=1/10
        assert pass_hat_k(4, 2, 1) == pytest.approx(0.5)  # C(2,1)/C(4,1)=2/4

    def test_fewer_correct_than_k_is_zero(self):
        assert pass_hat_k(5, 1, 2) == 0.0

    def test_pessimistic_vs_optimistic(self):
        # pass^k <= pass@k always (consistency is harder than "at least one")
        for k in (1, 2, 3):
            assert pass_hat_k(8, 3, k) <= pass_at_k(8, 3, k) + 1e-12

    def test_pass_hat_1_equals_pass_at_1(self):
        assert pass_hat_k(7, 3, 1) == pytest.approx(pass_at_k(7, 3, 1))


class TestWilson:
    def test_half_of_hundred(self):
        iv = wilson_interval(50, 100)
        assert iv.point == pytest.approx(0.5)
        assert iv.low == pytest.approx(0.4038, abs=1e-3)
        assert iv.high == pytest.approx(0.5962, abs=1e-3)

    def test_bounds_clamped_to_unit_interval(self):
        lo = wilson_interval(0, 10)
        hi = wilson_interval(10, 10)
        # Wilson stays within [0, 1] by construction; bounds clamped against float drift.
        assert lo.low == 0.0 and 0.0 < lo.high < 0.32
        assert hi.high == pytest.approx(1.0) and 0.68 < hi.low < 1.0
        assert 0.0 <= lo.low <= lo.high <= 1.0
        assert 0.0 <= hi.low <= hi.high <= 1.0 + 1e-12

    def test_unpacking(self):
        low, high = wilson_interval(7, 20)
        assert low < 7 / 20 < high

    def test_invalid(self):
        with pytest.raises(ValueError):
            wilson_interval(11, 10)
        with pytest.raises(ValueError):
            wilson_interval(1, 0)


class TestInvNormCdf:
    def test_median(self):
        assert inv_norm_cdf(0.5) == pytest.approx(0.0, abs=1e-9)

    def test_known_quantiles(self):
        assert inv_norm_cdf(0.975) == pytest.approx(1.959964, abs=1e-5)
        assert inv_norm_cdf(0.8413447) == pytest.approx(1.0, abs=1e-4)

    def test_symmetry(self):
        assert inv_norm_cdf(0.1) == pytest.approx(-inv_norm_cdf(0.9), abs=1e-9)

    @pytest.mark.parametrize("p", [0.0, 1.0, -0.1, 1.1])
    def test_out_of_domain_raises(self, p):
        with pytest.raises(ValueError):
            inv_norm_cdf(p)


class TestPower:
    def test_sanity_band(self):
        # detecting +20 pts from a 50% baseline at alpha=.05/power=.80 ~ 93/arm
        n = two_proportion_power(0.5, 0.20, 0.05, 0.80)
        assert 90 <= n <= 96

    def test_smaller_effect_needs_more_seeds(self):
        big = two_proportion_power(0.5, 0.20, 0.05, 0.80)
        small = two_proportion_power(0.5, 0.05, 0.05, 0.80)
        assert small > big

    def test_noise_floor_needs_many_seeds(self):
        # the SWE-bench Verified ~1.5pt noise floor at a 50% baseline is expensive
        assert two_proportion_power(0.5, 0.015, 0.05, 0.80) > 5000

    def test_higher_power_needs_more_seeds(self):
        p80 = two_proportion_power(0.5, 0.1, 0.05, 0.80)
        p90 = two_proportion_power(0.5, 0.1, 0.05, 0.90)
        assert p90 > p80

    def test_seeds_for_power_wrapper(self):
        res = seeds_for_power(0.6, 0.1)
        assert res.seeds_per_arm >= 1
        assert "baseline" in res.summary() or "%" in res.summary()
        assert math.isfinite(res.seeds_per_arm)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            two_proportion_power(0.0, 0.1, 0.05, 0.8)
        with pytest.raises(ValueError):
            two_proportion_power(0.5, 0.0, 0.05, 0.8)
