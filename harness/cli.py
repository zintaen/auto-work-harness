"""`awh` — command-line entry point for the auto-work-harness.

Subcommands map 1:1 to the stages so the toolkit is usable from a Makefile, a
CI job, or an AUTO_WORK gate script:

    awh lock <root>              Stage 0  make test/scoring files read-only
    awh firewall                 Stage 0  render the default-deny egress script
    awh power --baseline ...     Stage 1  seeds-for-power calculator
    awh eval <tasks>             Stage 1  multi-seed eval + regression gate
    awh mutate <file> --test-cmd Stage 2  mutation score for a test suite
    awh worktree <op> ...        Stage 3  manage per-task worktrees
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import __version__


def _cmd_lock(args) -> int:
    from harness.stage0_verification.readonly import lock_tests, write_policy_augmentation

    report = lock_tests(
        args.root,
        scoring_globs=tuple(args.scoring) if args.scoring else None,
        hidden=args.hidden,
    )
    print(report.summary())
    if args.write_policy and report.recommended_write_globs:
        p = write_policy_augmentation(args.root, report.recommended_write_globs)
        print(f"wrote deny_write_globs -> {p}")
    return 0 if not report.failed else 1


def _cmd_firewall(args) -> int:
    from harness.stage0_verification.egress import render_init_script

    script = render_init_script(args.domain or None)
    if args.out:
        Path(args.out).write_text(script)
        print(f"wrote {args.out}")
    else:
        print(script)
    return 0


def _cmd_power(args) -> int:
    from harness.common.stats import seeds_for_power

    res = seeds_for_power(args.baseline, args.mde, alpha=args.alpha, power=args.power)
    print(res.summary())
    return 0


def _cmd_eval(args) -> int:
    from harness.stage1_measurement.goldenset import load_tasks
    from harness.stage1_measurement.runner import EvalReport, evaluate, gate

    tasks = load_tasks(args.tasks)
    seeds = list(range(args.seeds))
    report = evaluate(tasks, seeds, base_dir=args.base_dir, label=args.label or "eval")
    print(report.summary())
    if args.out:
        Path(args.out).write_text(json.dumps(report.to_dict(), indent=2))
        print(f"wrote {args.out}")
    if args.baseline:
        base = EvalReport.from_dict(json.loads(Path(args.baseline).read_text()))
        g = gate(report, base, max_regression=args.max_regression)
        print(g.message)
        return 0 if g.ok else 1
    return 0


def _cmd_mutate(args) -> int:
    from harness.stage2_structural.mutation import run_mutation

    report = run_mutation(args.target, args.test_cmd, workdir=args.workdir)
    print(report.summary())
    return 0 if report.score >= args.min_score else 1


def _cmd_worktree(args) -> int:
    from harness.stage3_parallel.worktree import WorktreeManager

    mgr = WorktreeManager(args.repo)
    if args.op == "create":
        wt = mgr.create(args.task_id, base_ref=args.base)
        print(f"created {wt.branch} at {wt.path}")
    elif args.op == "list":
        for w in mgr.list():
            print(f"{w.task_id}\t{w.branch}\t{w.path}")
    elif args.op == "remove":
        mgr.remove(args.task_id, force=args.force, delete_branch=args.delete_branch)
        print(f"removed {args.task_id}")
    elif args.op == "merge":
        res = mgr.merge(args.task_id, into=args.into)
        print(res.message)
        return 0 if res.ok else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="awh", description="auto-work-harness CLI")
    p.add_argument("--version", action="version", version=f"awh {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    lk = sub.add_parser("lock", help="Stage 0: make test/scoring files read-only")
    lk.add_argument("root")
    lk.add_argument("--scoring", nargs="*", help="extra scoring-file globs")
    lk.add_argument("--hidden", action="store_true", help="seal scoring files unreadable")
    lk.add_argument("--write-policy", action="store_true", help="augment .awh/policy.json")
    lk.set_defaults(func=_cmd_lock)

    fw = sub.add_parser("firewall", help="Stage 0: render default-deny egress script")
    fw.add_argument("--domain", nargs="*", help="allowlisted domains (default: built-in set)")
    fw.add_argument("--out", help="write script to this path")
    fw.set_defaults(func=_cmd_firewall)

    pw = sub.add_parser("power", help="Stage 1: seeds needed to detect an effect")
    pw.add_argument("--baseline", type=float, required=True)
    pw.add_argument("--mde", type=float, required=True, help="minimum detectable effect")
    pw.add_argument("--alpha", type=float, default=0.05)
    pw.add_argument("--power", type=float, default=0.80)
    pw.set_defaults(func=_cmd_power)

    ev = sub.add_parser("eval", help="Stage 1: multi-seed eval + regression gate")
    ev.add_argument("tasks", help="golden-set YAML file or directory")
    ev.add_argument("--seeds", type=int, default=5)
    ev.add_argument("--base-dir", default=".")
    ev.add_argument("--label", default="")
    ev.add_argument("--out", help="write the JSON report here")
    ev.add_argument("--baseline", help="baseline report JSON to gate against")
    ev.add_argument("--max-regression", type=float, default=0.0)
    ev.set_defaults(func=_cmd_eval)

    mu = sub.add_parser("mutate", help="Stage 2: mutation score for a test suite")
    mu.add_argument("target", help="source file to mutate")
    mu.add_argument("--test-cmd", required=True, help="command that fails when a mutant is killed")
    mu.add_argument("--workdir", default=None)
    mu.add_argument("--min-score", type=float, default=1.0)
    mu.set_defaults(func=_cmd_mutate)

    wt = sub.add_parser("worktree", help="Stage 3: manage per-task worktrees")
    wt.add_argument("op", choices=["create", "list", "remove", "merge"])
    wt.add_argument("--repo", default=".")
    wt.add_argument("--task-id", default="")
    wt.add_argument("--base", default="HEAD")
    wt.add_argument("--into", default="main")
    wt.add_argument("--force", action="store_true")
    wt.add_argument("--delete-branch", action="store_true")
    wt.set_defaults(func=_cmd_worktree)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
