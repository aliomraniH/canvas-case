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
> `curl <url>/healthz`, and a `tools/list` dump confirming the validator tool
> names `capability`, `fhir_immutability`, `manifest`, `sandbox_imports`,
> `field_names`, `supported_versions`.
>
> NOTE: the live healthz returns `{"status":"ok","version":"...","supported_sdk":[...]}`
> — extra fields beyond `status:ok` are expected; treat `status:ok` as the pass
> condition. The service vendors SDK `0.169.x`; this plugin pins `0.163.1` (see
> the version-skew note at the bottom of this file).

## Step 3 — what the two deployments must hand back

Fill these from the Replit Agent reports; they map 1:1 onto the client env.
You do **not** put tokens in this file — at startup Claude asks you for them and
writes them to a gitignored `.claude/.env` (see Step 4). Template is
`.env.example`:

```bash
MEMORY_SERVER_URL=https://<repl-a>.replit.app   # no trailing slash
MCP_AUTH_TOKEN=<repl-a bearer token>
SDK_TOOLS_URL=https://<repl-b>.replit.app        # no trailing slash
SDK_TOOLS_TOKEN=<repl-b bearer token>            # must differ from MCP_AUTH_TOKEN
AGENT_ID=orchestrator                            # or a specific subagent
```

`lib/server_sync.py` appends `/mcp/` and `/healthz` itself, so the URLs must be
the bare origin with no trailing slash.

## Step 4 — start Claude Code and provide the tokens

Tokens are generated in the Replit dashboard and pasted into Claude at startup;
Claude stores them in `.claude/.env` (gitignored, `chmod 600`) so they persist
locally and never enter git. The hook path reads that file automatically
(`lib/config.py` folds it into the environment). The in-session `canvas-sdk-tools`
MCP server needs the same vars in the launch shell, so the file is sourced before
the real session:

```bash
cd extensions/growth_charts        # project root: holds .mcp.json + .claude/
claude                             # paste the four values when Claude asks; it writes .claude/.env
# then activate the canvas-sdk-tools + Memory_Assist MCP servers for the agents:
set -a; source .claude/.env; set +a; claude
```

`session_start_load.sh` prints `ONLINE` if `MEMORY_SERVER_URL/healthz` answers
and `STALE` otherwise (fail-open, never blocks). Smoke-test the wiring by
invoking `capability-check`, which calls `mcp__canvas-sdk-tools__supported_versions`.

## Tool placement (final)

- **Memory_Assist** tools are driven by the **hooks** over raw HTTP
  (`MEMORY_SERVER_URL` + `MCP_AUTH_TOKEN`) and are allow-listed for the
  orchestrator session in `settings.json` for manual board reads/writes.
  `memory_delete`, `stats`, and the artifact tools are intentionally **not**
  allow-listed (fail-safe: no destructive/admin calls from a normal session).
- **canvas-sdk-tools** tools are wired into the audit agents' `tools:` frontmatter
  as `mcp__canvas-sdk-tools__*`: `capability-check` → `supported_versions`,
  `capability`; `data-integrity` → `fhir_immutability`, `sandbox_imports`,
  `field_names`, `manifest`; `conflict-detection` → `manifest`,
  `supported_versions`.

## SDK version skew (resolution in progress)

The validator vendors only `0.169.x`; `CANVAS_MANIFEST.json` pins `0.163.1`, and
the server rejects `sdk_version=0.163.1` with
`{"ok":false,"error":"unsupported_sdk_version"}`.

**Chosen fix:** add a `0.163.x` reference bucket to the `canvas-sdk-tools` repo
and redeploy Repl B (vendor catalogs/schemas/rules extracted from
`canvas-plugins@0.163.1` into `reference/sdk_0.163.x/`, and have
`supported_versions` return both buckets). The agents already pass
`sdk_version=0.163.1` (the manifest pin) and treat an `unsupported_sdk_version`
reply as a blocking finding — so they validate correctly the moment Repl B ships
the `0.163.x` bucket, with no further change here.
