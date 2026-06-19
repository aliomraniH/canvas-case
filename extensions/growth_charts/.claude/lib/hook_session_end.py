"""SessionEnd / SubagentStop: idempotent reconcile (Phase 2).

Replays unpushed intents to the server, each carrying its event_id (at-least-once
+ server-side dedupe = exactly-once). Then it's a no-op if offline: events stay
queued and we exit 0. Same-agent overlap is serialized by an flock taken in the
shell wrapper; this module assumes it holds the lock.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from agent_cache import AgentCache  # noqa: E402
import server_sync  # noqa: E402

AGENT_ID = os.environ.get("AGENT_ID", "orchestrator")


def main() -> int:
    cache = AgentCache(AGENT_ID)
    pending = cache.unpushed()

    if not server_sync.server_reachable():
        print(f"reconcile: server offline — {len(pending)} intents left queued")
        cache.close()
        return 0

    pushed = 0
    for event in pending:
        if server_sync.push_event(event):
            cache.mark_pushed(event["event_id"])
            pushed += 1
        # On failure, leave queued — next reconcile retries (idempotent).

    print(f"reconcile: pushed {pushed}/{len(pending)} intents")
    cache.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
