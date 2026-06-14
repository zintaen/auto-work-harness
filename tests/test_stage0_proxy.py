"""Tests for the egress proxy's security-critical allowlist logic.

The SOCKS5 null-byte bypass that lived in Claude Code's proxy for ~5.5 months was
a parser-differential / substring-matching class bug. These tests pin the proxy
to *exact* host / subdomain matching so a lookalike host cannot slip through.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PROXY = Path(__file__).resolve().parents[1] / "sandbox" / "proxy" / "credential_proxy.py"


def _load():
    spec = importlib.util.spec_from_file_location("credential_proxy", _PROXY)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


proxy = _load()


class TestHostAllowed:
    def setup_method(self):
        self.allow = {"github.com", "api.anthropic.com"}

    def test_exact_match(self):
        assert proxy._host_allowed("github.com", self.allow)
        assert proxy._host_allowed("api.anthropic.com", self.allow)

    def test_subdomain_match(self):
        assert proxy._host_allowed("codeload.github.com", self.allow)

    def test_case_and_trailing_dot_normalized(self):
        assert proxy._host_allowed("GitHub.com.", self.allow)

    def test_lookalike_rejected(self):
        # substring/suffix tricks that a naive matcher would wave through
        assert not proxy._host_allowed("github.com.evil.com", self.allow)
        assert not proxy._host_allowed("notgithub.com", self.allow)
        assert not proxy._host_allowed("evil-github.com", self.allow)
        assert not proxy._host_allowed("github.computer.net", self.allow)

    def test_empty_allowlist_denies_all(self):
        assert not proxy._host_allowed("github.com", set())


class TestLoadAllowlist:
    def test_parses_and_ignores_comments(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("# comment\ngithub.com\n\n  PyPI.org \n")
        al = proxy.load_allowlist(str(f))
        assert al == {"github.com", "pypi.org"}

    def test_missing_file_is_empty(self, tmp_path):
        assert proxy.load_allowlist(str(tmp_path / "nope.txt")) == set()

    def test_shipped_allowlist_is_nonempty(self):
        shipped = _PROXY.parent / "allowlist.txt"
        assert proxy.load_allowlist(str(shipped)) >= {"github.com", "pypi.org"}
