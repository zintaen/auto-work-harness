# Default-deny egress sandbox for autonomous coding agents.
# Isolation note: a plain Docker container shares the host kernel and is
# "explicitly insufficient for untrusted agent code". For untrusted/third-party
# code, run this image inside a microVM (E2B/Firecracker, Kata) or gVisor (Modal,
# Daytona) — see sandbox/README.md. For your own code, container + default-deny
# egress is the pragmatic baseline.
#
# Supply-chain note: for untrusted/regulated builds, pin the base to an immutable
# digest (FROM python:3.12-slim@sha256:<digest>) and rebuild deliberately. Left as a
# floating tag here for low-friction local dev.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iptables ipset dnsutils ca-certificates curl git sudo \
    && rm -rf /var/lib/apt/lists/*

# Non-root agent user. The agent must NEVER run as root: root bypasses the
# read-only file perms that protect test/scoring files (Stage 0 readonly layer).
RUN useradd --create-home --shell /bin/bash agent \
    && echo 'agent ALL=(root) NOPASSWD:/usr/local/bin/init-firewall.sh' > /etc/sudoers.d/awh-firewall

COPY init-firewall.sh /usr/local/bin/init-firewall.sh
RUN chmod 0755 /usr/local/bin/init-firewall.sh

USER agent
WORKDIR /workspace
