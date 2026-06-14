"""Smoke tests for the `awh` CLI glue across all four stages."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.cli import main

EXAMPLES = (
    Path(__file__).resolve().parents[1] / "harness" / "goldenset" / "tasks" / "example_tasks.yaml"
)


def test_firewall(capsys):
    assert main(["firewall"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("#!/usr/bin/env bash")
    assert "OUTPUT DROP" in out


def test_power(capsys):
    assert main(["power", "--baseline", "0.5", "--mde", "0.2"]) == 0
    assert "seeds" in capsys.readouterr().out.lower()


def test_eval_runs(capsys):
    rc = main(["eval", str(EXAMPLES), "--seeds", "6"])
    assert rc == 0
    assert "pass@1" in capsys.readouterr().out


def test_eval_gate_against_baseline(tmp_path, capsys):
    base = tmp_path / "baseline.json"
    assert main(["eval", str(EXAMPLES), "--seeds", "6", "--out", str(base)]) == 0
    capsys.readouterr()
    # gating against an identical baseline => no regression => exit 0
    rc = main(["eval", str(EXAMPLES), "--seeds", "6", "--baseline", str(base)])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_lock(tmp_path, capsys):
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n")
    assert main(["lock", str(tmp_path)]) == 0
    assert "locked" in capsys.readouterr().out
    # file is now read-only
    import os
    import stat

    mode = os.stat(tmp_path / "test_x.py").st_mode
    assert not (mode & stat.S_IWUSR)


def test_mutate_strong_and_weak(tmp_path, capsys):
    (tmp_path / "m.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "t_strong.py").write_text("from m import add\nassert add(2, 3) == 5\n")
    (tmp_path / "t_weak.py").write_text("from m import add\nassert isinstance(add(1, 2), int)\n")
    rc_strong = main(
        [
            "mutate",
            str(tmp_path / "m.py"),
            "--test-cmd",
            "python3 -B t_strong.py",
            "--workdir",
            str(tmp_path),
        ]
    )
    assert rc_strong == 0  # score 1.0 >= default min 1.0
    capsys.readouterr()
    rc_weak = main(
        [
            "mutate",
            str(tmp_path / "m.py"),
            "--test-cmd",
            "python3 -B t_weak.py",
            "--workdir",
            str(tmp_path),
        ]
    )
    assert rc_weak == 1  # mutant survived -> score < 1.0


def test_worktree_create_list(tmp_path, capsys):
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True, capture_output=True)
    assert main(["worktree", "create", "--repo", str(repo), "--task-id", "t1"]) == 0
    assert main(["worktree", "list", "--repo", str(repo)]) == 0
    assert "t1" in capsys.readouterr().out


def test_no_subcommand_errors():
    with pytest.raises(SystemExit):
        main([])
