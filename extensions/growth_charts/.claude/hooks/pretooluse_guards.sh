#!/usr/bin/env bash
# PreToolUse (Tier 2): generic guard engine reads the project ruleset.
# Contract: the engine exits 2 to BLOCK (stderr = the reason) and 0 to ALLOW.
#
# Robustness: resolve our own directory via BASH_SOURCE rather than $0 — the
# hook runner does not always set $0 to this script's path, and a slipped path
# makes python3 open a missing file, which itself exits 2 and would be
# misread as a guard block on EVERY call. So we locate the engine explicitly and
# FAIL OPEN (exit 0) when it can't be found or run: a guard that cannot load must
# not block all tool use. Only an exit 2 from the engine that actually ran is
# propagated as a block.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
engine="$here/../lib/guard_engine.py"

if [ -z "$here" ] || [ ! -f "$engine" ]; then
  echo "pretooluse_guards: guard engine not found at '$engine' — allowing (fail-open)" >&2
  exit 0
fi

python3 "$engine"
rc=$?
[ "$rc" -eq 2 ] && exit 2   # intentional block from the engine
exit 0                       # allow, or fail open on any non-block error
