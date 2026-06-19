"""PostToolUse (Write|Edit): append a code-change intent to the local cache
(Phase 2). Each intent gets a fresh event_id + Lamport timestamp, pushed=false.
Reconcile replays it idempotently. Never blocks; failures are swallowed so a
cache hiccup can't break the edit.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from agent_cache import AgentCache  # noqa: E402

AGENT_ID = os.environ.get("AGENT_ID", "orchestrator")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0
    try:
        cache = AgentCache(AGENT_ID)
        cache.queue_intent(
            "intent",
            files=[file_path],
            diff_summary=f"{data.get('tool_name', 'edit')} {os.path.basename(file_path)}",
            payload={"file": file_path},
        )
        cache.close()
    except Exception:  # never break the edit on a cache error
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
