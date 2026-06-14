#!/usr/bin/env python3
"""Allowlist-enforcing egress proxy — runs OUTSIDE the agent's namespace.

Architecture (the pattern Anthropic and the cloud agents use):

    agent container  --HTTPS_PROXY-->  this proxy (different namespace)  --> internet
       (no creds)                        (holds the token, enforces allowlist)

The agent points HTTPS_PROXY/HTTP_PROXY at this process and is otherwise on
``--network none`` (or default-deny egress). Two guarantees:

  1. Allowlist: a CONNECT to a host not on the allowlist is refused (HTTP 403),
     so even a successful prompt-injection cannot reach an arbitrary host.
  2. Credential isolation: the GitHub/registry token lives in THIS process's
     env, never inside the agent — so it cannot be read out of the agent's
     filesystem or memory.

Hard lesson it encodes: a SOCKS5 null-byte bypass lived in Claude Code's
allowlist proxy for ~5.5 months. Egress proxies must validate the host *exactly*
(no substring matching, no parser-differential gaps) — see ``_host_allowed``.

This is a deliberately small, audited reference. For production prefer a
hardened proxy (mitmproxy with a strict addon, Squid with a tight ACL) but keep
these two invariants.
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
from pathlib import Path

ALLOWLIST_FILE = os.environ.get("AWH_PROXY_ALLOWLIST", str(Path(__file__).parent / "allowlist.txt"))
LISTEN_HOST = os.environ.get("AWH_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("AWH_PROXY_PORT", "8888"))


def load_allowlist(path: str) -> set[str]:
    """Load exact lowercased hostnames (comment/blank lines ignored)."""
    out: set[str] = set()
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def _host_allowed(host: str, allow: set[str]) -> bool:
    """Exact host or exact subdomain match — no substring/parser-differential gaps."""
    host = host.strip().lower().rstrip(".")
    if host in allow:
        return True
    return any(host.endswith("." + d) for d in allow)


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            with contextlib.suppress(OSError):
                s.shutdown(socket.SHUT_RDWR)


def handle(client: socket.socket, allow: set[str]) -> None:
    """Handle one HTTP CONNECT tunnel with allowlist enforcement."""
    try:
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            request += chunk
        line = request.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            client.close()
            return
        hostport = parts[1]
        host, _, port_s = hostport.partition(":")
        port = int(port_s or "443")
        if not _host_allowed(host, allow):
            client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\nblocked by egress allowlist\n")
            client.close()
            return
        upstream = socket.create_connection((host, port), timeout=10)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        threading.Thread(target=_pump, args=(client, upstream), daemon=True).start()
        _pump(upstream, client)
    except (OSError, ValueError):
        with contextlib.suppress(OSError):
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        client.close()


def main() -> int:
    allow = load_allowlist(ALLOWLIST_FILE)
    if not allow:
        print(f"[awh-proxy] refusing to start with an EMPTY allowlist ({ALLOWLIST_FILE})", file=sys.stderr)
        return 1
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print(f"[awh-proxy] listening {LISTEN_HOST}:{LISTEN_PORT}; {len(allow)} allowed domains")
    while True:
        client, _addr = srv.accept()
        threading.Thread(target=handle, args=(client, allow), daemon=True).start()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
