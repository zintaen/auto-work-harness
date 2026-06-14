"""Tests for the LLM-as-judge verifier and the scorer-mix blender."""

from __future__ import annotations

import json

import pytest

from harness.stage2_structural.scorermix import (
    DEFAULT_WEIGHTS,
    aggregate_deterministic,
    blend,
)
from harness.stage2_structural.verifier import (
    Criterion,
    Rubric,
    StubBackend,
    Verifier,
    VerifierError,
    build_prompt,
    code_review_rubric,
    parse_judgment,
)


def _judgment(criteria: dict, summary="ok") -> dict:
    return {"criteria": criteria, "summary": summary}


class TestParseJudgment:
    def test_all_pass(self):
        rub = code_review_rubric()
        crit = {c.name: {"score": 0.9, "pass": True} for c in rub.criteria}
        res = parse_judgment(json.dumps(_judgment(crit)), rub)
        assert res.passed
        assert res.overall_score == pytest.approx(0.9)

    def test_required_failure_blocks_pass(self):
        rub = code_review_rubric()
        crit = {c.name: {"score": 0.95, "pass": True} for c in rub.criteria}
        crit["security"] = {"score": 0.95, "pass": False}  # required -> must block
        import json

        res = parse_judgment(json.dumps(_judgment(crit)), rub)
        assert not res.passed
        assert res.overall_score > 0.75  # high score, still blocked by required fail

    def test_weighted_overall(self):
        import json

        rub = Rubric([Criterion("a", weight=1.0), Criterion("b", weight=3.0)], pass_threshold=0.2)
        text = json.dumps(_judgment({"a": {"score": 1.0, "pass": True}, "b": {"score": 0.0, "pass": False}}))
        res = parse_judgment(text, rub)
        assert res.overall_score == pytest.approx(0.25)  # (1*1 + 3*0)/4
        assert res.passed  # 0.25 >= 0.2

    def test_threshold_enforced(self):
        import json

        rub = Rubric([Criterion("a", weight=1.0), Criterion("b", weight=3.0)], pass_threshold=0.3)
        text = json.dumps(_judgment({"a": {"score": 1.0}, "b": {"score": 0.0}}))
        res = parse_judgment(text, rub)
        assert not res.passed  # 0.25 < 0.3

    def test_score_clamped(self):
        import json

        rub = Rubric([Criterion("a", weight=1.0)], pass_threshold=0.5)
        text = json.dumps(_judgment({"a": {"score": 2.5, "pass": True}}))
        res = parse_judgment(text, rub)
        assert res.per_criterion["a"]["score"] == 1.0

    def test_code_fence_tolerant(self):
        rub = Rubric([Criterion("a", weight=1.0)], pass_threshold=0.5)
        text = '```json\n{"criteria": {"a": {"score": 1.0, "pass": true}}, "summary": "x"}\n```'
        res = parse_judgment(text, rub)
        assert res.passed

    def test_prose_wrapped_json(self):
        rub = Rubric([Criterion("a", weight=1.0)], pass_threshold=0.5)
        text = 'Sure! Here is my review:\n{"criteria": {"a": {"score": 0.8, "pass": true}}}\nHope that helps.'
        res = parse_judgment(text, rub)
        assert res.passed

    def test_unparseable_raises(self):
        rub = code_review_rubric()
        with pytest.raises(VerifierError):
            parse_judgment("the diff looks fine to me, ship it", rub)


class TestVerifier:
    def test_end_to_end_pass(self):
        rub = code_review_rubric()
        crit = {c.name: {"score": 0.9, "pass": True} for c in rub.criteria}
        v = Verifier(backend=StubBackend(_judgment(crit)), rubric=rub)
        res = v.verify("diff --git a/x b/x ...", spec="add feature X")
        assert res.passed and res.error == ""

    def test_fail_closed_on_unparseable(self):
        v = Verifier(backend=StubBackend("looks good 👍"))
        res = v.verify("some diff")
        assert not res.passed and res.error

    def test_fail_closed_on_backend_error(self):
        def boom(prompt):
            raise RuntimeError("api down")

        res = Verifier(backend=boom).verify("diff")
        assert not res.passed and "backend error" in res.error

    def test_build_prompt_mentions_rubric_and_artifact(self):
        p = build_prompt("ARTIFACT-BODY", code_review_rubric(), spec="SPEC-BODY")
        assert "spec_adherence" in p and "ARTIFACT-BODY" in p and "SPEC-BODY" in p
        assert "JSON" in p


class TestScorerMix:
    def test_full_blend_default_weights(self):
        b = blend(deterministic=0.9, judge=0.6, human=0.0)
        # 0.6*0.9 + 0.3*0.6 + 0.1*0.0 = 0.72
        assert b.blended == pytest.approx(0.72)
        assert b.passed  # >= 0.7

    def test_renormalizes_without_human(self):
        b = blend(deterministic=0.9, judge=0.6)
        # (0.6*0.9 + 0.3*0.6) / 0.9 = 0.8
        assert b.blended == pytest.approx(0.8)
        assert sum(b.weights_used.values()) == pytest.approx(1.0)
        assert set(b.components) == {"deterministic", "judge"}

    def test_deterministic_list_is_averaged(self):
        b = blend(deterministic=[1.0, 0.0, 1.0])
        assert b.components["deterministic"] == pytest.approx(2 / 3)
        assert b.blended == pytest.approx(2 / 3)

    def test_judge_only(self):
        b = blend(deterministic=None, judge=0.42)
        assert b.blended == pytest.approx(0.42)

    def test_clamping(self):
        b = blend(deterministic=1.5, judge=-1.0)
        assert b.components["deterministic"] == 1.0
        assert b.components["judge"] == 0.0

    def test_no_components_raises(self):
        with pytest.raises(ValueError):
            blend(None, None, None)

    def test_aggregate_deterministic_empty(self):
        assert aggregate_deterministic([]) == 0.0

    def test_default_weights_sum_to_one(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_threshold_controls_pass(self):
        b = blend(deterministic=0.6, threshold=0.5)
        assert b.passed
        b2 = blend(deterministic=0.6, threshold=0.7)
        assert not b2.passed
