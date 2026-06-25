# Reusability Contract & Service Topology

**Commit this file as `REUSABILITY.md` to all three repos.** Both Claude Code agents must read it before building and treat conflicts with it as bugs.

---

## The contract, in one line

**Project identity lives in namespace *values*, ruleset files, and `CLAUDE.md` — never in a generic server's tool names, schema, columns, comments, or code.** `canvas-glp1` is legal as a config string; it is never legal as a tool name, a table/column name, or a hard-coded constant in Tier 1 or Tier 2.

---

## Three tiers — and what is allowed to say "canvas"

| Tier | What's in it | Reusable by | May contain project names? | Owner repo |
|---|---|---|---|---|
| **1 — Generic server** | The 18 memory/session/artifact tools, coordination (task board, leasing, intents), semantic recall, storage, sanitize | Every Claude Code project | **No.** Zero domain terms anywhere | `mcp-assist-memory` |
| **2 — Agent machinery** | Local-first cache lib, the four hooks *as generic runners*, the reconcile/sync boundary, the five agent *skeletons* (role + output schema + invoke pattern) | Any project, by copy/reference | **No.** Generic names; project content injected, not hard-coded | lives in `canvas-case` now, **liftable** |
| **3 — Canvas project pack** | `CLAUDE.md` invariants, the FHIR/ZZTEST rule *contents* (in a ruleset file), Canvas SDK knowledge, and the **Canvas-specific MCP** | Canvas only | **Yes** — the "very unique and specific" exception | `canvas-case` + new `canvas-sdk-tools` |

---

## Data separation: namespace is the tenant boundary

- **One namespace per repo** (`canvas-case`), with conventional sub-scopes by key prefix: `coord/…`, `knowledge/…`, `session/…`. Other repos/projects (`acme-billing`, …) get their own namespace and never see this repo's data. **The single source of truth is `agent.config.json:memory_namespace`** — every surface reads it; no one hard-codes or guesses a namespace string.
  > **DECISION 2026-06-25 (user).** This boundary was originally *one namespace per **plugin*** (`canvas-glp1`). Because Web/CLI/Desktop sessions drifted (CLI/Desktop wrote to `canvas-case`, Web to `canvas-glp1`), we collapsed to **one shared namespace per repo: `canvas-case`**. Trade-off accepted: plugins **inside** this monorepo no longer get separate namespaces (they share `canvas-case` and must self-scope by key prefix, e.g. `coord/cardiometabolic_tracker/…`). Isolation vs **other** repos is unchanged.
- **A `project` column on every coordination and knowledge table**, indexed, and **every query filters on it**. No implicit cross-project reads, ever.
- **Honest limit:** under one shared `MCP_AUTH_TOKEN`, namespace is a *soft* boundary — any client with the token can pass any namespace. It is real isolation for honest clients, not enforced against a misbehaving one. **Durable fix = per-namespace tokens/roles (v2 auth):** a token scoped to `canvas-case` can't touch `acme-billing`. Put this on the v2 roadmap now.
- **Tests use a neutral project** (`proj-test`), never `canvas-case`.

---

## The naming litmus test

For anything about to be named: **"Would a non-Canvas project want this verbatim?"**
- **Yes → Tier 1/2, generic name.** `detect_write_conflict`, `task_claim`, `memory_search`, `capability-check` (the skeleton). No "canvas", "glp1", "fhir", "zztest".
- **No, it's inherently Canvas → Tier 3.** A FHIR-immutability guard or a Canvas-SDK capability lookup is legitimately Canvas-named — but it lives in the agent pack or the `canvas-sdk-tools` MCP, **never** bolted into `mcp-assist-memory`.

---

## Service topology — three repos, two MCP servers on Replit

```
   Claude surfaces:  web (plan)   CLI (build)   Desktop (review)
                         │            │              │
        ┌────────────────┼────────────┼──────────────┼─────────────┐
        │   MCP #1 (generic)          │   MCP #2 (Canvas-only)      │
        ▼                             ▼                             │
 ┌──────────────────────┐   ┌──────────────────────────┐          │
 │ Replit Reserved VM A  │   │ Replit Reserved VM B      │          │
 │ mcp-assist-memory     │   │ canvas-sdk-tools          │          │
 │ (Tier 1, all projects)│   │ (Tier 3, Canvas only)     │          │
 │  + Neon Postgres      │   │  STATIC checks, stateless │          │
 └──────────────────────┘   └──────────────────────────┘          │
                                                                    │
 plugin repo (NOT a service):  canvas-case  ── Tier 2 machinery + Tier 3 pack
                               local CLI/Desktop reach the Canvas SANDBOX
                               using ~/.canvas creds (creds never leave the machine)
```

**Three repos, three deploy units:**
1. `mcp-assist-memory` → Replit Reserved VM **A** + Neon. Generic, every project.
2. `canvas-sdk-tools` (NEW) → Replit Reserved VM **B**. Canvas-only MCP.
3. `canvas-case` → not a service; holds the plugin, the agent machinery, and the Canvas pack.

> The two services get **separate repos and separate VMs** precisely because burying a deployable service as a subtree in the plugin repo is what caused the duplicate-build fork. Services get service treatment.

---

## Canvas MCP (`canvas-sdk-tools`) — hard constraints

- **Static / offline only.** Its tools validate code and specs against the **vendored** Canvas SDK surface (capability catalog, FHIR interaction rules, manifest schema, sandbox import allow-list). 
- **No Canvas credentials, ever.** Live sandbox validation stays with the **local** CLI using local creds — putting creds on a cloud VM would break the "creds never leave the machine" rule. The Canvas MCP does not call a Canvas instance.
- **No PHI.** It sees code and specs, not patient data.
- **Stateless.** It keeps no per-project state; if it caches the SDK surface, that's vendored reference data, not tenant data.
- **Its own `MCP_AUTH_TOKEN`**, distinct from the memory server's. Canvas surfaces only.
- **Same clean pattern as the memory server:** `config.py` via `pydantic-settings`, single structure, `/healthz`, `structlog` JSON. Canvas-named tools are fine here (`validate_canvas_capability`, `check_fhir_immutability`, `validate_manifest`, `check_sandbox_imports`).

---

## Updated cross-surface access matrix

| Capability | Web (plan) | CLI (build) | Desktop (review) | memory-server CC | canvas-sdk-tools |
|---|---|---|---|---|---|
| Memory MCP — read | ✓ | ✓ | ✓ | test-only | — |
| Memory MCP — write | handoff/decision/note only | ✓ (via hooks) | ✗ | ✗ | — |
| **Canvas MCP** (`canvas-sdk-tools`) | ✓ (planning capability checks) | ✓ | ✓ (review) | ✗ | self |
| Voyage embeddings | ✗ | ✗ | ✗ | ✗ | ✗ — **memory VM only** |
| OpenAI GPT-5.4 critic | ✗ | ✓ (3 critic agents) | ✗ | ✗ | ✗ |
| LangSmith / OTel | ✗ | ✓ | ✗ | optional | optional |
| Canvas SDK creds + sandbox | **✗ never** | ✓ local | ✓ local (read) | ✗ | **✗ never** |
| Commit rights | ✗ | ✓ canvas-case | review file only | ✓ memory repo | ✓ canvas-sdk-tools |

Enforce Desktop's read-only status **client-side** via `allowedTools` (memory: get/list/search/history, session get/list, artifact_get, server_status; plus the Canvas MCP read tools). Server-side enforcement waits for per-project/per-agent tokens (v2). *Capabilities constrain action; instructions only constrain intent.*

The **CLI orchestrator is the single writer to memory per session** (via SessionEnd/PostToolUse hooks). The five subagents read and return structured results to the orchestrator; they do not each write to memory. One writer per session removes a class of races.

---

## Where each rule is enforced

| Concern | Tier 1 (`mcp-assist-memory`) | Tier 2 (machinery) | Tier 3 (Canvas pack + `canvas-sdk-tools`) |
|---|---|---|---|
| Domain names | banned | banned | allowed |
| Tenant isolation | `project` column + namespace + (v2) token | passes `project` through, hard-codes nothing | uses `canvas-glp1` from config only |
| FHIR/ZZTEST rules | none | generic guard *runner* reads a ruleset | rule *contents* live here (`guards.rules`, `CLAUDE.md`) |
| Canvas SDK knowledge | none | none | vendored here |
| Secrets | own token, Neon, Voyage | none | own token (Canvas MCP); Canvas creds local-only |
