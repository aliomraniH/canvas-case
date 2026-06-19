"""FastMCP instance and the 18 tools.

The tools are thin: they validate/relay to the injected ``StorageBackend``.
The backend is set on ``deps`` during the FastAPI lifespan (one pool, injected),
so tools never open connections or read config themselves.

Tool surface (18):
  memory:   memory_save, memory_get, memory_list, memory_history, memory_delete, memory_search
  handoff:  handoff_save, handoff_load, handoff_list
  session:  session_create, session_append_event, session_get, session_list, session_events
  artifact: artifact_put, artifact_get, artifact_list
  admin:    stats
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP

from config import settings
from storage.base import StorageBackend


@dataclass
class Deps:
    backend: StorageBackend | None = None


deps = Deps()


def _backend() -> StorageBackend:
    if deps.backend is None:  # pragma: no cover - lifespan always sets this
        raise RuntimeError("storage backend not initialized")
    return deps.backend


mcp: FastMCP = FastMCP(name="assist-memory")


# ------------------------------------------------------------------ memory
@mcp.tool
async def memory_save(
    namespace: str,
    key: str,
    value: Any,
    kind: str = "note",
    tags: list[str] | None = None,
    source_surface: str | None = None,
    event_id: str | None = None,
) -> dict:
    """Append a new revision of a memory entry. kind ∈ note|decision|todo|handoff|config.
    Pass a stable event_id (uuid) for exactly-once writes during offline reconcile."""
    return await _backend().memory_save(
        namespace, key, value, kind=kind, tags=tags,
        source_surface=source_surface, event_id=event_id,
    )


@mcp.tool
async def memory_get(namespace: str, key: str) -> dict | None:
    """Return the latest live revision of a key, or null if missing/deleted."""
    return await _backend().memory_get(namespace, key)


@mcp.tool
async def memory_list(
    namespace: str, kind: str | None = None, tag: str | None = None, limit: int = 100
) -> list[dict]:
    """List the latest live entry per key in a namespace, optionally filtered by kind/tag."""
    return await _backend().memory_list(namespace, kind=kind, tag=tag, limit=limit)


@mcp.tool
async def memory_history(namespace: str, key: str, limit: int = 50) -> list[dict]:
    """Return revision history (newest first) for a key, including tombstones."""
    return await _backend().memory_history(namespace, key, limit=limit)


@mcp.tool
async def memory_delete(
    namespace: str, key: str, source_surface: str | None = None, event_id: str | None = None
) -> dict:
    """Soft-delete a key by appending a tombstone revision (history preserved)."""
    return await _backend().memory_delete(
        namespace, key, source_surface=source_surface, event_id=event_id
    )


@mcp.tool
async def memory_search(query: str, namespace: str | None = None, limit: int = 20) -> list[dict]:
    """Substring search over memory values (pgvector semantic recall arrives in Phase 3)."""
    return await _backend().memory_search(query, namespace=namespace, limit=limit)


# ------------------------------------------------------------------ handoff
@mcp.tool
async def handoff_save(
    key: str, value: Any, source_surface: str | None = None, event_id: str | None = None
) -> dict:
    """Save a cross-surface handoff under a shared key (read it back with handoff_load)."""
    return await _backend().handoff_save(
        key, value, source_surface=source_surface, event_id=event_id
    )


@mcp.tool
async def handoff_load(key: str) -> dict | None:
    """Load the latest handoff for a shared key (written by any surface)."""
    return await _backend().handoff_load(key)


@mcp.tool
async def handoff_list(limit: int = 100) -> list[dict]:
    """List active handoffs."""
    return await _backend().handoff_list(limit=limit)


# ------------------------------------------------------------------ session
@mcp.tool
async def session_create(surface: str | None = None, metadata: dict | None = None) -> dict:
    """Start an episodic session; returns its session_id."""
    return await _backend().session_create(surface=surface, metadata=metadata)


@mcp.tool
async def session_append_event(session_id: str, kind: str, payload: Any) -> dict:
    """Append an ordered event to a session; returns the assigned seq."""
    return await _backend().session_append_event(session_id, kind, payload)


@mcp.tool
async def session_get(session_id: str) -> dict | None:
    """Fetch session metadata."""
    return await _backend().session_get(session_id)


@mcp.tool
async def session_list(limit: int = 50) -> list[dict]:
    """List recent sessions (newest first)."""
    return await _backend().session_list(limit=limit)


@mcp.tool
async def session_events(session_id: str, limit: int = 200) -> list[dict]:
    """Return a session's events in seq order."""
    return await _backend().session_events(session_id, limit=limit)


# ----------------------------------------------------------------- artifact
@mcp.tool
async def artifact_put(content_base64: str, content_type: str | None = None) -> dict:
    """Store an immutable blob (base64). Rejects blobs over the configured size cap.
    Returns its sha256 (content address)."""
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise ValueError(f"content_base64 is not valid base64: {exc}") from exc
    if len(data) > settings.max_artifact_bytes:
        raise ValueError(
            f"artifact {len(data)} bytes exceeds cap {settings.max_artifact_bytes}; "
            "store large objects in object storage and reference the sha256"
        )
    return await _backend().artifact_put(data, content_type=content_type)


@mcp.tool
async def artifact_get(sha256: str) -> dict | None:
    """Return artifact metadata. Small blobs (< inline limit) include base64 content;
    larger blobs are fetched via GET /artifact/{sha256} (streamed)."""
    meta = await _backend().artifact_get(sha256)
    if meta is None:
        return None
    if meta["size"] <= settings.artifact_inline_limit:
        data = await _backend().artifact_read_range(sha256, 0, meta["size"])
        meta = {**meta, "content_base64": base64.b64encode(data or b"").decode("ascii")}
    else:
        meta = {**meta, "content_url": f"/artifact/{sha256}", "inline": False}
    return meta


@mcp.tool
async def artifact_list(limit: int = 100) -> list[dict]:
    """List stored artifacts (newest first)."""
    return await _backend().artifact_list(limit=limit)


# -------------------------------------------------------------------- admin
@mcp.tool
async def stats() -> dict:
    """Return store-wide counts (memory revisions/keys, sessions, events, artifacts, bytes)."""
    return await _backend().stats()
