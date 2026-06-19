#!/usr/bin/env bash
# PreToolUse: safety teeth (Phase 4). Exit 2 blocks the call; stderr is the reason.
exec python3 "$(dirname "$0")/../lib/guards.py"
