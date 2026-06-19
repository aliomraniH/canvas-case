# Tier-2 Agent Layer Reuse + Canvas MCP Wiring — Refactor Spec

**Date:** 2026-06-19
**Status:** DRAFT — spec-and-stop. No agent-layer code changes until approved.
**Scope:** one workstream — make the agent layer's Tier 2 liftable, wire the
agents to the (now separate-repo) Canvas MCP, and sequence the cleanup. The
Canvas MCP and `mcp-assist-memory` are separate repos; this repo *consumes* them.

---

## 0. Blocking note: REUSABILITY.md is not in this repo

The instruction was "REUSABILITY.md is in this repo — work to it." It is not
present. I searched the working tree, every branch, and untracked files; the
only "Tier 1–4" strings in the repo are the unrelated **debug-capture browser
tiers** (`extensions/DEBUG_TOOLING.md`, `skills/debug-capture`), not a
reusability tiering doc.

This spec therefore works to the **requirements stated in your message** and
infers the tier vocabulary below. **Reconcile against REUSABILITY.md before
implementation** — if it defines tiers differently, the names here change, not
the structure. Please confirm the file is committed/pushed (or paste it).

**Inferred tier model (to confirm):**

| Tier | Meaning | Examples here |
|---|---|---|
| **Tier 1 — project** | Canvas-specific; swapped per project | `CLAUDE.md` spine, `rules/guards.rules`, `agent.config.json`, `.mcp.json` registration |
| **Tier 2 — liftable** | Generic; copy to any project unchanged | `agents/` skeletons, `hooks/` runners, `lib/` cache + sync + guard engine |
| **Tier 3 — services** | External deployables | `mcp-assist-memory` (own repo/VM), `canvas-sdk-tools` MCP (own repo) |

**Lift test (the acceptance criterion for the whole refactor):** a new project
reuses Tier 2 by supplying only four Tier-1 files — `CLAUDE.md`,
`rules/guards.rules`, `agent.config.json`, `.mcp.json` — and changing nothing
under `agents/`, `hooks/`, or `lib/`. The string `canvas-glp1` appears only in
`agent.config.json`, never in code.

---

## 1. Target layout (after refactor)

```
extensions/growth_charts/
  CLAUDE.md                      # TIER 1 (NEW) — Canvas invariants spine the skeletons inherit
  .claude/
    agent.config.json            # TIER 1 (NEW) — project namespace + paths + env var names
    .mcp.json                    # TIER 1 (NEW) — canvas-sdk-tools + assist-memory MCP registration
    settings.json                # wiring: hooks + perms + mcp enable (paths only, no project strings in logic)
    rules/
      guards.rules               # TIER 1 (NEW) — Canvas guard rule CONTENTS (declarative)
    agents/                      # TIER 2 — five generic skeletons (reference CLAUDE.md + MCP tools)
      capability-check.md
      conflict-detection.md
      data-integrity.md
      ux-conflict.md
      deployment-practices.md
    hooks/                       # TIER 2 — thin generic runners
      session_start_load.sh
      post_tooluse_log.sh
      session_end_reconcile.sh
      pretooluse_guards.sh       # generic: loads rules/guards.rules, does not contain Canvas rules
    lib/                         # TIER 2 — generic, no Canvas imports, generic names
      agent_cache.py
      server_sync.py
      guard_engine.py            # RENAMED from guards.py — generic rule evaluator + repeat-attempt teeth
      hook_session_start.py
      hook_post_tooluse.py
      hook_session_end.py
      config.py                  # NEW — loads agent.config.json; the ONLY reader of project namespace
```

Nothing moves to a new repo in this workstream. The two service repos
(`mcp-assist-memory`, `canvas-sdk-tools`) are referenced, not vendored.

---

## 2. Hooks → generic runner + project ruleset

**Problem today:** `lib/guards.py` hard-codes Canvas rules (the FHIR-PATCH regex,
the `ZZTEST` check, the import allow/deny lists, the dev-host pattern) in the
script body. That is Tier-1 content living in a Tier-2 file.

**Refactor:**

1. **`lib/guard_engine.py` (Tier 2, generic).** A rule evaluator that:
   - reads a ruleset path from `agent.config.json` (default `rules/guards.rules`),
   - evaluates each rule against the PreToolUse `tool_input`,
   - on a match, prints the rule's `reason` + `allowed` to stderr and `exit 2`,
   - keeps the **repeat-attempt counter / escalation** (addendum #3) — that logic
     is generic and stays here.
   - Contains **zero** Canvas strings. No `Observation`, no `ZZTEST`, no
     `canvas_sdk`, no `requests` literal.

2. **`rules/guards.rules` (Tier 1, declarative).** A JSON document holding the
   Canvas rule *contents*. Proposed schema (to finalize):

   ```json
   {
     "version": 1,
     "rules": [
       {"id": "fhir-immutable",
        "when": {"all": [{"field": "*", "matches": "Observation"},
                          {"field": "*", "matches": "\\b(PATCH|DELETE)\\b"}]},
        "reason": "FHIR Observations are immutable (Create/Read/Search only).",
        "allowed": "create a new Observation, or mark the prior one entered_in_error."},
       {"id": "readonly-data",
        "when": {"all": [{"field": "*", "matches": "canvas_sdk\\.v1\\.data"},
                          {"field": "*", "matches": "\\.(save|create|update|delete)\\("}]},
        "reason": "canvas_sdk.v1.data models are read-only.",
        "allowed": "return a typed Effect from compute()."},
       {"id": "sandbox-imports", "type": "import_allowlist",
        "tools": ["Write", "Edit"],
        "allow": ["canvas_sdk", "datetime", "json", "math", "re", "typing", "..."],
        "deny": ["requests", "httpx", "subprocess", "socket", "pickle", "ctypes"],
        "reason": "import not on the sandbox allow-list.",
        "allowed": "use canvas_sdk.utils.http.Http; no raw network/process libs."},
       {"id": "zztest-only", "type": "patient_write_scope", "require": "ZZTEST",
        "reason": "Live writes may target ZZTEST-* test patients only.",
        "allowed": "use a ZZTEST-* patient; existing patients are read-only."},
       {"id": "dev-host-only", "type": "command_host_allowlist",
        "tools": ["Bash"], "command_matches": "canvas\\s+install",
        "host_allow": "(dev|uat|sandbox|localhost|127\\.0\\.0\\.1)",
        "reason": "canvas install may target the DEV/UAT host only.",
        "allowed": "pass a dev/uat/sandbox host; prod requires human sign-off."}
     ]
   }
   ```

   The engine supports a small fixed set of rule `type`s (`match`/default,
   `import_allowlist`, `patient_write_scope`, `command_host_allowlist`) so the
   Canvas specifics are pure data. Adding a project = writing a new `.rules`,
   not editing code.

3. **`hooks/pretooluse_guards.sh`** stays a thin wrapper:
   `exec python3 ../lib/guard_engine.py` (ruleset path comes from config).

**Cache + reconcile/sync stay Tier 2.** `agent_cache.py`, `server_sync.py`, and
the three `hook_*.py` already avoid Canvas imports. Refactor touches:
- move the two hardcoded namespaces in `server_sync.py` (`"intents"`, `"plan"`)
  into `agent.config.json` (`memory_namespace`, `intent_namespace`),
- read them via `lib/config.py`, so no project string is literal in code.

---

## 3. Agent skeletons reference CLAUDE.md, not embedded invariants

**Problem today:** `data-integrity.md`, `capability-check.md`, etc. embed the
Canvas invariants (field-name traps, ZZTEST, FHIR rules) in the prompt body —
Tier-1 content in Tier-2 files.

**Refactor:** each skeleton body becomes generic:
- "Audit the proposed change against the invariants in **`CLAUDE.md`** (the
  project spine). Do not assume invariants not stated there."
- "For deterministic checks, call the registered project capability/validation
  MCP tools (§4); keep your own reasoning for judgment/synthesis."
- Return contracts (the JSON shapes) stay — they're generic.
- **Frontmatter** keeps generic fields (`name`, `description`, `tools`, `model`).
  The `tools` list adds the MCP tool names (§4) but names no Canvas rule.

**`CLAUDE.md` spine (Tier 1, NEW).** Create
`extensions/growth_charts/CLAUDE.md` carrying the Canvas invariants the
skeletons inherit (FHIR immutability, read-only data, Effects-only writes,
sandbox allow-list, ZZTEST-only, PHI handling, the field-name traps:
`obs.units`, `dbid__in`, `lb`, `from __future__ import annotations`, `.get()`
for underscore keys — these are already verified facts in
`skills/build-discipline/SKILL.md` Gate 1 and should be cited, not re-derived).
Another project swaps this file + `guards.rules` + `.mcp.json` and reuses the
five skeletons verbatim.

> Note: the repo root already has a `CLAUDE.md` (repo-wide reviewer context).
> The plugin spine is plugin-scoped and lives under the plugin dir; it does not
> replace the root file.

---

## 4. Wire agents to consume the Canvas MCP (`canvas-sdk-tools`)

**Principle:** don't rebuild Canvas logic in agent prompts — the Canvas MCP owns
the deterministic checks. Agents call it for facts and keep prompt logic for
judgment/synthesis.

1. **Registration — `.claude/.mcp.json` (Tier 1):**
   ```json
   {
     "mcpServers": {
       "canvas-sdk-tools": {
         "type": "http",
         "url": "${CANVAS_MCP_URL}",
         "headers": { "Authorization": "Bearer ${CANVAS_MCP_TOKEN}" }
       },
       "assist-memory": {
         "type": "http",
         "url": "${MEMORY_SERVER_URL}/mcp",
         "headers": { "Authorization": "Bearer ${MCP_AUTH_TOKEN}" }
       }
     }
   }
   ```
   URL + token come from env (never committed). `canvas-sdk-tools` has its **own**
   bearer token, distinct from the memory server's.

2. **Deterministic checks routed to the Canvas MCP:**

   | Agent | Canvas MCP tools it calls (facts) | Keeps in prompt (judgment) |
   |---|---|---|
   | capability-check | `validate_canvas_capability`, `validate_manifest`, `lint_canvas_field_names` | gap-analysis synthesis, WORKAROUND framing |
   | data-integrity | `check_fhir_immutability`, `check_sandbox_imports`, `lint_canvas_field_names`, `validate_manifest` | invariant-to-acceptance-criteria mapping, PHI judgment, critic synthesis |

   The skeletons reference these tools by name and say "prefer the MCP's
   deterministic result over your own assertion." conflict-detection /
   ux-conflict / deployment-practices keep their current tool sets (they're not
   listed for MCP wiring in this workstream).

3. **Credential boundary (hard):** the Canvas MCP does **deterministic static
   checks only** and **never receives Canvas credentials**. **Live sandbox
   validation stays local** in `deployment-practices`, using `~/.canvas/
   credentials.ini` on the machine. Creds never leave the machine; the Canvas
   MCP URL/token are not creds to the Canvas instance.

4. **Tool allow-lists:** add the specific `mcp__canvas-sdk-tools__*` tool names
   to the two agents' `tools` frontmatter and to `settings.json` permissions, so
   the wiring is least-privilege (each agent can call only the MCP tools it needs).

---

## 5. `agent.config.json` (Tier 1) — the only place the project namespace lives

```json
{
  "project": "canvas-glp1",
  "claude_md": "../CLAUDE.md",
  "guards_rules": "rules/guards.rules",
  "memory_namespace": "canvas-glp1",
  "intent_namespace": "canvas-glp1:intents",
  "env": {
    "memory_server_url": "MEMORY_SERVER_URL",
    "memory_token": "MCP_AUTH_TOKEN",
    "canvas_mcp_url": "CANVAS_MCP_URL",
    "canvas_mcp_token": "CANVAS_MCP_TOKEN",
    "agent_id": "AGENT_ID"
  }
}
```

`lib/config.py` is the sole reader. Grep-gate (mirrors the memory server's
`config.py` discipline): the literal `canvas-glp1` must not appear anywhere under
`lib/`, `hooks/`, or `agents/`.

---

## 6. Cleanup sequencing (do NOT strip early)

The `mcp-assist-memory/` subtree currently in this repo is the working copy.
**Remove it only after** the standalone `aliomraniH/mcp-assist-memory` repo is
confirmed canonical and deployed. Coordinated steps, in order:

1. Confirm the standalone repo holds the canonical service (history reconciled,
   18 tools matched to the real ABC).
2. Confirm the VM deploy is live and `/healthz` is green.
3. Repoint every reference (this repo's READMEs, `.mcp.json` `assist-memory`
   URL) at the deployed VM.
4. `git rm -r mcp-assist-memory/` in its own commit, verifying nothing in this
   repo imports it (it's standalone, so nothing should).

Until all four hold, the subtree stays. This spec does not delete it.

---

## 7. Next step after deploy (separate task, not this spec's code)

Once the memory server is on its VM: wire `server_sync.py` to the live server and
validate the local-first loop both ways. Acceptance matrix:

| Condition | SessionStart | PostToolUse | SessionEnd | Invariant |
|---|---|---|---|---|
| **Server up** | pulls latest, prints fresh state | logs intent (event_id+Lamport) | reconciles: pushes queued intents | server has each intent exactly once |
| **Server down** | prints cache + STALE banner | logs intent locally | leaves queued, exit 0 | no work lost |
| **Down → up (reconnect)** | — | — | replays queue idempotently | **no double-apply** (event_id dedupe), no lost update |

This is the live, second-gate validation (mock-green is not done) per
`skills/build-discipline`. It runs after VM deploy, not in this refactor.

---

## 8. Out of scope / discipline

- No new behavior — this is a **reuse refactor**: same guard outcomes, same
  hook behavior, same agent contracts, reorganized along the tier boundary.
- Don't rebuild Canvas logic that the Canvas MCP owns (§4).
- Per `REVIEW.md`/`build-discipline`: no over-development, mock-green isn't the
  gate, write only inside the agent-layer boundary.

---

## 9. Checkpoint (human gate before code)

1. Confirm REUSABILITY.md (or accept the §0 inferred tier model).
2. Confirm the `guards.rules` schema (§2) and `agent.config.json` shape (§5).
3. Confirm the Canvas MCP tool names (§4) match the `canvas-sdk-tools` repo.

On approval, implement the refactor (no logic change), then proceed to §7 after
the VM is live.
