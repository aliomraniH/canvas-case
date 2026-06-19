# GLP-1 plugin — local-first multi-agent setup

Five Canvas subagents + deterministic hooks that make them local-first and
safe-by-capability (not by prompt). They talk to the `mcp-assist-memory` service
for shared state.

## Agents (`agents/`)
Invoke explicitly by name (auto-delegation is unreliable):

| Agent | Model | Role |
|---|---|---|
| `capability-check` | sonnet | Confirm an SDK effect/event/model/command exists before code depends on it |
| `conflict-detection` | sonnet | Plan contradictions + pre-commit diff regressions (dup `RESPONDS_TO`, manifest/version drift) |
| `data-integrity` | sonnet | FHIR immutability, read-only data, Effects-only writes, sandbox imports, ZZTEST-only, PHI |
| `ux-conflict` | haiku | Effect collisions across handlers + UX trade-offs |
| `deployment-practices` | sonnet | Deploy/rollback gates against the DEV/UAT host; watch `canvas logs` |

The three safety-critical agents also request a GPT-5.4 second opinion (independent critic).

## Hooks (`hooks/`) — what enforces local-first + safety
- `session_start_load.sh` (SessionStart): print last-known state from cache; pull
  latest if the server is up, else a `STALE` banner. Plan from cache when offline.
- `post_tooluse_log.sh` (PostToolUse Write|Edit): queue a code-change intent with
  a fresh `event_id` + Lamport, `pushed=false`.
- `session_end_reconcile.sh` (SessionEnd/SubagentStop): replay queued intents
  idempotently (server dedupes by `event_id`), then pull others. Offline → leave
  queued, exit 0. `flock`-serialized per agent.
- `pretooluse_guards.sh` (PreToolUse): **exit 2 blocks** FHIR Observation
  PATCH/DELETE, writes to `canvas_sdk.v1.data`, non-allow-listed imports, non-
  `ZZTEST-*` patient writes, and `canvas install` to a non-dev host. Repeat
  identical attempts escalate so the agent can't blindly loop.

## Per-agent environment
Each agent shell sets:
```bash
export AGENT_ID=capability-check          # one of the five (or 'orchestrator')
export MEMORY_SERVER_URL=https://<your-replit-vm>
export MCP_AUTH_TOKEN=<bearer token, matches the server>
# optional: AGENT_CACHE_DIR (defaults to <plugin>/.agent-cache)
```
`.agent-cache/<agent>.db` is a per-agent SQLite mirror (gitignored; WAL +
`busy_timeout`). Different agents never share a DB file.

## Phasing note
Agent definitions + the PreToolUse guards are usable now. The cache/reconcile
hooks implement the Phase 1–2 local-first mechanics; the server-sync push
(`lib/server_sync.py`) is the MCP boundary and **fails open** when the memory
service is offline. Wire it to a live `mcp-assist-memory` deployment before
relying on cross-agent reconcile. Per the build plan these activate behind human
gates — don't enable the guards' enforcement in CI until validated against the
sandbox.
