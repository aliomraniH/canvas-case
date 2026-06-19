#!/usr/bin/env bash
# SessionStart: load last-known state into context (Phase 1).
exec python3 "$(dirname "$0")/../lib/hook_session_start.py"
