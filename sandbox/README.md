# Stage 0 — Default-deny egress sandbox

> "Design for containment at the environment layer first, then steer behavior at
> the model layer." — Anthropic, *How we contain Claude across products* (2026)

This is what makes an unattended `auto/` session (and `--dangerously-skip-permissions`)
actually safe: even if a prompt-injection fully succeeds, the agent cannot reach an
arbitrary host or read a credential store.

## Isolation hierarchy (weakest → strongest)

| Layer | Tech | Use when |
|---|---|---|
| Container (shared kernel) | Docker/runc | **insufficient for untrusted code** — your own code only |
| User-space kernel | gVisor (Modal, Daytona) | intercepts syscalls; good default |
| microVM (own kernel) | Firecracker/Kata (E2B, Northflank) | untrusted / third-party code |

This folder ships the **container + default-deny egress** baseline. For untrusted
code, run the same image inside gVisor or a microVM.

## Components

- `devcontainer/Dockerfile` + `devcontainer.json` — non-root `agent` user, `NET_ADMIN`
  to apply the firewall, gate command wired via `AWH_GATE_CMD`.
- `devcontainer/init-firewall.sh` — **generated** by
  `harness.stage0_verification.egress.render_init_script` (its tested twin). Default
  policy `DROP`; allow loopback + established + DNS + an explicit domain allowlist;
  then self-verifies that a non-allowlisted host (`example.org`) is unreachable and
  *exits non-zero if it is reachable*.
- `seatbelt/agent.sb` — macOS `sandbox-exec` profile: deny outbound except localhost,
  deny reads of `~/.aws`, `~/.ssh`, `.env`, `*.pem`.
- `proxy/credential_proxy.py` — allowlist-enforcing CONNECT proxy that runs **outside**
  the agent namespace and holds the token, so the agent never sees a raw key.

## Quick start (Linux / devcontainer)

```bash
# regenerate the firewall script from the tested generator
python3 -c "from harness.stage0_verification.egress import render_init_script; \
            open('sandbox/devcontainer/init-firewall.sh','w').write(render_init_script())"
# build + run the sandbox, firewall applies on start
devcontainer up --workspace-folder .
```

## Quick start (macOS, no container)

```bash
# terminal 1: start the egress proxy (holds the token, enforces the allowlist)
GITHUB_TOKEN=... python3 sandbox/proxy/credential_proxy.py
# terminal 2: run the agent boxed, pointed at the proxy
HTTPS_PROXY=http://127.0.0.1:8888 \
  sandbox-exec -f sandbox/seatbelt/agent.sb -D PROJECT="$PWD" -D HOME="$HOME" \
  claude --dangerously-skip-permissions
```

## Two caveats burned in from real incidents

1. **A permitted domain can still exfiltrate.** Anthropic saw data leave through an
   *allowlisted* domain (`api.anthropic.com`) using an attacker's API key — "the
   sandbox worked perfectly, and yet the data was exfiltrated." Keep the allowlist
   minimal and watch for credentialed egress to allowed hosts.
2. **Egress proxies need real review.** A SOCKS5 null-byte bypass lived in Claude
   Code's allowlist proxy for ~5.5 months. `proxy/credential_proxy.py` matches hosts
   *exactly* (see `test_stage0_proxy.py`) precisely to avoid that class of bug.
