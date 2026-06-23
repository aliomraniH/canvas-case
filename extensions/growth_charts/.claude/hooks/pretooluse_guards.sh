#!/usr/bin/env bash
# PreToolUse (Tier 2): generic guard engine reads the project ruleset.
# Exit 2 blocks the call; stderr is the reason. Canvas rules live in rules/guards.rules.
exec python3 "$(dirname "$0")/../lib/guard_engine.py"
