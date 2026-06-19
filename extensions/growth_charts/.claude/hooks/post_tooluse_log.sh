#!/usr/bin/env bash
# PostToolUse (Write|Edit): queue a code-change intent locally (Phase 2).
exec python3 "$(dirname "$0")/../lib/hook_post_tooluse.py"
