"""Tests for the planner->worker->verifier pipeline (real repo, stub + real verifier)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.stage2_structural.verifier import (
    StubBackend,
    Verifier,
    code_review_rubric,
)
from harness.stage3_parallel.pipeline import (
    Pipeline,
    PipelineTask,
    WorkerResult,
    plan,
)
from harness.stage3_parallel.worktree import WorktreeManager


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.local")
    _git(root, "config", "user.name", "T")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "file.txt").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def make_worker(fname, content, ok=True, commit=True):
    def worker(wt):
        if commit:
            (Path(wt.path) / fname).write_text(content)
            _git(wt.path, "add", "-A")
            _git(wt.path, "commit", "-qm", f"add {fname}")
        return WorkerResult(
            ok=ok, artifact=f"diff for {fname}", summary=f"wrote {fname}", spec="spec"
        )

    return worker


PASS = lambda artifact, spec: SimpleNamespace(passed=True, overall_score=0.9, summary="ok")  # noqa: E731
FAIL = lambda artifact, spec: SimpleNamespace(passed=False, overall_score=0.2, summary="rejected")  # noqa: E731


class TestHappyPath:
    def test_all_independent_tasks_merge(self, repo):
        mgr = WorktreeManager(repo)
        tasks = [
            PipelineTask("a", make_worker("a.txt", "A")),
            PipelineTask("b", make_worker("b.txt", "B")),
            PipelineTask("c", make_worker("c.txt", "C")),
        ]
        report = Pipeline(mgr, PASS, integration_branch="main").run(tasks)
        assert sorted(report.merged_ids) == ["a", "b", "c"]
        for f in ("a.txt", "b.txt", "c.txt"):
            assert (repo / f).exists()
        # merged worktrees cleaned up by default
        assert mgr.list() == []


class TestGating:
    def test_verify_failure_blocks_merge(self, repo):
        mgr = WorktreeManager(repo)
        tasks = [PipelineTask("a", make_worker("a.txt", "A"))]
        report = Pipeline(mgr, FAIL, integration_branch="main").run(tasks)
        assert report.merged_ids == []
        assert report.outcomes[0].status == "verify_failed"
        assert not (repo / "a.txt").exists()  # nothing merged
        # blocked worktree kept for inspection
        assert "a" in {w.task_id for w in mgr.list()}

    def test_selective_verifier(self, repo):
        mgr = WorktreeManager(repo)

        def selective(artifact, spec):
            ok = "good" in artifact
            return SimpleNamespace(passed=ok, overall_score=0.9 if ok else 0.1, summary="")

        tasks = [
            PipelineTask("good", make_worker("good.txt", "G")),
            PipelineTask("bad", make_worker("bad.txt", "B")),
        ]
        # artifacts are "diff for good.txt" / "diff for bad.txt"
        report = Pipeline(mgr, selective, integration_branch="main").run(tasks)
        statuses = {o.task_id: o.status for o in report.outcomes}
        assert statuses["good"] == "merged"
        assert statuses["bad"] == "verify_failed"

    def test_worker_failure(self, repo):
        mgr = WorktreeManager(repo)
        tasks = [PipelineTask("a", make_worker("a.txt", "A", ok=False, commit=False))]
        report = Pipeline(mgr, PASS).run(tasks)
        assert report.outcomes[0].status == "worker_failed"

    def test_worker_exception_isolated(self, repo):
        mgr = WorktreeManager(repo)

        def boom(wt):
            raise RuntimeError("kaboom")

        tasks = [PipelineTask("a", boom), PipelineTask("b", make_worker("b.txt", "B"))]
        report = Pipeline(mgr, PASS).run(tasks)
        statuses = {o.task_id: o.status for o in report.outcomes}
        assert statuses["a"] == "error" and "kaboom" in next(
            o.reason for o in report.outcomes if o.task_id == "a"
        )
        assert statuses["b"] == "merged"  # one worker's crash doesn't sink the others


class TestSerializedMergeConflicts:
    def test_conflict_is_caught_by_integration_layer(self, repo):
        mgr = WorktreeManager(repo)
        # both tasks edit the SAME file -> second merge must conflict, not corrupt main
        tasks = [
            PipelineTask("a", make_worker("file.txt", "AAA\n")),
            PipelineTask("b", make_worker("file.txt", "BBB\n")),
        ]
        report = Pipeline(mgr, PASS, integration_branch="main").run(tasks)
        statuses = {o.task_id: o.status for o in report.outcomes}
        assert statuses["a"] == "merged"
        assert statuses["b"] == "conflict"
        # main is clean and holds the first merge, not a corrupted half-merge
        assert _git(repo, "status", "--porcelain").stdout.strip() == ""
        assert (repo / "file.txt").read_text() == "AAA\n"


class TestRealVerifierIntegration:
    def test_pipeline_with_real_stage2_verifier(self, repo):
        mgr = WorktreeManager(repo)
        rub = code_review_rubric()
        crit = {c.name: {"score": 0.9, "pass": True} for c in rub.criteria}
        verifier = Verifier(backend=StubBackend({"criteria": crit, "summary": "lgtm"}), rubric=rub)
        report = Pipeline(mgr, verifier, integration_branch="main").run(
            [PipelineTask("feat", make_worker("feat.txt", "X"), spec="add feat")]
        )
        assert report.outcomes[0].status == "merged"
        assert report.outcomes[0].verifier_score == pytest.approx(0.9)


class TestPlan:
    def test_duplicate_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            plan(
                [PipelineTask("x", make_worker("a", "a")), PipelineTask("x", make_worker("b", "b"))]
            )

    def test_summary(self, repo):
        mgr = WorktreeManager(repo)
        report = Pipeline(mgr, PASS).run([PipelineTask("a", make_worker("a.txt", "A"))])
        assert "1/1 merged" in report.summary()
