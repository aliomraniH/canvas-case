"""SessionStart: load last-known state before planning (Phase 1).

Prints the agent's cached status to stdout (Claude Code injects SessionStart
stdout into context). If the server is reachable, pulls the latest first; if not,
prints the cached state with a STALE banner and exits 0 — the agent plans from
cache. Never blocks on an MCP round-trip.
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
    online = server_sync.server_reachable()

    print(f"# Agent context: {AGENT_ID}")
    if online:
        print("Server: ONLINE — cache reflects last reconcile; pull latest before acting.")
    else:
        print("STALE: server offline — planning from local cache. Reconcile on reconnect.")

    entries = cache.list()
    if not entries:
        print("No cached state yet (fresh agent).")
    else:
        print(f"\nLast-known state ({len(entries)} keys):")
        for e in sorted(entries, key=lambda x: (x["namespace"], x["key"]))[:50]:
            print(f"- [{e['namespace']}] {e['key']} @rev{e['revision']}")

    pending = cache.unpushed()
    if pending:
        print(f"\n{len(pending)} unpushed local intents awaiting reconcile.")
    cache.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
