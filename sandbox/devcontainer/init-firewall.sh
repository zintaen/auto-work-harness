#!/usr/bin/env bash
# AUTO_WORK harness — default-deny egress firewall.
# Apply INSIDE the agent's network namespace as root at container start.
# Generated/validated by harness.stage0_verification.egress.render_init_script.
set -euo pipefail

if ! command -v ipset >/dev/null 2>&1; then
  echo "ipset is required (apt-get install -y ipset iptables dnsutils)" >&2
  exit 1
fi

iptables -F OUTPUT
iptables -F INPUT
ipset destroy allowed-domains 2>/dev/null || true
ipset create allowed-domains hash:ip
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -d 1.1.1.1 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -d 1.1.1.1 -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -d 8.8.8.8 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -d 8.8.8.8 -j ACCEPT
for ip in $(dig +short A github.com); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A api.github.com); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A codeload.github.com); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A objects.githubusercontent.com); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A registry.npmjs.org); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A pypi.org); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A files.pythonhosted.org); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
for ip in $(dig +short A api.anthropic.com); do ipset add allowed-domains "$ip" 2>/dev/null || true; done
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT
iptables -A OUTPUT -j LOG --log-prefix "AWH-EGRESS-DENY: " --log-level 4
iptables -P OUTPUT DROP
iptables -P INPUT DROP
iptables -P FORWARD DROP

echo "[awh] egress firewall applied: default-deny with 8 allowed domain(s)."

# --- self-verification: an allowed host must reach, a random host must NOT ---
if curl -sS --max-time 5 -o /dev/null "https://github.com"; then
  echo "[awh] OK: reached allowed host github.com"
else
  echo "[awh] WARN: could not reach allowed host github.com (DNS/timing?)" >&2
fi
if curl -sS --max-time 5 -o /dev/null "https://example.org" 2>/dev/null; then
  echo "[awh] FAIL: example.org was reachable — egress is NOT contained!" >&2
  exit 1
else
  echo "[awh] OK: non-allowlisted egress is blocked."
fi
