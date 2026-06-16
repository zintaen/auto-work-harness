"""Tests for harness.maturity — the self-evolution convergence tracker."""

from __future__ import annotations

from harness.maturity import Run, read_runs, record_run, summarize


def test_record_run_detects_harness_change(tmp_path):
    log = tmp_path / "evo.jsonl"
    r1 = record_run(log, repo="a", harness_version="v1", now=1.0)
    assert r1.harness_changed is False  # first run — no baseline to compare
    r2 = record_run(log, repo="b", harness_version="v1", now=2.0)
    assert r2.harness_changed is False  # same version
    r3 = record_run(log, repo="c", harness_version="v2", now=3.0)
    assert r3.harness_changed is True  # version moved -> evolution
    assert len(read_runs(log)) == 3


def test_is_evolution_rules():
    assert Run(0, "a", "v1", categories=["recipe:x"]).is_evolution() is True
    assert Run(0, "a", "v1", harness_changed=True).is_evolution() is True
    assert Run(0, "a", "v1").is_evolution() is False


def test_insufficient_data(tmp_path):
    log = tmp_path / "evo.jsonl"
    record_run(log, repo="a", harness_version="v1", now=1.0)
    rep = summarize(log, ready_streak=3)
    assert rep.verdict == "INSUFFICIENT_DATA"


def test_still_evolving_when_recent_churn(tmp_path):
    log = tmp_path / "evo.jsonl"
    record_run(log, repo="a", harness_version="v1", now=1.0)
    record_run(log, repo="b", harness_version="v1", now=2.0, categories=["fix:x"])
    record_run(log, repo="c", harness_version="v2", now=3.0, categories=["recipe:y"])
    rep = summarize(log, window=5, ready_streak=3, max_rate=0.2)
    assert rep.verdict == "STILL_EVOLVING"
    assert rep.no_evolution_streak == 0
    assert rep.evolution_events == 2
    assert rep.categories.get("fix:x") == 1
    assert rep.categories.get("recipe:y") == 1


def test_ready_after_clean_streak(tmp_path):
    log = tmp_path / "evo.jsonl"
    record_run(log, repo="a", harness_version="v1", now=1.0, categories=["fix:x"])
    record_run(log, repo="b", harness_version="v2", now=2.0)  # version moved -> evolution
    record_run(log, repo="c", harness_version="v2", now=3.0)  # clean
    record_run(log, repo="d", harness_version="v2", now=4.0)  # clean
    record_run(log, repo="e", harness_version="v2", now=5.0)  # clean
    rep = summarize(log, window=3, ready_streak=3, max_rate=0.2)
    assert rep.no_evolution_streak == 3
    assert rep.recent_rate == 0.0
    assert rep.verdict == "READY"


def test_streak_breaks_on_recent_evolution(tmp_path):
    log = tmp_path / "evo.jsonl"
    record_run(log, repo="a", harness_version="v1", now=1.0)
    record_run(log, repo="b", harness_version="v1", now=2.0)
    record_run(log, repo="c", harness_version="v1", now=3.0)
    record_run(log, repo="d", harness_version="v2", now=4.0)  # most recent = evolution
    rep = summarize(log, window=5, ready_streak=3, max_rate=0.2)
    assert rep.no_evolution_streak == 0
    assert rep.verdict == "STILL_EVOLVING"
