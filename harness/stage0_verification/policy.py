"""Deterministic PreToolUse policy engine.

A *deny rule wins over any allow* — the canonical Claude Code containment pattern.
This module is the pure, side-effect-free decision core so it can be unit-tested
exhaustively; the hook script in ``hooks/pretooluse_deny.py`` is a thin shell
around ``evaluate_event``.

Two default deny classes, both grounded in published incidents:

  * Destructive shell commands — ``rm -rf /``, force-pushes, ``mkfs``, fork bombs,
    ``DROP DATABASE``, ``curl … | sh``. The AUTO_WORK protocol forbids these in an
    unattended run; here they are *structurally* blocked, not prompt-discouraged.
  * Secret reads — ``.env``, ``~/.aws/credentials``, ``*.pem``, ``id_rsa``, ``.ssh/``.
    A phishing prompt got Claude to exfiltrate ``~/.aws/credentials`` in 24/25
    retries (Anthropic, "How we contain Claude across products", 2026); the only
    defense that held was the environment boundary. This is that boundary.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

__all__ = ["Decision", "Policy", "default_policy", "evaluate_event"]

# Tools whose file_path argument should be checked against secret globs.
_FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit")
# Tools that MODIFY a file (subset of _FILE_TOOLS) — subject to read-only/deny-write rules.
_WRITE_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")
# Shell tokens that indicate a command writes/mutates a target path.
_WRITE_INDICATORS = (">", ">>", "tee", "sed", "truncate", "chmod", "dd", "mv", "rm", "install")

# Default destructive-command signatures (case-insensitive, matched on the command string).
_DEFAULT_DENY_COMMANDS: tuple[str, ...] = (
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|~|\$HOME|\*|\.)(\s|$)",  # rm -rf / ~ * .
    r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+(/|~|\$HOME|\*|\.)(\s|$)",  # rm -fr ...
    r"\bgit\s+push\b[^\n]*\s(--force\b|-f\b)",                    # force push
    r"\bgit\s+push\b[^\n]*\s\+",                                  # refspec force (+branch)
    r"\bgit\s+reset\s+--hard\b[^\n]*\borigin/",                   # hard reset to remote
    r"\bgit\s+clean\s+-[a-z]*f[a-z]*d",                           # git clean -fd
    r"\bgit\s+branch\s+-D\b",                                     # force-delete branch
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:",                             # fork bomb :(){ :|:& };:
    r"\bmkfs\b",                                                   # format filesystem
    r"\bdd\b[^\n]*\bof=/dev/",                                    # dd to a device
    r">\s*/dev/sd[a-z]",                                          # redirect to a disk
    r"\bchmod\s+-[a-z]*R[a-z]*\s+0*777\s+/",                      # chmod -R 777 /
    r"\bsudo\b",                                                   # privilege escalation
    r"\bDROP\s+(DATABASE|TABLE|SCHEMA)\b",                        # destructive SQL
    r"\bTRUNCATE\s+TABLE\b",
    r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b",             # curl … | sh
)

# Default secret/credential path signatures (glob form; matched on full path and basename).
_DEFAULT_DENY_PATHS: tuple[str, ...] = (
    "*.env", ".env", ".env.*", "*/.env", "*/.env.*",
    "*/secrets/*", "secrets/*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "*/.ssh/*",
    "*/.aws/credentials", "*/.aws/config", "*.netrc", ".netrc",
    "*credentials.json", "*service-account*.json", "*.kdbx",
)

# Read-only commands that *view* a file — used to extend secret-path denial to Bash.
_READ_CMDS = ("cat", "less", "more", "head", "tail", "bat", "nl", "xxd", "od", "strings", "grep")


@dataclass(frozen=True)
class Decision:
    """Result of evaluating one tool event."""

    block: bool
    reason: str = ""
    rule: str = ""  # which rule fired, for auditability

    @property
    def allow(self) -> bool:
        return not self.block


@dataclass
class Policy:
    """A deny-list policy. Deny always wins; there is intentionally no allow-list
    that can override a deny (that is the whole point of containment)."""

    deny_command_patterns: list[str] = field(default_factory=lambda: list(_DEFAULT_DENY_COMMANDS))
    deny_path_globs: list[str] = field(default_factory=lambda: list(_DEFAULT_DENY_PATHS))
    # Paths that may be READ but never WRITTEN — the read-only test/scoring "middle
    # ground" from ImpossibleBench. Populated by the readonly tool or operator config.
    deny_write_globs: list[str] = field(default_factory=list)
    # Extra paths the operator explicitly allows reading (rarely needed; never overrides a secret).
    extra_command_patterns: list[str] = field(default_factory=list)
    extra_path_globs: list[str] = field(default_factory=list)

    def all_command_patterns(self) -> list[str]:
        return [*self.deny_command_patterns, *self.extra_command_patterns]

    def all_path_globs(self) -> list[str]:
        return [*self.deny_path_globs, *self.extra_path_globs]

    @classmethod
    def from_dict(cls, data: dict) -> Policy:
        return cls(
            deny_command_patterns=list(
                data.get("deny_command_patterns", _DEFAULT_DENY_COMMANDS)
            ),
            deny_path_globs=list(data.get("deny_path_globs", _DEFAULT_DENY_PATHS)),
            deny_write_globs=list(data.get("deny_write_globs", [])),
            extra_command_patterns=list(data.get("extra_command_patterns", [])),
            extra_path_globs=list(data.get("extra_path_globs", [])),
        )


def default_policy() -> Policy:
    """The shipped defaults — safe for an unattended `auto/` session."""
    return Policy()


def _path_matches(path: str, globs: list[str]) -> str | None:
    """Return the first glob that matches ``path`` (full or basename), else None."""
    p = path.strip().strip('"').strip("'")
    base = p.rsplit("/", 1)[-1]
    for g in globs:
        if fnmatch.fnmatch(p, g) or fnmatch.fnmatch(base, g):
            return g
    return None


def _command_hits_secret(command: str, globs: list[str]) -> str | None:
    """Detect a read command (cat/grep/...) targeting a secret path inside a Bash command."""
    tokens = re.split(r"[\s;|&]+", command)
    if not tokens:
        return None
    saw_read_cmd = any(t.rsplit("/", 1)[-1] in _READ_CMDS for t in tokens)
    if not saw_read_cmd:
        return None
    for tok in tokens:
        hit = _path_matches(tok, globs)
        if hit:
            return hit
    return None


def _command_writes_path(command: str, globs: list[str]) -> str | None:
    """Detect a shell command that writes/mutates a read-only-protected path."""
    if not globs:
        return None
    tokens = re.split(r"[\s;|&]+", command)
    cmd_words = {t.rsplit("/", 1)[-1] for t in tokens}
    has_write = (">" in command) or bool(cmd_words & set(_WRITE_INDICATORS))
    if not has_write:
        return None
    for tok in tokens:
        hit = _path_matches(tok, globs)
        if hit:
            return hit
    return None


def evaluate_event(event: dict, policy: Policy | None = None) -> Decision:
    """Evaluate a Claude Code PreToolUse event dict and decide allow/deny.

    Args:
        event: the JSON object Claude Code passes on stdin. Relevant keys:
            ``tool_name`` and ``tool_input`` (a dict with e.g. ``command`` for Bash,
            ``file_path`` for Read/Edit/Write).
        policy: deny-list to apply; ``default_policy()`` if None.

    Returns:
        Decision(block, reason, rule). ``block=True`` means the hook must exit 2.
    """
    pol = policy or default_policy()
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    # 1. Bash commands -> destructive-command + secret-read checks.
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        for pat in pol.all_command_patterns():
            if re.search(pat, command, flags=re.IGNORECASE):
                return Decision(
                    block=True,
                    reason=(
                        "Blocked by Stage-0 policy: command matches a destructive "
                        f"signature ({pat!r}). If this is genuinely required, the human "
                        "operator must run it — an unattended agent must not."
                    ),
                    rule=f"deny_command:{pat}",
                )
        hit = _command_hits_secret(command, pol.all_path_globs())
        if hit:
            return Decision(
                block=True,
                reason=(
                    f"Blocked by Stage-0 policy: command reads a secret path ({hit!r}). "
                    "Secrets must be supplied via a secret store, never read into context."
                ),
                rule=f"deny_secret_read_cmd:{hit}",
            )
        whit = _command_writes_path(command, pol.deny_write_globs)
        if whit:
            return Decision(
                block=True,
                reason=(
                    f"Blocked by Stage-0 policy: command modifies a read-only test/scoring "
                    f"file ({whit!r}). Never edit the tests to make code pass — fix the code, "
                    "or mark the task BLOCKED if the test is genuinely wrong."
                ),
                rule=f"deny_write_cmd:{whit}",
            )
        return Decision(block=False)

    # 2. File tools -> secret-path checks on file_path (read OR write of secrets denied).
    if tool in _FILE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        hit = _path_matches(path, pol.all_path_globs())
        if hit:
            return Decision(
                block=True,
                reason=(
                    f"Blocked by Stage-0 policy: {tool} touches a secret/credential path "
                    f"({hit!r}). Deny wins over allow — this boundary is what holds when a "
                    "prompt-injection slips through (Anthropic containment, 2026)."
                ),
                rule=f"deny_path:{hit}",
            )
        # Read-only test/scoring files: writes denied, reads still allowed.
        if tool in _WRITE_TOOLS:
            whit = _path_matches(path, pol.deny_write_globs)
            if whit:
                return Decision(
                    block=True,
                    reason=(
                        f"Blocked by Stage-0 policy: {tool} would modify a read-only "
                        f"test/scoring file ({whit!r}). Test files are read-only to prevent "
                        "reward hacking (ImpossibleBench >79% of cheats are test edits). "
                        "Fix the code under test, or mark the task BLOCKED."
                    ),
                    rule=f"deny_write_path:{whit}",
                )
        return Decision(block=False)

    # 3. Everything else is allowed by this gate (other gates may still apply).
    return Decision(block=False)
