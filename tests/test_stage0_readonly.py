"""Tests for read-only test enforcement (chmod layer + deny-write policy layer)."""

from __future__ import annotations

import json

from harness.stage0_verification import readonly
from harness.stage0_verification.policy import Policy, evaluate_event


def _make_tree(root):
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
    (root / "test_b.py").write_text("def test_b():\n    assert True\n")
    (root / "conftest.py").write_text("import pytest\n")
    (root / "src.py").write_text("x = 1\n")  # not a test -> stays writable
    (root / "score_secret.py").write_text("ANSWER = 42\n")  # scoring file


class TestChmodLayer:
    def test_lock_makes_tests_readonly_and_verifies(self, tmp_path):
        _make_tree(tmp_path)
        report = readonly.lock_tests(tmp_path)
        assert "test_b.py" in report.locked
        assert "tests/test_a.py" in report.locked
        assert "conftest.py" in report.locked
        assert report.failed == []
        # real evidence: a non-privileged write is refused
        assert readonly.verify_unwritable(tmp_path / "test_b.py")
        assert readonly.is_readonly(tmp_path / "test_b.py")
        # a non-test file is untouched
        assert not readonly.is_readonly(tmp_path / "src.py")

    def test_make_writable_restores(self, tmp_path):
        _make_tree(tmp_path)
        readonly.lock_tests(tmp_path)
        assert readonly.is_readonly(tmp_path / "test_b.py")
        readonly.make_writable(tmp_path / "test_b.py")
        assert not readonly.is_readonly(tmp_path / "test_b.py")
        assert not readonly.verify_unwritable(tmp_path / "test_b.py")

    def test_find_targets_globs(self, tmp_path):
        _make_tree(tmp_path)
        found = {p.name for p in readonly.find_targets(tmp_path)}
        assert {"test_a.py", "test_b.py", "conftest.py"} <= found
        assert "src.py" not in found

    def test_hidden_mode_seals_scoring(self, tmp_path):
        _make_tree(tmp_path)
        report = readonly.lock_tests(tmp_path, scoring_globs=("score*.py",), hidden=True)
        assert "score_secret.py" in report.hidden
        # 0o000 -> unreadable
        assert readonly.verify_unwritable(tmp_path / "score_secret.py")

    def test_scoring_readonly_when_not_hidden(self, tmp_path):
        _make_tree(tmp_path)
        report = readonly.lock_tests(tmp_path, scoring_globs=("score*.py",), hidden=False)
        assert "score_secret.py" in report.locked
        assert readonly.is_readonly(tmp_path / "score_secret.py")


class TestPolicyAugmentation:
    def test_writes_and_merges_policy(self, tmp_path):
        p = readonly.write_policy_augmentation(tmp_path, ["test_b.py", "tests/test_a.py"])
        data = json.loads(p.read_text())
        assert set(data["deny_write_globs"]) == {"test_b.py", "tests/test_a.py"}
        # merge, not overwrite
        readonly.write_policy_augmentation(tmp_path, ["conftest.py"])
        data2 = json.loads(p.read_text())
        assert "conftest.py" in data2["deny_write_globs"]
        assert "test_b.py" in data2["deny_write_globs"]


class TestDenyWritePolicy:
    def _pol(self):
        return Policy(deny_write_globs=["test_*.py", "tests/*"])

    def test_edit_locked_test_blocked(self):
        ev = {"tool_name": "Edit", "tool_input": {"file_path": "test_core.py"}}
        d = evaluate_event(ev, self._pol())
        assert d.block and "read-only" in d.reason.lower()

    def test_read_locked_test_allowed(self):
        # tests must remain readable so they can run; only writes are denied
        ev = {"tool_name": "Read", "tool_input": {"file_path": "test_core.py"}}
        assert evaluate_event(ev, self._pol()).allow

    def test_write_non_test_allowed(self):
        ev = {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}}
        assert evaluate_event(ev, self._pol()).allow

    def test_bash_redirect_into_test_blocked(self):
        ev = {"tool_name": "Bash", "tool_input": {"command": "echo pass > test_core.py"}}
        assert evaluate_event(ev, self._pol()).block

    def test_bash_sed_inplace_test_blocked(self):
        ev = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/assert/pass#/' test_core.py"},
        }
        assert evaluate_event(ev, self._pol()).block

    def test_bash_read_test_allowed(self):
        ev = {"tool_name": "Bash", "tool_input": {"command": "cat test_core.py"}}
        assert evaluate_event(ev, self._pol()).allow

    def test_no_deny_write_globs_means_no_block(self):
        ev = {"tool_name": "Edit", "tool_input": {"file_path": "test_core.py"}}
        assert evaluate_event(ev, Policy()).allow  # default has empty deny_write_globs
