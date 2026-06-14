"""Tests for the mutation tester (pure mutate_source + the mutate-run-restore loop)."""

from __future__ import annotations

from harness.stage2_structural.mutation import mutate_source, run_mutation


class TestMutateSource:
    def test_binop_add_to_sub(self):
        muts = mutate_source("def f(a, b):\n    return a + b\n")
        assert len(muts) == 1
        assert "Add->Sub" in muts[0].description
        assert "a - b" in muts[0].source

    def test_compare_and_constant(self):
        muts = mutate_source("def g(x):\n    return x > 0\n")
        descs = {m.description for m in muts}
        srcs = "\n".join(m.source for m in muts)
        assert any("Gt->LtE" in d for d in descs)
        assert any("Constant 0->1" in d for d in descs)
        assert "x <= 0" in srcs and "x > 1" in srcs
        assert len(muts) == 2

    def test_boolop(self):
        muts = mutate_source("def b(x, y):\n    return x and y\n")
        assert any("And->Or" in m.description for m in muts)
        assert any("x or y" in m.source for m in muts)

    def test_bool_constant(self):
        muts = mutate_source("def h():\n    return True\n")
        assert len(muts) == 1
        assert "True->False" in muts[0].description
        assert "return False" in muts[0].source

    def test_no_mutable_sites(self):
        assert mutate_source("def noop():\n    pass\n") == []

    def test_each_mutant_is_single_mutation(self):
        # two independent sites -> each mutant differs from source in exactly one
        src = "def f(a, b):\n    return a + b > 0\n"
        muts = mutate_source(src)
        # sites: BinOp(Add), Compare(Gt), Constant(0) = 3
        assert len(muts) == 3


class TestRunMutation:
    def _project(self, tmp_path, test_body):
        (tmp_path / "m.py").write_text("def add(a, b):\n    return a + b\n")
        (tmp_path / "t.py").write_text(test_body)
        return tmp_path

    def test_strong_test_kills_mutant(self, tmp_path):
        self._project(
            tmp_path,
            "from m import add\nassert add(2, 3) == 5\nassert add(0, 0) == 0\n",
        )
        rep = run_mutation(tmp_path / "m.py", "python3 -B t.py", workdir=tmp_path)
        assert rep.total == 1
        assert rep.score == 1.0
        assert rep.survived == []

    def test_weak_test_lets_mutant_survive(self, tmp_path):
        self._project(
            tmp_path,
            "from m import add\nassert isinstance(add(1, 2), int)\n",  # tautological
        )
        rep = run_mutation(tmp_path / "m.py", "python3 -B t.py", workdir=tmp_path)
        assert rep.total == 1
        assert rep.score == 0.0
        assert len(rep.survived) == 1
        assert "Add->Sub" in rep.survived[0].description

    def test_original_file_restored(self, tmp_path):
        self._project(tmp_path, "from m import add\nassert add(2, 3) == 5\n")
        before = (tmp_path / "m.py").read_text()
        run_mutation(tmp_path / "m.py", "python3 -B t.py", workdir=tmp_path)
        assert (tmp_path / "m.py").read_text() == before

    def test_summary_mentions_score(self, tmp_path):
        self._project(tmp_path, "from m import add\nassert add(2, 3) == 5\n")
        rep = run_mutation(tmp_path / "m.py", "python3 -B t.py", workdir=tmp_path)
        assert "mutation score" in rep.summary()
