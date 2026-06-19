# mcp-assist-memory → Postgres (Phase 0) — Implementation Sub-Spec

**Date:** 2026-06-19
**Status:** DRAFT — awaiting human approval. **No code is to be written until this is approved.**
**Scope:** Phase 0 only (memory server live on Neon Postgres). Phases 1–4 are explicitly out of scope.
**Target repo:** `aliomraniH/mcp-assist-memory` (server). **Builder:** Claude Code CLI.
**Reference DB discipline:** `aliomraniH/mneme` (reuse its pool/config/migration patterns; do not reinvent).
**Deploy target:** Replit Reserved VM (not Autoscale) + Neon Postgres (pooled endpoint) + pgvector.

---

## 0. Read-before-you-build note (cross-repo)

This sub-spec is being authored from the `canvas-case` repo because that is the
repo this session is scoped to. **The Phase 0 changes themselves do not touch
`canvas-case`** — they land in `aliomraniH/mcp-assist-memory`. To turn this
sub-spec into code I need one of:

1. `aliomraniH/mcp-assist-memory` added to this session's repo scope (so I can
   read the real `StorageBackend` ABC, the exact 18 tool signatures, and the
   current SQLite/filesystem backend), **and**
2. `aliomraniH/mneme` readable (to copy the pool/config/migration patterns
   verbatim rather than approximate them).

Everything below is written against the plan's description of those repos. The
two **open verification points** that the source repos will pin down are
flagged inline as `⚠ VERIFY`.

---

## 1. Goal of Phase 0 (and only Phase 0)

Stand up `mcp-assist-memory` live on Neon Postgres + pgvector, swapping the
default SQLite+filesystem backend for a `PostgresBackend` **behind the existing
`StorageBackend` ABC, with all 18 tool contracts unchanged**. Blobs move from
the content-addressed filesystem into Postgres `bytea`. The server runs as one
Python process on a Replit Reserved VM, exposes `/mcp` and `/healthz`, and
survives a redeploy with data intact.

**Phase 0 is done when (gate, §9):**
- `pytest` is green and all 18 tools round-trip against a real Postgres.
- A VM redeploy preserves data (durability of `bytea` blobs + rows).
- `handoff_save` written from one surface is read by `handoff_load` on another.

**Not in Phase 0:** local SQLite caches, hooks, reconciliation, embeddings/
pgvector *recall*, the five Canvas agents, LangSmith, the critic, promptfoo.
(pgvector the *extension* is installed now; the `knowledge` table + HNSW index
arrive in Phase 3 via `0003_knowledge_vector.sql`.)

---

## 2. Non-negotiable structural rules (carried from `mneme`)

| Rule | Enforcement in Phase 0 |
|---|---|
| **One** `AsyncConnectionPool`, opened in FastAPI `lifespan`, injected everywhere | `app.py` only; `app.state.pool`. No other module opens a connection. |
| **One** `config.py` (`pydantic-settings`); never read `os.environ` elsewhere | `config.py` exports a `settings` singleton. Lint/grep gate: no `os.environ` outside `config.py`. |
| **One** Postgres for all tiers (relational + JSONB + bytea + pgvector) | Single `DATABASE_URL`. |
| Keep the `StorageBackend` ABC; add `PostgresBackend` implementing it | New file `storage/postgres.py`; ABC untouched. |
| Frozen, numbered SQL migrations | `migrations/0001_init.sql` is immutable once merged. |
| `structlog` JSON to stdout | logging config in `app.py`. |
| Wrap stored/returned strings in `<<<UNTRUSTED_DATA>>> … <<<END>>>`; sanitize on write | `storage/sanitize.py`, called on every write path. |
| Read-only DB role for readers; no service-role keys; MCP sampling disabled | DB roles + MCP server config (§7). |

---

## 3. Files created / changed in Phase 0

```
mcp-assist-memory/
  app.py                     # CHANGED/NEW: FastAPI + lifespan (the ONE pool); mounts /mcp, /healthz; structlog
  config.py                  # NEW: pydantic-settings; the ONLY place secrets are read
  server/
    mcp_server.py            # CHANGED: FastMCP instance + the 18 tools — contracts UNCHANGED; backend injected
  storage/
    base.py                  # UNCHANGED: StorageBackend ABC (interface frozen)
    postgres.py              # NEW: PostgresBackend(StorageBackend) — implements the ABC over the pool
    sanitize.py              # NEW: strip injection patterns; UNTRUSTED_DATA wrapping
  migrations/
    0001_init.sql            # NEW + FROZEN: memory_entry, session, session_event, artifact(bytea), CREATE EXTENSION vector
  tests/
    test_round_trip.py       # NEW: all 18 tools round-trip against a real Postgres
    test_sanitize.py         # NEW: write-path sanitization + UNTRUSTED_DATA wrapping
    test_idempotency.py      # NEW: event_id dedupe (save twice → one revision)  ⚠ only if ABC already exposes event_id; see §5
    test_blob_durability.py  # NEW: artifact bytea store/fetch by sha256
    test_healthz.py          # NEW: /healthz returns 200 + db ok
  .env.example               # NEW: documents every var read by config.py
  Makefile                   # NEW: make migrate / make run / make test
  pyproject.toml             # CHANGED: add psycopg[binary], psycopg_pool, pydantic-settings, structlog, pgvector deps
```

Files explicitly **not** created in Phase 0 (they belong to later phases):
`server/embeddings.py`, `server/recall.py`, `coordination/*`,
`migrations/0002_coordination.sql`, `migrations/0003_knowledge_vector.sql`.

`⚠ VERIFY:` the existing repo's actual paths for the ABC and the tools may
differ from the plan's tree (e.g. tools may live in a single module). The swap
points are: (a) wherever the backend is instantiated today, inject
`PostgresBackend`; (b) leave every `@mcp.tool` signature byte-for-byte.

---

## 4. Migration DDL — `0001_init.sql` (FROZEN once merged)

Reuses `mcp-assist-memory`'s existing entities; moves blobs to `bytea`. Append-
only revisioning is preserved (matches the repo's current model). `⚠ VERIFY`
column names/types against the live SQLite schema before freezing.

```sql
-- 0001_init.sql  — FROZEN. Never edit; add a new numbered migration instead.
CREATE EXTENSION IF NOT EXISTS vector;      -- extension only; knowledge table arrives in 0003 (Phase 3)

-- Append-only, revisioned key/value memory (the system of record for notes/decisions/todos/handoffs)
CREATE TABLE memory_entry (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    namespace      text        NOT NULL,
    key            text        NOT NULL,
    revision       integer     NOT NULL,
    kind           text        NOT NULL CHECK (kind IN ('note','decision','todo','handoff','config')),
    value          jsonb       NOT NULL,
    source_surface text,                      -- 'cli' | 'web' | 'desktop' | <agent_id>
    tags           text[]      NOT NULL DEFAULT '{}',
    event_id       uuid,                      -- idempotency key (nullable; see §5)
    tombstone      boolean     NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (namespace, key, revision)
);
CREATE INDEX memory_entry_ns_key_rev ON memory_entry (namespace, key, revision DESC);
CREATE INDEX memory_entry_tags_gin   ON memory_entry USING gin (tags);
-- Idempotency: a given event_id may only be applied once.
CREATE UNIQUE INDEX memory_entry_event_id_uq ON memory_entry (event_id) WHERE event_id IS NOT NULL;

-- Episodic memory: sessions and their ordered events
CREATE TABLE session (
    session_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    surface      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    metadata     jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE session_event (
    session_id uuid    NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
    seq        integer NOT NULL,                 -- per-session monotonic
    kind       text    NOT NULL,
    payload    jsonb   NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);

-- Immutable blobs, content-addressed, stored as bytea (moved off the filesystem)
CREATE TABLE artifact (
    sha256       char(64) PRIMARY KEY,           -- hex digest = identity
    bytes        bytea    NOT NULL,
    size         integer  NOT NULL,
    content_type text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

Notes:
- `gen_random_uuid()` needs `pgcrypto` on older PG; Neon (PG 15/16) provides it
  built-in. `⚠ VERIFY` PG version; add `CREATE EXTENSION IF NOT EXISTS pgcrypto`
  only if needed.
- Revision allocation is **server-computed** (`max(revision)+1` under the write
  path), not client-supplied, to keep the append-only invariant.

---

## 5. `PostgresBackend` behind the unchanged ABC

```python
# storage/postgres.py
from storage.base import StorageBackend
from storage.sanitize import sanitize

class PostgresBackend(StorageBackend):
    def __init__(self, pool):                # the ONE pool, injected from app.state
        self.pool = pool

    async def memory_save(self, namespace, key, value, *, event_id=None, **kw):
        async with self.pool.connection() as conn:
            if event_id and await self._seen(conn, event_id):   # dedupe → no double-apply
                return await self._latest(conn, namespace, key)
            value = sanitize(value)                              # strip injection, wrap UNTRUSTED_DATA
            return await self._append_revision(conn, namespace, key, value, event_id, **kw)
    # ... remaining ABC methods (memory_list, memory_history, handoff_*, session_*, artifact_*) ...
```

Rules for the implementation:
- **Every** ABC method is implemented over `self.pool.connection()`; nothing
  opens its own connection.
- **Writes** go through `sanitize()` before hitting SQL.
- **Reads** return values already wrapped in `<<<UNTRUSTED_DATA>>> … <<<END>>>`
  at the boundary so consumers can't be tricked into treating stored text as
  instructions.
- `_append_revision` computes the next revision in the same transaction
  (`SELECT max(revision) … FOR UPDATE` on the key, or an `INSERT … ON CONFLICT`
  pattern) to avoid races.

**`⚠ VERIFY` (the one real contract question):** the plan's idempotent-save
sketch uses an `event_id` parameter. If the *current* ABC method signatures do
**not** include `event_id`, then adding it as a keyword-only arg with a default
of `None` is backward-compatible and keeps the 18 contracts unchanged for
existing callers. If the ABC must stay literally identical, the dedupe key
moves into the `value`/metadata envelope instead. **Decide against the real ABC
before writing.** (Full reconciliation/idempotency is a Phase 2 concern; in
Phase 0 we only lay the column + unique index so we don't have to alter the
frozen migration later.)

---

## 6. The single pool + app wiring

```python
# app.py
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool
from config import settings

@asynccontextmanager
async def lifespan(app):
    async with AsyncConnectionPool(settings.database_url, open=False) as pool:
        await pool.open()
        await pool.wait()                 # fail fast if Neon is unreachable at boot
        app.state.pool = pool             # shared by MCP server + /healthz; nowhere else opens a conn
        yield
```

```python
# config.py — the ONLY place secrets are read
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    mcp_auth_token: str
    voyage_api_key: str | None = None       # unused until Phase 3; declared now
    openai_api_key: str | None = None       # unused until Phase 3
    anthropic_api_key: str | None = None
    langsmith_api_key: str | None = None

settings = Settings()
```

- `DATABASE_URL` → Neon **pooled** endpoint (PgBouncer). Because PgBouncer is in
  transaction-pooling mode, configure psycopg with no server-side prepared
  statements where required (`prepare_threshold=None`) — `⚠ VERIFY` against the
  Neon pooled connstring guidance.
- `/mcp` (FastMCP, the 18 tools) and `/healthz` both read `app.state.pool`.
- MCP server is mounted with **bearer auth** (`MCP_AUTH_TOKEN`) and **sampling
  disabled** (closes the worst injection surface).

### `/healthz`
```
GET /healthz → 200 {"status":"ok","db":"ok"}   when `SELECT 1` succeeds on the pool
            → 503 {"status":"degraded","db":"down"}  otherwise
```
No auth on `/healthz` (it's the liveness probe for the Reserved VM and the
Phase 8 scheduled health routine), but it returns no data — just pool health.

---

## 7. Secrets, roles, deploy

- All cloud secrets in **Replit Secrets**, read only via `config.py`:
  `DATABASE_URL`, `MCP_AUTH_TOKEN` (and the Phase-3 keys, declared-but-optional).
- **Canvas credentials never come near this server** — they stay in
  `~/.canvas/credentials.ini` on the local machine. Phase 0 doesn't touch them.
- **DB roles:** an owner/migrator role runs migrations; a **read-only role** is
  used by any read path. No service-role keys.
- **Deploy:** Replit **Reserved VM** (persistent, survives redeploy) — *not*
  Autoscale (ephemeral, would defeat the durability gate). `make migrate` runs
  `0001_init.sql` against Neon; `make run` starts uvicorn; `make test` runs pytest.

---

## 8. Tests (first gate) — must verify behavior, not types

| Test | Asserts |
|---|---|
| `test_round_trip.py` | each of the 18 tools performs its documented effect against a real Postgres (save→list→history→get; handoff save/load; session event append/read; artifact put/get). Asserts *values*, not `isinstance(list)`. |
| `test_sanitize.py` | injection markers stripped on write; returned strings wrapped in `<<<UNTRUSTED_DATA>>>…<<<END>>>`. |
| `test_blob_durability.py` | a blob stored as `bytea` is byte-identical on fetch by `sha256`; size/content_type preserved. |
| `test_idempotency.py` | `memory_save` with the same `event_id` twice yields **one** revision (`⚠` gated on the §5 decision). |
| `test_healthz.py` | 200/`db:ok` when pool healthy; 503 when `SELECT 1` fails. |

Tests run against a real Postgres (ephemeral Neon branch or a local PG
container) — **not** an in-memory stub. Mock-green is not the gate.

---

## 9. Phase 0 checkpoint (human gate to advance to Phase 1)

1. `pytest` green; all 18 tools round-trip against real Postgres. ✅
2. **Redeploy the Reserved VM → rows + blobs persist.** ✅ (the durability proof)
3. `handoff_save` written on one surface is read by `handoff_load` on another. ✅

Only after these three pass — and after explicit human sign-off — does Phase 1
(local SQLite cache + load-before-planning) begin. No Phase 1–4 code before then.

---

## 10. Open items to confirm before code (from the plan §"Open items")

These carry the plan author's recommendations; I've adopted them as the
working defaults in this sub-spec. Confirm or override:

1. **Neon vs Replit-built-in Postgres** → **external Neon, pooled endpoint**
   (default adopted). One `DATABASE_URL` secret; branch-per-test for CI.
2. **Blobs → Postgres `bytea`** (default adopted) vs filesystem on the VM disk.
   `bytea` chosen for single-store durability across redeploy; object storage
   left as a future ABC swap.
3. **`event_id` on the write path** (§5 `⚠ VERIFY`) — confirm whether the real
   `StorageBackend` ABC may grow a keyword-only `event_id=None`, or whether the
   dedupe key must ride inside the value envelope to keep the 18 signatures
   literally byte-identical.
4. **Repo scope** — to write the code I need `aliomraniH/mcp-assist-memory`
   (and read access to `aliomraniH/mneme`) added to this session.

---

**Awaiting approval. No Phase 0 code, and nothing from Phases 1–4, will be
written until this sub-spec is approved and the source repos are in scope.**
