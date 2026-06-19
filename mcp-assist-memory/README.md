# mcp-assist-memory (Postgres) — shared memory backbone for the Canvas agents

A single FastAPI process that serves the **18-tool memory MCP** over Streamable
HTTP, backed by **Neon Postgres + pgvector**, deployed standalone on a **Replit
Reserved VM**. It is the blackboard / system of record for the Canvas multi-agent
system. Canvas SDK credentials never touch this service.

> **Repo note.** This subtree is a *self-contained, liftable* service. It is
> intended to live in its own repo (`aliomraniH/mcp-assist-memory`) and deploy to
> Replit from there. It sits inside `canvas-case` only because that is the repo
> this build session could write to. The tool surface and `StorageBackend` ABC
> here are the **canonical Phase-0 implementation per the approved spec** — when
> merging into the real `mcp-assist-memory`, reconcile against any pre-existing
> tool signatures. The migration `0001_init.sql` is **frozen**.

## What's implemented (Phase 0)

- One `AsyncConnectionPool` created in the FastAPI `lifespan` (`app.py`), injected
  everywhere. Nothing else opens a connection.
- One `config.py` (`pydantic-settings`) — the only place secrets are read.
- `0001_init.sql`: `memory_entry` (append-only/revisioned), `session` /
  `session_event`, `artifact` (bytea), `CREATE EXTENSION vector` (extension only).
- `PostgresBackend` behind the unchanged `StorageBackend` ABC.
- Write-path `sanitize` + `<<<UNTRUSTED_DATA>>>` wrapping on read.
- `/healthz`, bearer-auth on `/mcp`, streamed `GET /artifact/{sha256}`.
- Bounded lifespan readiness (no unbounded `pool.wait()`), 50 MB artifact cap,
  ranged blob reads, idempotent `event_id` writes, idempotent blob backfill.

**Not in Phase 0** (later phases): embeddings/pgvector recall, coordination tables,
local agent caches/hooks, LangSmith, the critic, promptfoo.

## The 18 tools

| Group | Tools |
|---|---|
| memory | `memory_save` `memory_get` `memory_list` `memory_history` `memory_delete` `memory_search` |
| handoff | `handoff_save` `handoff_load` `handoff_list` |
| session | `session_create` `session_append_event` `session_get` `session_list` `session_events` |
| artifact | `artifact_put` `artifact_get` `artifact_list` |
| admin | `stats` |

`/healthz` is served separately (not an MCP tool).

## Run locally

```bash
cp .env.example .env          # fill DATABASE_URL (Neon pooled) + MCP_AUTH_TOKEN
make install                  # pip install -e ".[test]"
make migrate                  # apply migrations/0001_init.sql
make run                      # uvicorn app:app
curl localhost:8000/healthz   # {"status":"ok","db":"ok"}
```

Tests run against a **real** Postgres (set `DATABASE_URL` to a throwaway Neon
branch); they skip cleanly if it's unset:

```bash
DATABASE_URL=... make test
```

## Deploy on Replit (Reserved VM)

1. Create a Replit from this subtree. In **Secrets**, set `DATABASE_URL` (Neon
   **pooled** endpoint) and `MCP_AUTH_TOKEN` (plus the optional Phase-3 keys).
2. Deploy as a **Reserved VM** (`deploymentTarget = "vm"` in `.replit`) — *not*
   Autoscale; Phase 0's durability gate needs the process/disk to persist.
3. The deploy `run` step runs `python scripts/migrate.py` then starts uvicorn.
4. Point each Claude surface's MCP client at `https://<your-vm>/mcp` with
   `Authorization: Bearer <MCP_AUTH_TOKEN>`.

### Neon

Use the **pooled** connection string (`...-pooler...`). psycopg is configured with
`prepare_threshold=None` for PgBouncer transaction pooling. Use an owner/migrator
role for `make migrate` and a read-only role for read paths.

## Phase 0 done-gate

1. `pytest` green; all 18 tools round-trip against real Postgres.
2. Redeploy the Reserved VM → rows + blobs persist.
3. `handoff_save` on one surface read by `handoff_load` on another.

## Blob migration (filesystem → bytea)

```bash
python scripts/backfill_artifacts.py /path/to/old/blobstore
```
Idempotent (dedup by sha256), streams each file, skips/reports anything over the
50 MB cap, and verifies a random sample by checksum readback.
