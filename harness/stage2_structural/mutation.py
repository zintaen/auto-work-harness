"""A small, dependency-free mutation tester.

Mutation testing scores *test-suite quality* by injecting mutants (off-by-one,
flipped comparison/boolean/arithmetic operators) and checking the suite kills
each one. It is the complement to property-based testing: PBT stops an agent
passing by memorizing test inputs; mutation testing stops an agent passing with
tautological/weak tests (``assert isinstance(result, int)``) that a coverage
number would call "tested".

``mutate_source`` is pure (AST in -> list of single-mutation variants out) and
exhaustively unit-tested. ``run_mutation`` applies each mutant to a target file,
runs the test command, and restores the original — the standard mutate-run-restore
loop (mutmut/cosmic-ray), here with zero third-party deps so it runs in any
sandbox. For large suites, prefer mutmut/cosmic-ray; this is the always-available
baseline and the tested reference.
"""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Mutant", "MutationReport", "mutate_source", "run_mutation"]

# operator -> replacement (single, opinionated mutant per site)
_BINOP = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.Mod: ast.Mult,
}
_CMPOP = {
    ast.Lt: ast.GtE,
    ast.LtE: ast.Gt,
    ast.Gt: ast.LtE,
    ast.GtE: ast.Lt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}
_BOOLOP = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass(frozen=True)
class Mutant:
    index: int
    description: str
    source: str


class _Mutator(ast.NodeTransformer):
    """Applies the ``target``-th mutation; ``target=-1`` mutates nothing (count pass)."""

    def __init__(self, target: int):
        self.target = target
        self.i = 0
        self.desc: str | None = None

    def _site(self, label: str) -> bool:
        idx = self.i
        self.i += 1
        if idx == self.target:
            self.desc = label
            return True
        return False

    def visit_BinOp(self, node: ast.BinOp):
        self.generic_visit(node)
        repl = _BINOP.get(type(node.op))
        if repl and self._site(f"BinOp {type(node.op).__name__}->{repl.__name__}"):
            node.op = repl()
        return node

    def visit_Compare(self, node: ast.Compare):
        self.generic_visit(node)
        if node.ops:
            repl = _CMPOP.get(type(node.ops[0]))
            if repl and self._site(f"Compare {type(node.ops[0]).__name__}->{repl.__name__}"):
                node.ops[0] = repl()
        return node

    def visit_BoolOp(self, node: ast.BoolOp):
        self.generic_visit(node)
        repl = _BOOLOP.get(type(node.op))
        if repl and self._site(f"BoolOp {type(node.op).__name__}->{repl.__name__}"):
            node.op = repl()
        return node

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, bool):
            if self._site(f"Constant {node.value}->{not node.value}"):
                return ast.copy_location(ast.Constant(value=not node.value), node)
        elif isinstance(node.value, int) and self._site(f"Constant {node.value}->{node.value + 1}"):
            return ast.copy_location(ast.Constant(value=node.value + 1), node)
        return node


def _count_sites(src: str) -> int:
    m = _Mutator(target=-1)
    m.visit(ast.parse(src))
    return m.i


def mutate_source(src: str) -> list[Mutant]:
    """Return one Mutant per mutation site (a single mutation each)."""
    total = _count_sites(src)
    mutants: list[Mutant] = []
    for i in range(total):
        mut = _Mutator(target=i)
        tree = mut.visit(ast.parse(src))
        ast.fix_missing_locations(tree)
        mutants.append(Mutant(index=i, description=mut.desc or "?", source=ast.unparse(tree)))
    return mutants


@dataclass
class MutationReport:
    total: int
    killed: int
    survived: list[Mutant] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.killed / self.total if self.total else 1.0

    def summary(self) -> str:
        s = f"mutation score {self.score:.0%} ({self.killed}/{self.total} killed)"
        if self.survived:
            s += f"; {len(self.survived)} survived (weak tests): " + ", ".join(
                m.description for m in self.survived[:5]
            )
        return s


def run_mutation(
    target_file: str | Path,
    test_cmd: str,
    *,
    workdir: str | Path | None = None,
    runner=subprocess.run,
    timeout: float = 60.0,
) -> MutationReport:
    """Mutate ``target_file`` one site at a time, run ``test_cmd``, restore.

    A mutant is *killed* if ``test_cmd`` exits non-zero while it is in place. A
    surviving mutant means the suite did not detect that change — a gap in the
    tests. Returns a MutationReport; the original file is always restored.
    """
    target = Path(target_file)
    original = target.read_text()
    mutants = mutate_source(original)
    killed = 0
    survived: list[Mutant] = []
    try:
        for m in mutants:
            target.write_text(m.source)
            try:
                proc = runner(
                    test_cmd,
                    shell=True,
                    cwd=str(workdir) if workdir else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                rc = 124  # a hang counts as "killed" (the change broke something)
            if rc != 0:
                killed += 1
            else:
                survived.append(m)
    finally:
        target.write_text(original)
    return MutationReport(total=len(mutants), killed=killed, survived=survived)
