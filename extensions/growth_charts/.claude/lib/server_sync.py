"""Best-effort sync boundary between an agent's local cache and the memory server.

This is where the MCP round-trip happens during reconcile. Everything here
**fails open**: if the server is unreachable, callers leave events queued and
exit 0 (the local-first guarantee). Reachability is a cheap `/healthz` probe;
the push is an idempotent MCP `tools/call` carrying each event's `event_id`, so
re-running after a partial failure is safe (the server dedupes).

Stdlib only (urllib) so it runs in a hook with no install step.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import config as _config  # noqa: E402

SERVER_URL = os.environ.get("MEMORY_SERVER_URL", "").rstrip("/")
AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
TIMEOUT = float(os.environ.get("MEMORY_SERVER_TIMEOUT", "4"))


def server_reachable() -> bool:
    if not SERVER_URL:
        return False
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/healthz", timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode())
            return resp.status == 200 and body.get("db") == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _mcp_call(tool: str, arguments: dict) -> bool:
    """Invoke one MCP tool over Streamable HTTP. Returns True on success.

    Idempotent by design: arguments carry event_id, so the server treats a
    duplicate as a no-op. Any transport/protocol error returns False (fail open).
    """
    if not SERVER_URL or not AUTH_TOKEN:
        return False
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    req = urllib.request.Request(
        f"{SERVER_URL}/mcp/",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status in (200, 202)
    except (urllib.error.URLError, OSError):
        return False


def push_event(event: dict) -> bool:
    """Replay one queued intent to the server. Maps op -> MCP tool."""
    op = event["op"]
    eid = event["event_id"]
    if op == "memory_save":
        return _mcp_call("memory_save", {
            "namespace": event["namespace"], "key": event["key"],
            "value": event["payload"], "kind": "todo",
            "source_surface": event["agent_id"], "event_id": eid,
        })
    if op == "handoff_save":
        # namespace is the project boundary and is required by every
        # per-project tool on the server; it comes from the Tier-3 pack.
        cfg = _config.load()
        return _mcp_call("handoff_save", {
            "namespace": cfg.memory_namespace,
            "key": event["key"], "value": event["payload"],
            "source_surface": event["agent_id"], "event_id": eid,
        })
    if op == "intent":
        # Code-change intent recorded for the board; stored as a memory todo.
        # Namespace/scope come from the Tier-3 pack, never hardcoded here.
        cfg = _config.load()
        return _mcp_call("memory_save", {
            "namespace": cfg.memory_namespace,
            "key": cfg.scoped_key("intent", eid),
            "value": {"files": event["files"], "diff_summary": event["diff_summary"],
                      "lamport": event["lamport"]},
            "kind": "todo", "source_surface": event["agent_id"], "event_id": eid,
        })
    return False
