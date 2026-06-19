#!/usr/bin/env bash
# SessionEnd/SubagentStop: idempotent reconcile (Phase 2).
# Serialize same-agent reconciles with a per-agent flock; the network/server
# work happens inside the lock but outside any SQLite write transaction.
AGENT_ID="${AGENT_ID:-orchestrator}"
CACHE_DIR="${AGENT_CACHE_DIR:-$(dirname "$0")/../../.agent-cache}"
mkdir -p "$CACHE_DIR"
LOCK="$CACHE_DIR/${AGENT_ID}.reconcile.lock"
if command -v flock >/dev/null 2>&1; then
  exec flock -w 10 "$LOCK" python3 "$(dirname "$0")/../lib/hook_session_end.py"
else
  exec python3 "$(dirname "$0")/../lib/hook_session_end.py"
fi
