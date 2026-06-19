# Phase 0 Sub-Spec — Addendum: Architectural Edge Cases & Failure Modes

**Date:** 2026-06-19
**Status:** DRAFT — review addendum. Still spec-and-stop; no implementation code.
**Companion to:** `2026-06-19-mcp-assist-memory-phase0-design.md`
**Reviewer hat:** Principal/Staff — designing for cold starts, partitions, backpressure,
runaway agents, OOM, and lock contention within the *current* plan constraints.

This addendum pins down mitigations for six risks. Where a risk belongs to a later
phase (2/3/4), the mitigation is recorded now so the **frozen** `0001_init.sql` and
the Phase 0 wiring don't have to be re-cut later.

---

## 0. Bug found while reviewing #1

The companion spec's lifespan sketch ends with a bare `await pool.wait()`. With no
timeout that is **the indefinite hang** risk #1 describes: a Neon cold start or a
silent partition parks the FastAPI lifespan forever and the Reserved VM never
becomes ready (and never gets killed/restarted, because it isn't "crashed", just
stuck). Mitigation #1 replaces it.

---

## 1. Lifespan hangs — bound every wait, fail fast, let the VM restart

**Principle:** boot must reach a *terminal* state quickly — either "ready" or
"crash-and-restart" — never "hung". Neon cold start is ~a few hundred ms to a few
seconds; a partition is unbounded. We bound it.

**Pool construction (explicit timeouts, no unbounded waits):**

```python
AsyncConnectionPool(
    settings.database_url,
    open=False,
    min_size=0,                 # do NOT block boot on warming a full pool through a cold Neon
    max_size=10,
    timeout=10.0,               # max seconds a CALLER waits to check out a conn before PoolTimeout
    max_idle=60.0,              # drop idle conns so a scaled-to-zero Neon doesn't keep dead sockets
    reconnect_timeout=30.0,     # give up a single bad connect attempt instead of retrying forever
    num_workers=1,
    kwargs={
        "connect_timeout": 10,          # libpq TCP/handshake cap — caps the cold-start/partition wait
        "options": "-c statement_timeout=15000 "   # 15s server-side stmt cap; no infinite queries
                   "-c idle_in_transaction_session_timeout=15000",
    },
)
```

**Lifespan readiness (bounded, fail-fast):**

```python
await pool.open()                                   # returns immediately; does not wait for min_size
try:
    async with asyncio.timeout(15):                 # HARD cap on boot readiness
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")          # one bounded liveness probe, not pool.wait()
except (TimeoutError, psycopg.OperationalError) as exc:
    log.error("db_not_ready_at_boot", error=str(exc))
    raise                                            # crash → Replit restarts the VM (terminal, not hung)
app.state.pool = pool
```

Key decisions:
- **`min_size=0`** so boot never blocks on warming N connections through a cold DB.
- Replace `pool.wait()` with **one `SELECT 1` under `asyncio.timeout(15)`**.
- On failure we **raise** (terminal crash → supervised restart) rather than swallow
  and serve a half-dead process. `/healthz` then reflects real pool health at runtime
  (it already does its own bounded `SELECT 1` with a short timeout).
- `connect_timeout` + `statement_timeout` ensure *no* code path can wait on the
  network without an upper bound.

---

## 2. Embed-on-write I/O blocking — outbox + background worker, never await Voyage on the write path

**Principle (Phase 3 design, decided now):** `memory_save` commits to Postgres and
returns. It **must not** await Voyage. Embedding is a *derived, eventually-consistent*
property, so we use a **transactional outbox**, not an inline call.

- `0003_knowledge_vector.sql` (Phase 3) gives `knowledge` an `embedding vector NULL`
  plus `embed_status text NOT NULL DEFAULT 'pending'` and `embed_attempts int`.
- On write: insert the row with `embedding=NULL, embed_status='pending'` inside the
  same transaction as the content. `memory_save` returns immediately — its latency is
  pure Postgres, independent of Voyage.
- A **background worker** (an `asyncio.Task` started in the same lifespan, sharing the
  one pool — *not* a second pool) claims pending rows with
  `SELECT ... FOR UPDATE SKIP LOCKED`, calls Voyage with a **bounded** `Http` client
  (timeout, retry-with-backoff, and a simple circuit breaker so a Voyage latency spike
  pauses the worker instead of stampeding), and writes the vector back, flipping
  `embed_status='done'`. Failures increment `embed_attempts` and back off; they never
  touch the caller.
- **`recall.py` degrades gracefully:** rows with `embedding IS NULL` are simply not yet
  semantically searchable; recall falls back to `LIKE`/tag filtering for them. No query
  ever blocks on a missing embedding.

Why outbox over an in-process `asyncio.Queue`: the queue dies with the VM on redeploy
and silently drops pending work; the DB-backed outbox **survives redeploy** and is the
same durability discipline the whole plan is built on. Backpressure is naturally bounded
by the worker's `SKIP LOCKED` claim batch size.

---

## 3. Agent retry loops on a blocked PreToolUse (#3, Phase 4)

**Mechanism (Claude Code semantics):** a PreToolUse hook exiting **code 2** blocks the
call and feeds **stderr back to the model** as the reason. So stderr is our channel —
make it a precise *negative constraint*, not "blocked".

Three layers stop a blind 10× retry:

1. **Actionable stderr.** The guard emits the exact rule, the exact offending target,
   and the allowed alternative, e.g.:
   `BLOCKED: FHIR Observation PATCH is immutable (Create/Read/Search only). Target=Observation/abc. Do NOT retry. Allowed: create a new Observation, or correct via entered_in_error on a new record.`
   A specific, instructional message is far less likely to be re-attempted verbatim
   than a generic denial.

2. **Repeat-attempt detector with escalation (deterministic, not model goodwill).** The
   guard hashes `(tool, normalized_input)` and records attempts in the agent's local
   cache. On the **same** hash:
   - attempt 1–2 → the block message above,
   - attempt ≥3 → escalate: `REPEATED BLOCK (n=3). Stop retrying this action and either choose a different approach or hand off to a human. Further identical attempts will be treated as a loop.`
   This counter is the durable circuit breaker; it holds even if the model "forgets".

3. **Persist the block as negative memory.** The guard writes a
   `kind=decision`, `tags=['forbidden','guardrail']` entry ("agent X attempted PATCH on
   Observation; blocked; rule Y"). `SessionStart` loads these, so the constraint is in
   context *before* planning on the next session — the block becomes a learned boundary,
   not a per-call surprise. (PHI guardrail: store the rule + symbol/ID reference, never
   patient payload.)

Honest limit: a hook cannot *force* a model to stop — but (2) makes continued identical
attempts a no-op the orchestrator can see and halt on, and (1)+(3) make the model far
less likely to retry. The deterministic counter, not the prompt, is the real teeth.

---

## 4. bytea OOM on the Replit VM (#4, Phase 0)

**Principle:** never materialize an unbounded blob in Python on a small VM. Two teeth:

1. **Write-side hard cap.** `MAX_ARTIFACT_BYTES` (proposed **25 MB** for MVP; tune to VM
   RAM). Reject larger writes with a clear error instead of storing them. PG's bytea
   tops out at ~1 GB (TOAST), but the practical limit here is VM memory, not Postgres.
   Content-addressing by `sha256` also dedupes repeat blobs so we don't store N copies.

2. **Read-side bounded/streamed reads.** Don't `SELECT bytes` whole. Read in fixed
   windows with `substring(bytes FROM :off FOR :len)` (e.g., 1 MB chunks) and emit via a
   `StreamingResponse`, so peak memory is one chunk, not the whole artifact. This keeps
   the `bytea` decision (single durable store, survives redeploy) without the OOM risk.

**Escape hatch (stated, not built):** if real artifacts routinely exceed the cap, that's
the signal to take the plan's pre-named **object-storage ABC swap** (S3/R2) and keep only
the `sha256` + metadata in Postgres. The cap is the tripwire that tells us when to do it.

---

## 5. SQLite `database is locked` across overlapping reconciles (#5, Phase 2)

**First, the structural relief:** caches are **per-agent** (`.agent-cache/<agent>.db`), so
two *different* agents reconciling at once touch *different files* — no cross-agent
contention by design. The real risk is *within one agent*: a `SessionEnd` reconcile
overlapping a `PostToolUse` log write, or two instances of the same agent.

**PRAGMAs on every cache connection:**
```sql
PRAGMA journal_mode=WAL;        -- readers don't block the writer; one writer at a time
PRAGMA busy_timeout=5000;       -- wait up to 5s for a lock instead of failing instantly
PRAGMA synchronous=NORMAL;      -- safe with WAL, much less fsync stall
PRAGMA foreign_keys=ON;
```
Plus:
- **`BEGIN IMMEDIATE`** for write transactions (acquire the write lock up front, fail fast
  rather than mid-transaction), and keep transactions **short** (batch the unpushed-event
  replay, don't hold the lock across the network round-trip to the server).
- **Serialize same-agent reconcile** with a per-db advisory file lock: `session_end_reconcile.sh`
  takes `flock .agent-cache/<agent>.db.lock` so two overlapping reconcile runs for the
  same agent queue instead of racing. The network/server work happens *outside* the
  SQLite write transaction.

WAL + a real `busy_timeout` eliminates essentially all transient "database is locked";
`flock` covers the rare same-agent double-run.

---

## 6. Migrating existing filesystem artifacts → bytea (your direct question)

**Reframe:** this is a new Reserved-VM + Neon deploy, so it's a **one-time backfill +
cutover**, not a live dual-write migration. Treat it as content-addressed import.

**Plan:**
1. **Survey first.** Count blobs and the size distribution in the current
   filesystem/SQLite store before doing anything. Two numbers decide the path:
   total count and the **max single-blob size**.
2. **If max size is within the §4 cap (≤25 MB):** a one-time, **idempotent** backfill
   script (`tools/backfill_artifacts.py`, *not* part of frozen `0001`):
   - walk the content-addressed files, **stream** each (don't slurp), compute `sha256`,
     `INSERT ... ON CONFLICT (sha256) DO NOTHING` in batches.
   - idempotent + dedup by construction → safe to **re-run** after an interruption.
   - **verify**: row count == file count, and re-checksum a random sample (and any
     "interesting" ones) by reading back the `bytea` and comparing digests.
   - flag-and-skip anything over the cap into a report rather than aborting the run.
3. **Cutover.** Reads go to `bytea`. A short-lived **dual-read fallback** (try `bytea`,
   fall back to filesystem on miss) can bridge the window if you want zero-downtime; once
   verification passes and the fallback shows zero filesystem hits, drop it and retire the
   files.
4. **If there are many large blobs (cap exceeded at scale):** don't force them into
   `bytea`. That's the §4 escape hatch firing early — keep those in the
   object-storage ABC and migrate only `sha256` + metadata into Postgres. The survey in
   step 1 is what tells us which branch we're on **before** we commit to bytea for the
   whole corpus.

**Net:** the migration is re-runnable, checksum-verified, dedup-safe, and has an explicit
size-based off-ramp to object storage — so a large existing blob corpus can't silently
OOM the import or the VM.

---

## 7. What changes in the companion spec if these are accepted

- **`app.py` lifespan:** replace `await pool.wait()` with the bounded `SELECT 1` readiness
  probe (#1) and add the explicit pool/`kwargs` timeouts.
- **`0001_init.sql` (still freezable):** no change required for #2/#3 — those columns live
  in `0002`/`0003`. `artifact` is unchanged; the §4 cap is enforced in the write path +
  `config.MAX_ARTIFACT_BYTES`, not in DDL.
- **`config.py`:** add `max_artifact_bytes: int = 25 * 1024 * 1024`.
- **New (Phase 0) helper:** `tools/backfill_artifacts.py` for the §6 import (kept out of
  the frozen migration; idempotent and re-runnable).

Awaiting your sign-off on these mitigations before we proceed to the Phase 0
implementation sub-spec / code.
