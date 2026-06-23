# Deploy runbook — backends + Claude Code startup

The `.claude/` layer here is a **client**. It depends on two MCP services that
run as **two separate Replit deployments** (one repo each). This file is the
durable copy of the deploy prompts and the env contract; the design rationale
lives in `README.md`.

## Topology

| Repl | Repo | Role | DB | Token env (client side) |
|---|---|---|---|---|
| A | `aliomraniH/mcp-assist-memory` | memory + coordination (18 tools) | Postgres + pgvector | `MEMORY_SERVER_URL`, `MCP_AUTH_TOKEN` |
| B | `aliomraniH/canvas-sdk-tools` | static Canvas validator (6 tools) | none | `SDK_TOOLS_URL`, `SDK_TOOLS_TOKEN` |

Two Repls, two **distinct** bearer tokens. There is no live Canvas-instance MCP;
`deployment-practices` reaches DEV/UAT through the `canvas` CLI, not MCP.

## Step 1 — Replit Agent prompt for Repl A (mcp-assist-memory)

> Run this repo as a Replit deployment. Provision Replit's built-in Postgres,
> enable the `pgvector` extension, set `DATABASE_URL` to it, and run migrations
> on boot. Generate `MCP_AUTH_TOKEN` (seeds the first bearer token) and
> `ADMIN_PASSWORD` (gates `/admin`). Serve MCP over Streamable HTTP at
> `POST /mcp/` with `Authorization: Bearer <token>`, and `GET /healthz`
> (no auth) returning exactly `{"status":"ok","db":"ok"}`. Writes are idempotent
> on an `event_id` argument; every per-project tool requires a `namespace`
> argument (no implicit cross-project reads). Prefer an always-on Reserved VM —
> it holds persistent connections. When live, report back: the `.replit.app`
> URL, the bearer token, the output of `curl <url>/healthz`, and a `tools/list`
> dump confirming `memory_save`, `memory_get`, `memory_list`, `handoff_save`,
> and `session_append_event` accept `namespace`, `key`, `value`, `kind`,
> `source_surface`, `event_id`.

## Step 2 — Replit Agent prompt for Repl B (canvas-sdk-tools)

> Run this repo as a Replit deployment. There is no database — reference data is
> baked into the image (`reference/sdk_0.169.x/`). Generate an `MCP_AUTH_TOKEN`
> that is **different** from the memory server's. Serve MCP over Streamable HTTP
> at `POST /mcp/` with `Authorization: Bearer <token>`, and `GET /healthz`
> (no auth) returning `{"status":"ok"}`. Autoscale is fine (stateless/offline).
> When live, report back: the `.replit.app` URL, the bearer token, the output of
> `curl <url>/healthz`, and a `tools/list` dump confirming
> `validate_canvas_capability`, `check_fhir_immutability`, `validate_manifest`,
> `check_sandbox_imports`, `lint_canvas_field_names`, `supported_versions`.

## Step 3 — what the two deployments must hand back

Fill these from the Replit Agent reports; they map 1:1 onto the client env:

```bash
export MEMORY_SERVER_URL=https://<repl-a>.replit.app   # no trailing slash
export MCP_AUTH_TOKEN=<repl-a bearer token>
export SDK_TOOLS_URL=https://<repl-b>.replit.app        # no trailing slash
export SDK_TOOLS_TOKEN=<repl-b bearer token>
export AGENT_ID=orchestrator                            # or a specific subagent
```

`lib/server_sync.py` appends `/mcp/` and `/healthz` itself, so the URLs must be
the bare origin with no trailing slash.

## Step 4 — start Claude Code against this plugin

```bash
cd extensions/growth_charts        # .claude/ must be the project dir
# (env from Step 3 already exported in this shell)
claude
```

Claude Code discovers `.claude/.mcp.json` (expanding `${SDK_TOOLS_URL}` etc.),
applies `.claude/settings.json` (hooks + tool allowlist), and fires
`session_start_load.sh`, which prints `ONLINE` if `MEMORY_SERVER_URL/healthz`
answers and `STALE` otherwise (fail-open, never blocks).

## Tool placement (final)

- **assist-memory** tools are driven by the **hooks** over raw HTTP
  (`MEMORY_SERVER_URL` + `MCP_AUTH_TOKEN`) and are allow-listed for the
  orchestrator session in `settings.json` for manual board reads/writes.
  `memory_delete`, `stats`, and the artifact tools are intentionally **not**
  allow-listed (fail-safe: no destructive/admin calls from a normal session).
- **sdk-tools** tools are wired into the audit agents' `tools:` frontmatter as
  `mcp__sdk-tools__*` (see `README.md` for the per-agent map).
