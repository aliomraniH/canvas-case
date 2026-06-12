---
name: debug-capture
description: >
  Use this skill for ANY browser-based debugging, testing, or visual investigation
  task in Claude Code. Triggers on: "debug this", "test the UI", "capture a
  screenshot", "run visual tests", "check accessibility", "profile performance",
  "inspect network calls", "capture console errors", "compare to Figma",
  "use Figma as reference", "investigate why this is broken", "run a debug
  session", "capture API calls", "store test results", "create a test scenario
  from this failure", "generate a test script". Each session gets its own
  timestamped folder under .workspace_state/debug/ with structured JSON logs
  readable by Claude Code, Claude.ai, and future agents. Always use this skill
  before any debugging, screenshot, or browser testing work — it defines the
  session structure, mode selection, capture format, and agent-handoff output.
---

# Debug Capture Skill

A general-purpose browser debugging and visual testing framework.
Every session is self-contained, timestamped, and structured for reuse
by Claude Code, Claude.ai, and future autonomous agents.

---

## Quick start

```
Mode options: visual | accessibility | performance | network | console | figma-reference | full
```

When the user asks to debug or test, ask:
> "Which debug mode? `full` runs all of them.
> Options: `visual` `accessibility` `performance` `network` `console` `figma-reference`"

If the user says "just debug it" or doesn't specify → use `full`.

---

## Credentials — never hardcode

All Canvas credentials live in one gitignored file:
`<repo>/extensions/.env`
(keys: `CANVAS_HOST`, `CANVAS_USERNAME`, `CANVAS_PASSWORD`,
`CANVAS_CLIENT_ID`, `CANVAS_CLIENT_SECRET`).

- **Scripts** load them with `dotenv`:
  ```javascript
  import { config } from 'dotenv';
  config({ path: '<repo>/extensions/.env' });
  const { CANVAS_USERNAME, CANVAS_PASSWORD } = process.env;
  ```
- **Bash** loads them with `set -a; source extensions/.env; set +a`.
- **Browser login steps**: read the values from `.env` at run time and type
  them into the login form. Never write the literal username or password into
  a prompt, doc, session artifact, brief.md, or test_deploy.sh — reference
  `.env` instead.
- If `.env` is missing a needed key, stop and ask the user — do not fall back
  to a remembered or hardcoded value.

---

## Step 1 — Create the session folder

```python
import os, datetime, json

session_id = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%SZ') + '_' + mode.replace('+', '-')
base = '<repo>/extensions/.workspace_state/debug'
session_dir = f'{base}/{session_id}'

os.makedirs(f'{session_dir}/screenshots', exist_ok=True)
os.makedirs(f'{session_dir}/api-calls',   exist_ok=True)
os.makedirs(f'{session_dir}/snapshots',   exist_ok=True)
os.makedirs(f'{session_dir}/performance', exist_ok=True)
os.makedirs(f'{session_dir}/figma-reference', exist_ok=True)
os.makedirs(f'{session_dir}/agent-handoff',   exist_ok=True)
```

Initialize `session.json` immediately — read schema from `references/session-schema.md`.

Tell the user:
> "Session `[session_id]` created. Starting [mode] capture."

---

## Step 2 — Navigate and capture

Read `references/mode-playbooks.md` for the exact steps for the selected mode(s).

Summary of what each mode captures:

| Mode | What it does |
|---|---|
| `visual` | Screenshots + d3/SVG element detection via `evaluate_script` |
| `accessibility` | Full WCAG audit via `take_snapshot` + accessibility tree |
| `performance` | Core Web Vitals (LCP, CLS, INP, TBT) via Chrome DevTools |
| `network` | All FHIR/API requests + full response bodies during test |
| `console` | Browser console errors, warnings, unhandled rejections |
| `figma-reference` | Use a Figma file as source of truth — read `references/figma-integration.md` |
| `full` | All of the above, in order: network+console first, then interact, then visual+accessibility+performance |

For `full` mode, always start network and console capture BEFORE navigating
or clicking, so API calls made during page load are included.

---

## Step 3 — Write results to session.json

After each mode completes, update `session.json` with results.
Never overwrite — always merge into the existing file.
Read full schema from `references/session-schema.md`.

Key fields to update after every capture:
- `results.passed` / `results.failed` / `results.errors[]`
- `artifacts` — add paths to every file created
- `metadata.ended_at` — update on completion

---

## Step 4 — Generate agent handoff

Always run this at the end of every session, even if no failures.

Read `references/agent-handoff.md` for the full format.

Produces two files:
1. `agent-handoff/brief.md` — human-readable summary + suggested next actions
2. `agent-handoff/test_deploy.sh` — executable script to rerun or extend tests

Update `session.json`:
```json
"agent_handoff": {
  "brief": "agent-handoff/brief.md",
  "deploy_script": "agent-handoff/test_deploy.sh",
  "rerun_command": "bash .workspace_state/debug/<session_id>/agent-handoff/test_deploy.sh"
}
```

---

## Step 5 — Figma upload (optional)

After session completes, ask:
> "Upload screenshots to Figma? (new file / existing file / skip)"

If yes, read `references/figma-integration.md` for upload steps.
For `figma-reference` mode, comparison and diff report are already captured
during Step 2 — the upload step just packages them.

---

## File structure reference

```
.workspace_state/debug/
└── 2026-06-09T14-30-00Z_full/
    ├── session.json              ← master record (agent-readable)
    ├── screenshots/
    │   ├── 001_dashboard.png
    │   └── 002_chart_modal.png
    ├── api-calls/
    │   ├── network_log.json      ← all requests + full response bodies
    │   └── console_log.json      ← errors, warnings, unhandled rejections
    ├── snapshots/
    │   └── accessibility_tree.json
    ├── performance/
    │   └── core_web_vitals.json
    ├── figma-reference/
    │   ├── reference_node.png    ← screenshot from Figma design
    │   └── diff_report.json      ← structured visual diff
    └── agent-handoff/
        ├── brief.md              ← LLM-readable summary + suggestions
        └── test_deploy.sh        ← runnable test script
```

---

## Reference files

Load these on demand — do NOT load all at once:

- `references/session-schema.md` — full JSON schemas for session.json,
  network_log.json, console_log.json, core_web_vitals.json, diff_report.json.
  Load when initializing a session or writing results.

- `references/mode-playbooks.md` — exact step-by-step instructions for each
  debug mode. Load when starting capture for a given mode.

- `references/agent-handoff.md` — format and generation logic for brief.md
  and test_deploy.sh. Load when generating handoff at end of session.

- `references/figma-integration.md` — Figma upload flow, all three reference
  modes (URL / named frame / auto-detect), and comparison diff logic.
  Load for any Figma-related step.
