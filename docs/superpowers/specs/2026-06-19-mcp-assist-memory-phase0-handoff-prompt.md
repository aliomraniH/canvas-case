# Handoff Prompt — `mcp-assist-memory` Phase 0 (standalone Replit service)

**Purpose:** paste the block below into a *separate* Claude Code session whose repo scope is
`aliomraniH/mcp-assist-memory` (committer) with `aliomraniH/mneme` readable as the reference
pattern. That session builds Phase 0: the memory service running **standalone on Replit**
(Reserved VM + Neon Postgres + pgvector), serving the Canvas Claude surfaces over MCP. It is a
separate deployment from any Canvas plugin infra; Canvas credentials never touch it.

This is the source of truth for that session because it cannot read the `canvas-case` spec docs.

---

## ►►► COPY EVERYTHING BELOW THIS LINE INTO THE OTHER SESSION ◄◄◄

You are the sole committer for `aliomraniH/mcp-assist-memory`. Read `aliomraniH/mneme` for its
pool/config/migration discipline and **reuse those patterns verbatim — do not reinvent them.**

### Mission
Refactor `mcp-assist-memory` to run as a **standalone service on Replit** backed by **Neon
Postgres + pgvector**, swapping the default SQLite+filesystem backend for a `PostgresBackend`
**behind the existing `StorageBackend` ABC, with all 18 MCP tool contracts unchanged.** This is
Phase 0 of a larger plan. **Phases 1–4 are out of scope — do not build local caches, hooks,
reconciliation, embeddings recall, agents, LangSmith, or promptfoo.**

This service is deployed **separately** for Canvas: one FastAPI process exposing `/mcp` (FastMCP,
the 18 tools) + `/healthz`, on a Replit **Reserved VM** (not Autoscale), with `DATABASE_URL`
pointing at Neon's **pooled** endpoint. Canvas SDK credentials stay on the local machine and
**never** reach this server or Replit Secrets.

### Spec-and-stop (do this first)
**Before writing any code**, read this prompt, then read the actual repo: the real
`StorageBackend` ABC, the exact 18 `@mcp.tool` signatures, the current SQLite/filesystem backend,
and where the backend is instantiated. Produce a short written implementation sub-spec that maps
the items below onto the *real* file layout (which may differ from the idealized tree), and
**stop for human approval.** Call out anything in the repo that contradicts this prompt.

### Non-negotiable structural rules (from `mneme`)
- **One** `AsyncConnectionPool`, opened in the FastAPI `lifespan`, stored on `app.state.pool`,
  injected everywhere. No other module opens a connection.
- **One** `config.py` using `pydantic-settings`. It is the **only** place `os.environ`/secrets are
  read. Grep-gate: no `os.environ` outside `config.py`.
- **One** Postgres for everything (relational + JSONB + bytea + pgvector). One `DATABASE_URL`.
- Keep the `StorageBackend` ABC unchanged; add `storage/postgres.py: PostgresBackend`.
- **Frozen, numbered migrations.** `migrations/0001_init.sql` is immutable once merged.
- `structlog` JSON to stdout.
- Sanitize on the write path; wrap stored/returned strings in `<<<UNTRUSTED_DATA>>> … <<<END>>>`.
- Read-only DB role for readers; no service-role keys; **MCP sampling disabled**; bearer auth on
  `/mcp` via `MCP_AUTH_TOKEN`.

### Files in scope for Phase 0
`app.py` (FastAPI + lifespan + structlog, mounts `/mcp` and `/healthz`), `config.py` (NEW),
`server/mcp_server.py` (inject the backend; **tool signatures unchanged**), `storage/postgres.py`
(NEW), `storage/sanitize.py` (NEW), `migrations/0001_init.sql` (NEW + FROZEN),
`tools/backfill_artifacts.py` (NEW, one-time blob import — see Migration), `tests/*`, `.env.example`,
`Makefile` (`make migrate|run|test`), `pyproject.toml` (add `psycopg[binary]`, `psycopg_pool`,
`pydantic-settings`, `structlog`, `pgvector`). **Do NOT create** `server/embeddings.py`,
`server/recall.py`, `coordination/*`, `0002_*`, `0003_*` — later phases.

### Migration `0001_init.sql` (verify column names against the live SQLite schema before freezing)
- `CREATE EXTENSION IF NOT EXISTS vector;` (extension only — the `knowledge` table is Phase 3).
- `memory_entry`: append-only revisioned KV — `(namespace, key, revision)` unique, `kind IN
  (note,decision,todo,handoff,config)`, `value jsonb`, `source_surface`, `tags text[]`,
  `event_id uuid` (nullable) with a **partial unique index** `WHERE event_id IS NOT NULL`,
  `tombstone bool`, `created_at`. Index `(namespace,key,revision DESC)` and a GIN on `tags`.
  Revision is **server-computed** (`max+1` in-txn), never client-supplied.
- `session` / `session_event` (per-session monotonic `seq`, PK `(session_id, seq)`).
- `artifact`: immutable, content-addressed blobs as **bytea** — PK `sha256 char(64)`, `bytes
  bytea`, `size int`, `content_type`, `created_at`.
- Confirm PG version for `gen_random_uuid()`; add `pgcrypto` only if needed.

### PostgresBackend
Implement every ABC method over `self.pool.connection()`. Writes pass through `sanitize()`. Reads
return values wrapped in `<<<UNTRUSTED_DATA>>>…<<<END>>>`. Idempotent save: if `event_id` is seen,
return the latest revision instead of appending (no double-apply). **If the current ABC signatures
do not already include `event_id`, add it as a keyword-only arg defaulting to `None`** so the 18
contracts stay backward-compatible; if they must stay literally byte-identical, carry the dedupe
key inside the value envelope instead. Decide against the real ABC and note it in the sub-spec.

### Lifespan — bound every wait, fail fast (critical)
Do **not** use a bare `await pool.wait()` — that hangs indefinitely on a Neon cold start or silent
partition. Instead:
- Build the pool with `open=False`, `min_size=0` (don't warm a pool through a cold DB),
  `max_size=10`, `timeout=10.0`, `reconnect_timeout=30.0`, `max_idle=60.0`, and
  `kwargs={"connect_timeout": 10, "options": "-c statement_timeout=15000 -c
  idle_in_transaction_session_timeout=15000"}`.
- `await pool.open()` (returns immediately), then a **single** `SELECT 1` readiness probe wrapped
  in `async with asyncio.timeout(15):`. On timeout/`OperationalError`, **log and raise** — a
  terminal crash lets Replit restart the VM, which is correct; a hung lifespan is not.
- `/healthz`: bounded `SELECT 1` → `200 {"status":"ok","db":"ok"}` else `503` degraded. No auth,
  returns no data (liveness only).

### `config.py`
`pydantic-settings` `Settings` with: `database_url`, `mcp_auth_token`, optional
`voyage_api_key/openai_api_key/anthropic_api_key/langsmith_api_key` (declared now, unused until
Phase 3), and `max_artifact_bytes: int = 25 * 1024 * 1024`. Export a `settings` singleton.

### bytea safety (avoid OOM on the Replit VM)
- **Write cap:** reject artifacts larger than `max_artifact_bytes` (25 MB MVP) with a clear error;
  dedupe by `sha256`.
- **Reads:** never `SELECT bytes` whole — read in ~1 MB windows via `substring(bytes FROM :off FOR
  :len)` and stream via `StreamingResponse`. If real blobs routinely exceed the cap, stop and
  flag: that's the signal to use object storage (a future ABC swap), keeping only `sha256` +
  metadata in Postgres.

### Migration of existing filesystem/SQLite blobs → bytea
Survey **first**: count blobs and the **max single-blob size**. Then `tools/backfill_artifacts.py`
(NOT part of the frozen migration): stream each content-addressed file, compute `sha256`,
`INSERT ... ON CONFLICT (sha256) DO NOTHING` in batches — **idempotent and re-runnable**. Verify
row-count == file-count and re-checksum a random sample by reading the bytea back. Skip-and-report
anything over the cap. Optional short-lived dual-read fallback (bytea, then filesystem) during
cutover; drop it once verification passes and filesystem hits hit zero. If many oversized blobs
exist, take the object-storage off-ramp instead of forcing them into bytea.

### Replit deployment specifics
- **Reserved VM**, not Autoscale (Phase 0's durability gate requires the process/disk to persist).
- Replit Secrets hold cloud secrets only (`DATABASE_URL`, `MCP_AUTH_TOKEN`, and the
  declared-optional Phase-3 keys). Read them **only** through `config.py`.
- `DATABASE_URL` = Neon **pooled** (PgBouncer) endpoint. Because PgBouncer runs transaction
  pooling, disable server-side prepared statements where psycopg needs it
  (`prepare_threshold=None`) — verify against Neon's pooled-connstring guidance.
- DB roles: an owner/migrator role for `make migrate`; a read-only role for read paths.

### Tests (first gate; must verify behavior, against a REAL Postgres — not a stub)
`test_round_trip.py` (all 18 tools perform their documented effect, asserting values not types),
`test_sanitize.py` (injection stripped + UNTRUSTED_DATA wrapping), `test_blob_durability.py`
(bytea byte-identical by sha256, size/content_type preserved), `test_idempotency.py` (same
`event_id` twice → one revision), `test_healthz.py` (200/ok healthy, 503 when `SELECT 1` fails).

### Phase 0 done-gate (human sign-off required to advance)
1. `pytest` green; all 18 tools round-trip against real Postgres.
2. **Redeploy the Reserved VM → rows + blobs persist** (the durability proof).
3. `handoff_save` from one surface is read by `handoff_load` on another.
Mock-green alone never ships — live validation is a separate, required gate. **Do not start
Phase 1.**

### Workflow
Develop on a feature branch, commit with clear messages, push that branch, do **not** open a PR
unless asked. Keep the 18 tool contracts unchanged. Produce the sub-spec, stop for approval, then
implement only after sign-off.

## ►►► END COPY ◄◄◄
