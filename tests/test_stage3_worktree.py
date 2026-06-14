"""Tests for the git worktree manager — run against a real temporary repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.stage3_parallel.worktree import WorktreeError, WorktreeManager


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


class TestCreateList:
    def test_create_and_list(self, repo):
        mgr = WorktreeManager(repo)
        wt = mgr.create("task-a")
        assert wt.branch == "auto/wt/task-a"
        assert wt.path.exists()
        assert len(wt.head) >= 7
        listed = {w.task_id for w in mgr.list()}
        assert "task-a" in listed
        # the main worktree is NOT reported as one of ours
        assert all(w.path.resolve() != repo.resolve() for w in mgr.list())

    def test_duplicate_path_guard(self, repo):
        mgr = WorktreeManager(repo)
        mgr.create("task-a")
        with pytest.raises(WorktreeError, match="already exists"):
            mgr.create("task-a")

    def test_same_branch_collision_guard(self, repo):
        mgr = WorktreeManager(repo)
        mgr.create("task-a")  # checks out auto/wt/task-a
        other = mgr.worktrees_dir / "elsewhere"
        # git structurally refuses to check out the same branch twice
        with pytest.raises(WorktreeError):
            mgr._git("worktree", "add", str(other), "auto/wt/task-a")

    def test_reattach_existing_branch(self, repo):
        mgr = WorktreeManager(repo)
        mgr.create("task-a")
        mgr.remove("task-a", delete_branch=False)  # branch survives
        wt = mgr.create("task-a")  # should re-attach the existing branch
        assert wt.branch == "auto/wt/task-a"


class TestMerge:
    def _commit_in(self, path, content, msg):
        (Path(path) / "file.txt").write_text(content)
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", msg)

    def test_clean_merge(self, repo):
        mgr = WorktreeManager(repo)
        wt = mgr.create("feat")
        (wt.path / "new.txt").write_text("hello\n")
        _git(wt.path, "add", "-A")
        _git(wt.path, "commit", "-qm", "add new.txt")
        res = mgr.merge("feat", into="main")
        assert res.ok and not res.conflicts
        assert (repo / "new.txt").exists()  # change landed on main

    def test_conflict_is_aborted_and_reported(self, repo):
        mgr = WorktreeManager(repo)
        a = mgr.create("a")
        b = mgr.create("b")
        self._commit_in(a.path, "A-version\n", "a edits file")
        self._commit_in(b.path, "B-version\n", "b edits file")
        assert mgr.merge("a", into="main").ok
        res = mgr.merge("b", into="main")
        assert not res.ok
        assert "file.txt" in res.conflicts
        # repo must be left clean (merge aborted, not half-applied)
        status = _git(repo, "status", "--porcelain").stdout
        assert status.strip() == ""
        assert (repo / "file.txt").read_text() == "A-version\n"


class TestLifecycle:
    def test_remove(self, repo):
        mgr = WorktreeManager(repo)
        wt = mgr.create("gone")
        assert wt.path.exists()
        mgr.remove("gone")
        assert not wt.path.exists()
        assert "gone" not in {w.task_id for w in mgr.list()}

    def test_write_isolation(self, repo):
        mgr = WorktreeManager(repo)
        mgr.create("iso")
        env = mgr.write_isolation("iso", base_port=5000)
        assert 5000 <= int(env["PORT"]) < 6000
        assert (mgr.worktrees_dir / "iso" / ".env.local").exists()
        # port must be DETERMINISTIC (crc32, not salted hash()) across calls
        env2 = mgr.write_isolation("iso", base_port=5000)
        assert env2["PORT"] == env["PORT"]

    def test_disk_usage_nonnegative(self, repo):
        mgr = WorktreeManager(repo)
        mgr.create("d")
        assert mgr.disk_usage() > 0

    def test_not_a_repo_raises(self, tmp_path):
        with pytest.raises(WorktreeError, match="not a git repository"):
            WorktreeManager(tmp_path / "nope")
