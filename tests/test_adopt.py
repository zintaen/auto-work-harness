"""Tests for `awh adopt` — the one-command Stage-0 scaffold."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from harness.adopt import scaffold
from harness.cli import main
from harness.stage1_measurement.goldenset import load_tasks

HARNESS_ROOT = Path(__file__).resolve().parents[1]


def _mkrepo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    (repo / ".git").mkdir(parents=True)  # look like a git repo
    return repo


def test_scaffold_creates_all_stage0_files(tmp_path):
    repo = _mkrepo(tmp_path)
    report = scaffold(repo, HARNESS_ROOT)

    settings = repo / ".claude" / "settings.json"
    assert settings.exists()
    assert (repo / ".awh" / "gate.sh").exists()
    assert (repo / ".awh" / "goldenset.yaml").exists()
    assert (repo / ".awh" / "policy.json").exists()
    assert report.is_git is True
    # everything is reported as created on a fresh repo
    assert any("settings.json" in c for c in report.created)
    assert not report.skipped


def test_settings_has_absolute_harness_path_substituted(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    text = (repo / ".claude" / "settings.json").read_text()
    assert "__AWH_ROOT__" not in text  # placeholder fully rendered
    assert str(HARNESS_ROOT) in text  # points back at this harness
    json.loads(text)  # valid JSON


def test_gate_is_executable_and_fails_closed(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    gate = repo / ".awh" / "gate.sh"
    assert gate.stat().st_mode & stat.S_IXUSR  # executable
    # the stub must fail on purpose so an un-edited gate never green-lights a stop
    assert "exit 1" in gate.read_text()


def test_policy_is_valid_and_denies_test_writes(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    policy = json.loads((repo / ".awh" / "policy.json").read_text())
    assert "deny_write_globs" in policy
    assert any("test" in g for g in policy["deny_write_globs"])


def test_seeded_goldenset_parses_with_the_real_loader(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    tasks = load_tasks(repo / ".awh" / "goldenset.yaml")  # must satisfy the Stage-1 parser
    assert len(tasks) >= 1
    assert all(t.timeout_sec > 0 for t in tasks)  # every task is hang-bounded


def test_idempotent_second_run_skips_existing_and_never_clobbers(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    # user edits the gate; a re-run must not overwrite it
    gate = repo / ".awh" / "gate.sh"
    gate.write_text("#!/bin/sh\nnpm test\n")
    report2 = scaffold(repo, HARNESS_ROOT)
    assert gate.read_text() == "#!/bin/sh\nnpm test\n"  # preserved
    assert any("gate.sh" in s for s in report2.skipped)
    # an existing settings.json is not clobbered — ours lands beside it
    assert (repo / ".claude" / "settings.awh.json").exists()


def test_force_overwrites_settings(tmp_path):
    repo = _mkrepo(tmp_path)
    scaffold(repo, HARNESS_ROOT)
    (repo / ".claude" / "settings.json").write_text("{}")
    scaffold(repo, HARNESS_ROOT, force=True)
    assert "__AWH_ROOT__" not in (repo / ".claude" / "settings.json").read_text()
    assert not (repo / ".claude" / "settings.awh.json").exists()


def test_non_directory_repo_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="not a directory"):
        scaffold(missing, HARNESS_ROOT)


def test_non_git_repo_flagged(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    report = scaffold(repo, HARNESS_ROOT)
    assert report.is_git is False
    assert "not a git repo" in report.summary()


def test_cli_adopt_smoke(tmp_path, capsys):
    repo = _mkrepo(tmp_path)
    rc = main(["adopt", str(repo)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "scaffolded Stage-0 gates" in out
    assert "awh maturity log" in out  # prints the next-steps checklist
    assert (repo / ".claude" / "settings.json").exists()
