"""Tests for the Stage-1 golden set loader and multi-seed eval runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.stage1_measurement.goldenset import (
    GoldenSetError,
    GoldenTask,
    load_tasks,
)
from harness.stage1_measurement.runner import (
    EvalReport,
    TaskResult,
    evaluate,
    gate,
    run_task,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "harness" / "goldenset" / "tasks"
SEEDS = list(range(8))


class TestLoader:
    def test_loads_example_tasks(self):
        tasks = load_tasks(EXAMPLES / "example_tasks.yaml")
        ids = {t.id for t in tasks}
        assert ids == {"deterministic-pass", "flaky-3-of-4", "end-state-checked"}
        flaky = next(t for t in tasks if t.id == "flaky-3-of-4")
        assert flaky.weight == 2.0

    def test_duplicate_id_raises(self, tmp_path):
        f = tmp_path / "d.yaml"
        f.write_text("tasks:\n  - {id: a, cmd: 'true'}\n  - {id: a, cmd: 'true'}\n")
        with pytest.raises(GoldenSetError, match="duplicate"):
            load_tasks(f)

    def test_missing_cmd_raises(self, tmp_path):
        f = tmp_path / "d.yaml"
        f.write_text("tasks:\n  - {id: a}\n")
        with pytest.raises(GoldenSetError, match="cmd"):
            load_tasks(f)

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(GoldenSetError):
            load_tasks(tmp_path / "nope.yaml")

    def test_single_mapping_and_list_forms(self, tmp_path):
        (tmp_path / "one.yaml").write_text("id: solo\ncmd: 'true'\n")
        (tmp_path / "two.yaml").write_text("- {id: x, cmd: 'true'}\n- {id: y, cmd: 'true'}\n")
        ids = {t.id for t in load_tasks(tmp_path)}
        assert ids == {"solo", "x", "y"}


class TestRunTaskReal:
    def test_deterministic_pass(self, tmp_path):
        t = GoldenTask(id="p", cmd='python3 -c "import sys;sys.exit(0)"')
        assert run_task(t, 0, tmp_path) is True

    def test_seed_dependent(self, tmp_path):
        t = GoldenTask(
            id="f",
            cmd="python3 -c \"import os,sys;sys.exit(0 if int(os.environ['AWH_SEED'])%4 else 1)\"",
        )
        assert run_task(t, 1, tmp_path) is True
        assert run_task(t, 4, tmp_path) is False

    def test_check_is_source_of_truth(self, tmp_path):
        t = GoldenTask(
            id="c",
            cmd="python3 -c \"print('work')\"",  # always rc 0
            check="python3 -c \"import os,sys;sys.exit(0 if int(os.environ['AWH_SEED'])%2 else 1)\"",
        )
        assert run_task(t, 1, tmp_path) is True  # check passes on odd seed
        assert run_task(t, 2, tmp_path) is False  # check fails on even seed

    def test_timeout_counts_as_fail(self, tmp_path):
        t = GoldenTask(id="slow", cmd="sleep 5", timeout_sec=0.2)
        assert run_task(t, 0, tmp_path) is False


class TestEvaluateReal:
    def test_end_to_end_example_set(self):
        tasks = load_tasks(EXAMPLES / "example_tasks.yaml")
        report = evaluate(tasks, SEEDS, base_dir=".", label="test")
        by_id = {t.task_id: t for t in report.tasks}
        assert by_id["deterministic-pass"].c == 8
        assert by_id["deterministic-pass"].pass_at_1 == 1.0
        assert by_id["flaky-3-of-4"].c == 6  # seeds 1,2,3,5,6,7
        assert by_id["flaky-3-of-4"].pass_at_1 == pytest.approx(0.75)
        assert by_id["end-state-checked"].c == 4  # odd seeds
        # weighted: (1*1.0 + 2*0.75 + 1*0.5)/4 = 0.75
        assert report.weighted_pass_at_1 == pytest.approx(0.75)
        # pass^8 exposes the flaky task: not consistent across all 8 seeds
        assert by_id["flaky-3-of-4"].pass_hat(8) == 0.0
        assert report.fully_consistent == 1  # only deterministic-pass


class TestEvaluateInjected:
    def test_injected_runner_counts_passes(self):
        # runner passes on even seeds only -> 4 of 8
        class P:
            def __init__(self, rc):
                self.returncode = rc
                self.stdout = self.stderr = ""

        def fake(cmd, **kw):
            seed = int(kw["env"]["AWH_SEED"])
            return P(0 if seed % 2 == 0 else 1)

        tasks = [GoldenTask(id="t", cmd="x")]
        report = evaluate(tasks, SEEDS, runner=fake)
        assert report.tasks[0].c == 4

    def test_oserror_runner_is_fail(self):
        def boom(cmd, **kw):
            raise OSError("no shell")

        report = evaluate([GoldenTask(id="t", cmd="x")], [0, 1], runner=boom)
        assert report.tasks[0].c == 0


class TestReportSerialization:
    def test_roundtrip_preserves_counts(self):
        tasks = load_tasks(EXAMPLES / "example_tasks.yaml")
        report = evaluate(tasks, SEEDS, base_dir=".")
        data = report.to_dict()
        restored = EvalReport.from_dict(data)
        a = {t.task_id: (t.n, t.c) for t in report.tasks}
        b = {t.task_id: (t.n, t.c) for t in restored.tasks}
        assert a == b
        assert data["aggregate"]["weighted_pass_at_1"] == pytest.approx(0.75)


def _report(label, pairs, k=5):
    # pairs: {task_id: (n, c, weight)}
    tasks = [
        TaskResult(
            task_id=tid, weight=w, seeds=list(range(n)), passes=[True] * c + [False] * (n - c)
        )
        for tid, (n, c, w) in pairs.items()
    ]
    return EvalReport(tasks=tasks, seeds=list(range(k)), k=k, label=label)


class TestGate:
    def test_regression_blocks(self):
        base = _report("base", {"a": (5, 5, 1), "b": (5, 4, 1)})
        cur = _report("cur", {"a": (5, 5, 1), "b": (5, 1, 1)})  # b dropped 0.8 -> 0.2
        g = gate(cur, base)
        assert not g.ok
        assert any(r["task_id"] == "b" for r in g.regressions)
        assert "FAIL" in g.message

    def test_no_regression_passes(self):
        base = _report("base", {"a": (5, 4, 1)})
        cur = _report("cur", {"a": (5, 5, 1)})  # improved
        assert gate(cur, base).ok

    def test_threshold_tolerates_noise(self):
        base = _report("base", {"a": (10, 8, 1)})  # 0.8
        cur = _report("cur", {"a": (10, 7, 1)})  # 0.7, drop 0.1
        assert not gate(cur, base, max_regression=0.05).ok
        assert gate(cur, base, max_regression=0.15).ok  # within tolerated noise

    def test_gateresult_is_truthy(self):
        base = _report("base", {"a": (5, 5, 1)})
        cur = _report("cur", {"a": (5, 5, 1)})
        assert bool(gate(cur, base)) is True


def test_subprocess_module_importable():
    # guard: default runner is the stdlib one
    assert run_task.__defaults__[-1] is subprocess.run
