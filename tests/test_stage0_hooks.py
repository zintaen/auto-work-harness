"""Tests for the Stage-0 hook entry points (pretooluse, stop_gate, posttooluse)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from harness.stage0_verification.hooks import (
    posttooluse_format,
    pretooluse_deny,
    stop_gate,
)


@dataclass
class FakeProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class TestPreToolUseHook:
    def test_blocks_destructive(self, tmp_path):
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
        code, out, err = pretooluse_deny.main(ev, cwd=str(tmp_path))
        assert code == 2
        assert "policy" in err.lower()

    def test_allows_safe(self, tmp_path):
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        code, out, err = pretooluse_deny.main(ev, cwd=str(tmp_path))
        assert code == 0 and err == ""

    def test_blocks_secret_read(self, tmp_path):
        ev = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x/.env"}})
        code, _, err = pretooluse_deny.main(ev, cwd=str(tmp_path))
        assert code == 2 and "secret" in err.lower()

    def test_malformed_input_fails_open(self, tmp_path):
        code, out, err = pretooluse_deny.main("not json{", cwd=str(tmp_path))
        assert code == 0

    def test_empty_input(self, tmp_path):
        code, _, _ = pretooluse_deny.main("", cwd=str(tmp_path))
        assert code == 0


class TestStopGateHook:
    def test_no_gate_configured_allows_stop(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AWH_GATE_CMD", raising=False)
        code, _, _ = stop_gate.main("{}", cwd=str(tmp_path))
        assert code == 0

    def test_failing_gate_blocks_stop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWH_GATE_CMD", "pytest")

        def fake_runner(cmd, **kw):
            return FakeProc(returncode=1, stdout="2 failed, 5 passed\n")

        code, _, err = stop_gate.main("{}", cwd=str(tmp_path), runner=fake_runner)
        assert code == 2
        assert "evidence gate" in err.lower()
        assert "2 failed" in err

    def test_passing_gate_allows_stop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWH_GATE_CMD", "pytest")
        code, _, _ = stop_gate.main(
            "{}", cwd=str(tmp_path), runner=lambda *a, **k: FakeProc(returncode=0)
        )
        assert code == 0

    def test_loop_guard_honors_stop_hook_active(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWH_GATE_CMD", "pytest")
        called = {"n": 0}

        def fake_runner(cmd, **kw):
            called["n"] += 1
            return FakeProc(returncode=1)

        ev = json.dumps({"stop_hook_active": True})
        code, _, _ = stop_gate.main(ev, cwd=str(tmp_path), runner=fake_runner)
        assert code == 0
        assert called["n"] == 0  # gate must not even run on the re-entrant stop

    def test_real_subprocess_failing_command(self, tmp_path, monkeypatch):
        # exercise the real subprocess path, not just the injected runner
        monkeypatch.setenv("AWH_GATE_CMD", "sh -c 'echo boom; exit 7'")
        code, _, err = stop_gate.main("{}", cwd=str(tmp_path))
        assert code == 2 and "exited 7" in err and "boom" in err


class TestPostToolUseHook:
    def test_formats_python_file(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("x=1\n")
        ev = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(f)}})
        ran = {}

        def fake_runner(cmd, **kw):
            ran["cmd"] = cmd
            return FakeProc(returncode=0)

        code, out, _ = posttooluse_format.main(ev, cwd=str(tmp_path), runner=fake_runner)
        assert code == 0
        assert ran["cmd"][:2] == ["ruff", "format"]
        assert "formatted x.py" in out

    def test_ignores_non_edit_tools(self, tmp_path):
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        code, out, _ = posttooluse_format.main(ev, cwd=str(tmp_path))
        assert code == 0 and out == ""

    def test_missing_file_is_noop(self, tmp_path):
        ev = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "nope.py"}})
        code, out, _ = posttooluse_format.main(ev, cwd=str(tmp_path))
        assert code == 0 and out == ""

    def test_non_python_skipped(self, tmp_path):
        f = tmp_path / "x.md"
        f.write_text("# hi\n")
        ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
        code, out, _ = posttooluse_format.main(ev, cwd=str(tmp_path))
        assert code == 0 and out == ""
