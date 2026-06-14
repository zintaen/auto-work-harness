"""Tests for the egress firewall generator (safety invariants of the plan)."""

from __future__ import annotations

from harness.stage0_verification.egress import (
    build_iptables_plan,
    default_allowlist,
    render_init_script,
)


class TestPlan:
    def test_is_default_deny(self):
        plan = build_iptables_plan(default_allowlist())
        text = "\n".join(plan)
        assert "iptables -P OUTPUT DROP" in plan
        assert "iptables -P INPUT DROP" in plan
        assert "iptables -P FORWARD DROP" in plan
        assert "AWH-EGRESS-DENY" in text  # denied traffic is logged

    def test_allow_established_and_loopback(self):
        plan = build_iptables_plan(["github.com"])
        assert "iptables -A OUTPUT -o lo -j ACCEPT" in plan
        assert any("ESTABLISHED,RELATED" in line for line in plan)

    def test_allowlist_accept_precedes_default_drop(self):
        plan = build_iptables_plan(["github.com"])
        accept_idx = next(i for i, line in enumerate(plan) if "--match-set allowed-domains" in line)
        drop_idx = plan.index("iptables -P OUTPUT DROP")
        assert accept_idx < drop_idx, "allow rules must come before the default DROP"

    def test_each_domain_resolved_into_ipset(self):
        domains = ["github.com", "pypi.org"]
        plan = build_iptables_plan(domains)
        for d in domains:
            assert any(d in line and "ipset add allowed-domains" in line for line in plan)

    def test_dns_resolvers_allowed(self):
        plan = build_iptables_plan(["x.com"], resolver_ips=["9.9.9.9"])
        assert any("--dport 53" in line and "9.9.9.9" in line for line in plan)

    def test_extra_subnets(self):
        plan = build_iptables_plan(["x.com"], allow_subnets=["10.0.0.0/8"])
        assert any("10.0.0.0/8" in line for line in plan)


class TestRender:
    def test_script_shape(self):
        s = render_init_script(["github.com"])
        assert s.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in s
        assert "github.com" in s
        # self-verification proves containment, not just asserts it
        assert "example.org" in s
        assert "egress is NOT contained" in s

    def test_default_allowlist_nonempty_and_includes_core(self):
        al = default_allowlist()
        assert "api.anthropic.com" in al
        assert "pypi.org" in al
        assert len(al) >= 5
