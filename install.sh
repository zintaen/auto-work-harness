#!/usr/bin/env bash
# Wire the Stage-0 gates into a TARGET project's Claude Code settings.
# Usage:  ./install.sh /path/to/target-project
# Idempotent-ish: never clobbers an existing settings.json (writes settings.awh.json
# beside it for you to merge).
set -euo pipefail

AWH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "usage: $0 /path/to/target-project" >&2
  exit 2
fi
if [ ! -d "$TARGET" ]; then
  echo "target is not a directory: $TARGET" >&2
  exit 2
fi

TEMPLATE="$AWH_ROOT/harness/stage0_verification/settings.template.json"
CLAUDE_DIR="$TARGET/.claude"
mkdir -p "$CLAUDE_DIR"

# Substitute the absolute harness path into the hook commands.
rendered="$(sed "s#__AWH_ROOT__#$AWH_ROOT#g" "$TEMPLATE")"

dest="$CLAUDE_DIR/settings.json"
if [ -e "$dest" ]; then
  dest="$CLAUDE_DIR/settings.awh.json"
  echo "[awh] $CLAUDE_DIR/settings.json exists — writing $dest instead; merge its \"hooks\" block in."
fi
printf '%s\n' "$rendered" > "$dest"
echo "[awh] wrote $dest"

# Seed the per-project gate command + a starter policy.
mkdir -p "$TARGET/.awh"
if [ ! -e "$TARGET/.awh/gate.sh" ]; then
  cat > "$TARGET/.awh/gate.sh" <<'EOF'
#!/usr/bin/env sh
# Stage-0 evidence gate — exit non-zero to BLOCK the agent from stopping.
# Replace with this project's real test+lint+typecheck commands.
set -e
echo "[awh-gate] running project checks…"
# e.g.: npm test && npm run lint && npm run typecheck
EOF
  chmod +x "$TARGET/.awh/gate.sh"
  echo "[awh] wrote $TARGET/.awh/gate.sh (edit it to run your real checks)"
fi

cat <<EOF

[awh] done. Next:
  1. Edit $TARGET/.awh/gate.sh to run your real test+lint+typecheck.
  2. (optional) Lock test files read-only:
       python3 -m harness.cli lock "$TARGET" --write-policy
  3. (optional, untrusted code) run inside the egress sandbox: see $AWH_ROOT/sandbox/README.md
EOF
