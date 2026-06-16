"""Regression tests for the exhaustive edge-case / security audit.

Each test pins a specific bypass or silent-wrong-result that the audit found and
the hardening pass fixed, so none of them can quietly return.
"""

from __future__ import annotations

import math
import subprocess

import pytest

from harness.cli import main as cli_main
from harness.common.stats import two_proportion_power, wilson_interval
from harness.maturity import read_runs, summarize
from harness.stage0_verification.egress import build_iptables_plan
from harness.stage0_verification.hooks import stop_gate
from harness.stage0_verification.policy import Policy, evaluate_event
from harness.stage2_structural.mutation import (
    MutationError,
    MutationReport,
    mutate_source,
    run_mutation,
)
from harness.stage2_structural.scorermix import _clamp, blend
from harness.stage2_structural.verifier import Criterion, Rubric, parse_judgment
from harness.stage3_parallel.pipeline import Pipeline, PipelineTask, WorkerResult
from harness.stage3_parallel.worktree import WorktreeError, WorktreeManager


# --------------------------------------------------------------------------- #
# Stage 0 — policy bypasses
# --------------------------------------------------------------------------- #
def _bash(cmd: str, pol: Policy | None = None) -> bool:
    return evaluate_event({"tool_name": "Bash", "tool_input": {"command": cmd}}, pol).block


def _edit(path: str, pol: Policy) -> bool:
    return evaluate_event({"tool_name": "Edit", "tool_input": {"file_path": path}}, pol).block


class TestPolicyBypasses:
    def test_secret_read_via_redirect_no_space(self):
        assert _bash("cat<.env")  # tokenizer must split on '<'

    def test_deny_write_dot_slash_prefix(self):
        pol = Policy(deny_write_globs=["tests/*", "tests/**"])
        assert _bash("echo x > ./tests/foo.py", pol)
        assert _bash("echo x>tests/foo.py", pol)  # no space around '>'

    def test_deny_write_copy_verb(self):
        pol = Policy(deny_write_globs=["tests/**"])
        assert _bash("cp /tmp/evil.py tests/foo.py", pol)

    def test_edit_deny_write_normalized_paths(self):
        pol = Policy(deny_write_globs=["tests/**"])
        assert _edit("./tests/foo.py", pol)
        assert _edit("/abs/repo/tests/foo.py", pol)
        assert _edit("tests/../tests/foo.py", pol)

    def test_rm_quoted_glob_longflag(self):
        assert _bash("rm -rf '/'")
        assert _bash("rm -rf /*")
        assert _bash("rm --recursive --force /")

    def test_from_dict_non_object_is_safe_default(self):
        assert Policy.from_dict([1, 2, 3]).deny_command_patterns  # non-empty defaults
        assert _bash("rm -rf /", Policy.from_dict([1, 2, 3]))

    def test_from_dict_wrong_typed_field_does_not_disable(self):
        # a bare string must not become list("rm")=['r','m'] (containment off)
        pol = Policy.from_dict({"deny_command_patterns": "rm"})
        assert _bash("rm -rf /", pol)

    def test_no_overblock_regressions(self):
        pol = Policy(deny_write_globs=["tests/**"])
        assert not _bash("rm -rf ./build")
        assert not _bash("rm -rf build/")
        assert not _edit("src/app.py", pol)
        assert not _bash("ls -la")


# --------------------------------------------------------------------------- #
# Stage 0 — egress injection
# --------------------------------------------------------------------------- #
class TestEgressInjection:
    @pytest.mark.parametrize(
        "kw",
        [
            {"domains": ["github.com; rm -rf /"]},
            {"domains": ["$(curl evil)"]},
            {"domains": ["evil.com\nrm -rf ~"]},
            {"domains": ["github.com"], "resolver_ips": ["1.1.1.1; rm x"]},
            {"domains": ["github.com"], "allow_subnets": ["10/8 -j ACCEPT; rm x"]},
        ],
    )
    def test_injection_rejected(self, kw):
        with pytest.raises(ValueError):
            build_iptables_plan(**kw)

    def test_valid_inputs_accepted(self):
        assert build_iptables_plan(["github.com", "api.github.com"], ["8.8.8.8"], ["10.0.0.0/8"])


# --------------------------------------------------------------------------- #
# common — stats guards
# --------------------------------------------------------------------------- #
class TestStatsGuards:
    def test_wilson_rejects_bad_z(self):
        with pytest.raises(ValueError):
            wilson_interval(3, 10, float("nan"))
        with pytest.raises(ValueError):
            wilson_interval(3, 10, 0)

    def test_power_rejects_bad_alpha_power(self):
        with pytest.raises(ValueError):
            two_proportion_power(0.5, 0.1, 0.0, 0.8)
        with pytest.raises(ValueError):
            two_proportion_power(0.5, 0.1, 0.05, 1.0)

    def test_power_zero_delta_after_clamp(self):
        with pytest.raises(ValueError):
            two_proportion_power(0.999999999, 0.5, 0.05, 0.8)


# --------------------------------------------------------------------------- #
# Stage 2 — scorermix / verifier NaN fail-closed
# --------------------------------------------------------------------------- #
class TestScorerNaN:
    def test_clamp_non_finite_fails_to_zero(self):
        assert _clamp(float("nan")) == 0.0
        assert _clamp(float("inf")) == 0.0

    def test_blend_nan_does_not_pass(self):
        b = blend(float("nan"))
        assert b.blended == 0.0 and not b.passed

    def test_blend_rejects_negative_weight(self):
        with pytest.raises(ValueError):
            blend(0.8, 0.5, weights={"deterministic": 1.0, "judge": -1.0})

    def test_verifier_nan_score_fails_closed(self):
        r = Rubric(criteria=[Criterion(name="x", weight=1.0)])
        res = parse_judgment('{"criteria":{"x":{"score":NaN,"pass":true}}}', r)
        assert res.per_criterion["x"]["score"] == 0.0
        assert res.overall_score == 0.0

    def test_verifier_truthy_pass_string_not_honored(self):
        r = Rubric(criteria=[Criterion(name="x", weight=1.0)])
        res = parse_judgment('{"criteria":{"x":{"score":0.2,"pass":"no"}}}', r)
        assert res.per_criterion["x"]["pass"] is False


# --------------------------------------------------------------------------- #
# maturity — ledger robustness
# --------------------------------------------------------------------------- #
class TestMaturityRobustness:
    def test_corrupt_and_forward_compat_lines(self, tmp_path):
        log = tmp_path / "evo.jsonl"
        log.write_text(
            '{"ts":1,"repo":"a","harness_version":"v1"}\n'
            "NOT JSON\n"
            '{"ts":2,"repo":"b","harness_version":"v1","NEWKEY":9}\n'
            '{"ts":3,"missing":"fields"}\n'
            '{"ts":4,"repo":"c","harness_version":"v2"}\n'
            '{"ts":5,"repo":"d","harn'  # truncated
        )
        assert [r.repo for r in read_runs(log)] == ["a", "b", "c"]

    def test_window_non_positive_clamped(self, tmp_path):
        log = tmp_path / "evo.jsonl"
        log.write_text('{"ts":1,"repo":"a","harness_version":"v1"}\n')
        assert summarize(log, window=0).window >= 1  # must not raise / mis-slice


# --------------------------------------------------------------------------- #
# Stage 3 — worktree / pipeline (real temp repo)
# --------------------------------------------------------------------------- #
@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "r"
    d.mkdir()

    def git(*a):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "a@b.c")
    git("config", "user.name", "t")
    (d / "f.txt").write_text("hi\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    return d


class TestWorktreeInjection:
    @pytest.mark.parametrize("bad", ["../../etc/passwd", "sub/evil", "-D x", "", "a..b", "x;rm"])
    def test_task_id_rejected(self, repo, bad):
        m = WorktreeManager(repo)
        with pytest.raises(WorktreeError):
            m.branch_for(bad)

    def test_merge_missing_branch_clean_error(self, repo):
        m = WorktreeManager(repo)
        head = m._current_ref()
        res = m.merge("ghost", into=head)
        assert not res.ok and res.conflicts == [] and "does not exist" in res.message


class TestPipelineGuards:
    def test_missing_integration_branch_fails_fast(self, repo):
        m = WorktreeManager(repo)
        pipe = Pipeline(m, verifier=lambda a, s: True, integration_branch="nonexistent")
        task = PipelineTask(id="t1", worker=lambda wt: WorkerResult(ok=True, artifact="x"))
        with pytest.raises(WorktreeError):
            pipe.run([task])


# --------------------------------------------------------------------------- #
# Stage 2 — mutation robustness
# --------------------------------------------------------------------------- #
class TestMutationRobustness:
    def test_chained_comparison_fully_mutated(self):
        assert len(mutate_source("def f(lo, x, hi):\n    return lo < x < hi\n")) >= 2

    def test_no_mutants_is_not_a_perfect_score(self):
        rep = MutationReport(total=0, killed=0)
        assert math.isnan(rep.score)
        assert "N/A" in rep.summary()

    def test_syntax_error_raises_mutation_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def f(:\n")
        with pytest.raises(MutationError):
            run_mutation(f, "true", require_baseline=False)

    def test_failing_baseline_raises(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("def f():\n    return 1 + 1\n")
        with pytest.raises(MutationError):
            run_mutation(f, "false")  # test cmd fails even on clean source


# --------------------------------------------------------------------------- #
# Stage 0 — hook timeouts (a hung gate must not wedge the turn)
# --------------------------------------------------------------------------- #
class TestStopGateTimeout:
    def test_hung_gate_blocks_with_message(self, tmp_path):
        (tmp_path / ".awh").mkdir()
        (tmp_path / ".awh" / "gate.sh").write_text("sleep 999\n")

        def hang(*a, **k):
            raise subprocess.TimeoutExpired(cmd="gate", timeout=k.get("timeout", 1))

        code, _, err = stop_gate.main("{}", cwd=str(tmp_path), runner=hang)
        assert code == 2 and "did not finish" in err


# --------------------------------------------------------------------------- #
# CLI — known user errors print cleanly, not as a traceback
# --------------------------------------------------------------------------- #
class TestCliCleanErrors:
    def test_bad_seeds_clean_error(self, capsys, tmp_path):
        gs = tmp_path / "g.yaml"
        gs.write_text("tasks:\n  - {id: a, cmd: 'true'}\n")
        rc = cli_main(["eval", str(gs), "--seeds", "0"])
        err = capsys.readouterr().err
        assert rc == 1 and "awh: error:" in err and "seed" in err

    def test_bad_power_arg_clean_error(self, capsys):
        rc = cli_main(["power", "--baseline", "0.5", "--mde", "0"])
        err = capsys.readouterr().err
        assert rc == 1 and "awh: error:" in err


# --------------------------------------------------------------------------- #
# CLI — smoke-test every subcommand's dispatch + handler (was largely uncovered)
# --------------------------------------------------------------------------- #
class TestCliSmoke:
    def test_maturity_report(self, capsys, tmp_path):
        log = tmp_path / "evo.jsonl"
        log.write_text('{"ts":1,"repo":"a","harness_version":"v1"}\n')
        assert cli_main(["maturity", "--log", str(log)]) == 0
        assert "VERDICT" in capsys.readouterr().out

    def test_maturity_log_and_json(self, tmp_path):
        log = tmp_path / "evo.jsonl"
        assert (
            cli_main(["maturity", "log", "--repo", "t/x", "--version", "v1", "--log", str(log)])
            == 0
        )
        assert log.exists()
        assert cli_main(["maturity", "--log", str(log), "--json"]) == 0

    def test_lock_firewall_power(self, capsys, tmp_path):
        assert cli_main(["lock", str(tmp_path)]) == 0
        assert cli_main(["firewall"]) == 0
        assert cli_main(["power", "--baseline", "0.5", "--mde", "0.1"]) == 0
        assert "#!/usr/bin/env bash" in capsys.readouterr().out  # firewall rendered to stdout

    def test_worktree_list(self, repo):
        assert cli_main(["worktree", "list", "--repo", str(repo)]) == 0

    def test_maturity_log_resolves_version(self, tmp_path):
        # no --version -> exercises _harness_version (git short sha, or __version__ fallback)
        log = tmp_path / "evo.jsonl"
        assert cli_main(["maturity", "log", "--repo", "t/y", "--log", str(log)]) == 0

    def test_maturity_log_missing_repo_errors(self, tmp_path):
        log = tmp_path / "evo.jsonl"
        assert cli_main(["maturity", "log", "--log", str(log)]) == 2  # --repo required

    def test_maturity_gate_nonzero_when_not_ready(self, tmp_path):
        log = tmp_path / "evo.jsonl"
        log.write_text('{"ts":1,"repo":"a","harness_version":"v1","categories":["x"]}\n')
        assert cli_main(["maturity", "--log", str(log), "--gate"]) == 1  # not READY

    def test_lock_write_policy_and_firewall_out(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "t_a.py").write_text("def test():\n    pass\n")
        assert cli_main(["lock", str(tmp_path), "--scoring", "tests/**", "--write-policy"]) == 0
        out = tmp_path / "fw.sh"
        assert cli_main(["firewall", "--out", str(out)]) == 0
        assert out.exists()
