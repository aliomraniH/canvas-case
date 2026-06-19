"""Per-agent local SQLite cache — the last-known-state mirror that makes the
agents local-first (Phases 1–2).

Each agent gets its own DB file (`.agent-cache/<agent>.db`) so different agents
never contend on the same file. WAL + busy_timeout handle same-agent overlap;
`session_end_reconcile.sh` additionally takes an flock per DB.

This module is intentionally dependency-free (stdlib `sqlite3`) so it runs in a
hook with no install step. The server-sync boundary (`mark_pushed` consumers) is
where the MCP round-trip happens; reconcile fails open when the server is down.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import time
import uuid

CACHE_DIR = pathlib.Path(
    os.environ.get("AGENT_CACHE_DIR", pathlib.Path(__file__).resolve().parents[2] / ".agent-cache")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entry (
    namespace TEXT NOT NULL, key TEXT NOT NULL,
    value_json TEXT NOT NULL, revision INTEGER NOT NULL,
    last_seen_revision INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL, PRIMARY KEY (namespace, key));
CREATE TABLE IF NOT EXISTS unpushed_events (
    event_id TEXT PRIMARY KEY, lamport INTEGER NOT NULL, agent_id TEXT NOT NULL,
    op TEXT NOT NULL, namespace TEXT, key TEXT, files_json TEXT,
    diff_summary TEXT, payload_json TEXT, created_at REAL NOT NULL,
    pushed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def _connect(agent_id: str) -> sqlite3.Connection:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DIR / f"{agent_id}.db", timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(_SCHEMA)
    return conn


def _next_lamport(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT v FROM meta WHERE k='lamport'").fetchone()
    nxt = (int(row[0]) if row else 0) + 1
    conn.execute(
        "INSERT INTO meta (k, v) VALUES ('lamport', ?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (str(nxt),),
    )
    return nxt


class AgentCache:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.conn = _connect(agent_id)

    # --- read-through state (SessionStart) ---
    def get(self, namespace: str, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT value_json, revision, last_seen_revision FROM cache_entry "
            "WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
        if not row:
            return None
        return {"value": json.loads(row[0]), "revision": row[1], "last_seen_revision": row[2]}

    def list(self, namespace: str | None = None) -> list[dict]:
        if namespace:
            rows = self.conn.execute(
                "SELECT namespace, key, value_json, revision FROM cache_entry WHERE namespace=?",
                (namespace,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT namespace, key, value_json, revision FROM cache_entry"
            ).fetchall()
        return [
            {"namespace": r[0], "key": r[1], "value": json.loads(r[2]), "revision": r[3]}
            for r in rows
        ]

    def upsert_from_server(self, namespace: str, key: str, value, revision: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO cache_entry (namespace, key, value_json, revision, last_seen_revision, updated_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET "
                "value_json=excluded.value_json, revision=excluded.revision, "
                "last_seen_revision=excluded.revision, updated_at=excluded.updated_at",
                (namespace, key, json.dumps(value), revision, revision, time.time()),
            )

    # --- offline write queue (PostToolUse) ---
    def queue_intent(self, op: str, *, namespace=None, key=None, files=None,
                     diff_summary=None, payload=None) -> str:
        with self.conn:
            eid = str(uuid.uuid4())
            lamport = _next_lamport(self.conn)
            self.conn.execute(
                "INSERT INTO unpushed_events "
                "(event_id, lamport, agent_id, op, namespace, key, files_json, diff_summary, payload_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (eid, lamport, self.agent_id, op, namespace, key,
                 json.dumps(files or []), diff_summary, json.dumps(payload), time.time()),
            )
        return eid

    def unpushed(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT event_id, lamport, agent_id, op, namespace, key, files_json, "
            "diff_summary, payload_json FROM unpushed_events WHERE pushed=0 ORDER BY lamport ASC"
        ).fetchall()
        return [
            {"event_id": r[0], "lamport": r[1], "agent_id": r[2], "op": r[3],
             "namespace": r[4], "key": r[5], "files": json.loads(r[6]),
             "diff_summary": r[7], "payload": json.loads(r[8]) if r[8] else None}
            for r in rows
        ]

    def mark_pushed(self, event_id: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE unpushed_events SET pushed=1 WHERE event_id=?", (event_id,))

    def close(self) -> None:
        self.conn.close()
