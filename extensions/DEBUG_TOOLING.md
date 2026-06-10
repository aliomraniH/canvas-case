# Debug Tooling Guide

**Location:** `extensions/.workspace_state/debug/`
**Skill:** `~/.claude/skills/debug-capture/`
**Last validated:** 2026-06-10 against `pxbuilder-aomrani.canvasmedical.com`

This document covers the full debugging toolbox for the Canvas plugin project.
Read the complexity guide before reaching for any tool — most issues don't need
a full debug session.

---

## Complexity guide — pick the right tool

Debugging overhead should match the problem. Using the full skill for a quick
deploy check wastes time; using a one-liner for a visual regression misses
evidence. The table below is the decision entry point.

| Tier | When to use | Tool | Time |
|---|---|---|---|
| **0 — Deploy check** | "Is it installed and enabled?" | `canvas list` | 5 sec |
| **1 — Quick look** | "Does it render / is there an error?" | One-liner snippet | 1 min |
| **2 — Targeted assertion** | "Does element X exist?" | `evaluate_script` one-liner | 2 min |
| **3 — Focused investigation** | "Why is this failing?" 1–2 modes | debug-capture (selected modes) | 5–10 min |
| **4 — Full session** | Visual regression, agent handoff, Figma compare | debug-capture full | 10–20 min |
| **5 — New tool** | Tier 4 doesn't cover the need | Build alongside, don't modify skill | open |

**Default to the lowest tier that answers the question.** Move up only when the
lower tier leaves something unresolved.

---

## Tier 0 — Deploy check (5 seconds)

```bash
canvas list --host pxbuilder-aomrani
```

Confirms: plugin is installed, version number, enabled/disabled state.
Use this before anything else. If the plugin isn't listed, nothing else matters.

```bash
# Check a specific plugin
canvas list --host pxbuilder-aomrani | grep cardiometabolic
# Expected: cardiometabolic_tracker@0.1.3   enabled
```

---

## Tier 1 — Quick look (1 minute)

Use when you want to see the current state of the instance without starting a
full session. Paste directly into the Claude Code Desktop integrated terminal or
CLI session.

**Check canvas logs (last 30 lines):**
```bash
# NB: `--host` flag is required (CLI 0.163.1); bare positional arg errors.
# `canvas logs` streams — background it and kill after a few seconds:
canvas logs --host pxbuilder-aomrani > /tmp/canvas_logs.txt 2>&1 & sleep 10; kill %1; tail -30 /tmp/canvas_logs.txt
```

**Quick screenshot — no session folder created:**
In a `claude --chrome` session:
```
Navigate to https://pxbuilder-aomrani.canvasmedical.com/ and take a screenshot.
Do not create any session folder. Just show me the current state.
```

**Check plugin is rendering (no assertions, no artifacts):**
```
Open https://pxbuilder-aomrani.canvasmedical.com/, log in with the credentials
from extensions/.env (CANVAS_USERNAME / CANVAS_PASSWORD), open Lori Collins'
chart, click Weight Trajectory, and tell me if the chart renders. One sentence
answer. No files.
```

---

## Tier 2 — Targeted assertion (2 minutes)

For single-element checks. Use `evaluate_script` directly without a full skill
invocation. Paste the snippet into a `claude --chrome` session after navigating
to the right page.

**Check SVG and data points:**
```javascript
const svg = document.querySelector('iframe[src="about:srcdoc"]')
  ?.contentDocument?.querySelector('svg');
const circles = svg?.querySelectorAll('circle') || [];
const dashed = svg?.querySelectorAll('line[stroke-dasharray]') || [];
const texts = [...(svg?.querySelectorAll('text') || [])]
  .map(t => t.textContent.trim()).filter(Boolean);
return {
  svg_present: !!svg,
  data_points: circles.length,
  baseline_line: dashed.length > 0,
  annotations: texts.filter(t => t.includes('%') || t.includes('TBWL'))
};
```

**Check for error state:**
```javascript
const iframe = document.querySelector('iframe[src="about:srcdoc"]');
const body = iframe?.contentDocument?.body?.textContent || '';
return {
  has_error: body.includes('Cannot') || body.includes('error') || body.includes('Error'),
  snippet: body.substring(0, 200)
};
```

**Check specific patient URL is loadable:**
```javascript
return {
  url: window.location.href,
  title: document.title,
  patient_key: window.location.pathname.split('/patient/')[1]?.split('/')[0]
};
```

---

## Tier 3 — Focused investigation (5–10 minutes)

Use when a Tier 2 check reveals a problem but not the cause. Select only the
modes relevant to the failure — do not run full.

```
Run a debug-capture session in [mode] mode only against [URL].
Context: [what you observed at Tier 2].
Do not run other modes. Write artifacts to .workspace_state/debug/.
```

**Common mode selections by symptom:**

| Symptom | Use mode |
|---|---|
| Chart renders but wrong data | `visual` — check DOM values from iframe srcdoc |
| Button not appearing | `accessibility` — check button is in the accessibility tree |
| Page slow to load | `performance` — check LCP, TTFB, resource timing |
| Unexpected error in logs | `console` — capture full stack trace with source line |
| Auth/API failure | `network` — capture GraphQL render event + REST calls |
| Doesn't match design | `figma-reference` — compare to Figma node |

---

## Tier 4 — Full debug session (10–20 minutes)

Use for:
- Pre-submission verification of a new plugin version
- Visual regression against a Figma reference
- Producing an agent-readable brief for a complex failure
- Any situation where you need persistent artifacts for later review

```
Run a full debug-capture session against [URL].
Patient: [name]. Action: [what to click].
Upload screenshots to Figma file zhU3thHKxOblc5D9dL7hbl.
Write agent-handoff brief at the end.
```

The session creates a timestamped folder with all artifacts. See
[Session structure](#session-structure) below.

---

## Tier 5 — New tool (open-ended)

When debug-capture doesn't cover the need, build a new tool alongside it.

**The non-interference rule:** Do not modify `~/.claude/skills/debug-capture/`
to add new capabilities. That skill has a defined scope (browser-based
debugging, visual capture, agent handoff). A new need that falls outside that
scope gets its own tool, its own skill file, or its own script.

**Where new tools go:**
```
extensions/
├── .workspace_state/
│   └── debug/              ← debug-capture session artifacts
│       └── tools/          ← NEW: standalone debug scripts live here
│           ├── capture_lori_collins.js   ← Playwright session script
│           └── [new_tool].js
└── .claude/
    └── skills/
        └── debug-capture/  ← do not modify for new tool needs
```

**Signal that you need a new tool (not a skill modification):**
- Needs a language or runtime debug-capture doesn't use (e.g. native mobile)
- Requires persistent state across multiple sessions (debug-capture is per-session)
- Is a production monitoring tool, not a development debugging tool
- Has a CI/CD trigger rather than a human trigger

---

## Canvas-specific architectural findings

These are findings from live sessions that change how you debug this plugin.
Read before debugging data or rendering issues.

### Plugin data access is server-side

The cardiometabolic tracker fetches weight observations via the Canvas SDK ORM
(`canvas_sdk.v1.data`) running on the Canvas server — not via browser FHIR
calls. This has three consequences:

1. **No `GET /api/r4/Observation` calls appear in the browser** when the Weight
   Trajectory button is clicked. Network interception will never show them.
2. **The only browser-visible signal is a single GraphQL POST** — the plugin
   render event. Capturing this confirms the button was clicked and the plugin
   was invoked, but tells you nothing about the data it received.
3. **Weight data is embedded in the `about:srcdoc` iframe content** at render
   time. To inspect what data the plugin received, read the iframe DOM directly:

```javascript
const iframe = document.querySelector('iframe[src="about:srcdoc"]');
const iframeDoc = iframe?.contentDocument;
// The graphs[] array is injected as a script tag or window variable
const scriptTags = [...(iframeDoc?.querySelectorAll('script') || [])];
return scriptTags.map(s => s.textContent.substring(0, 300));
```

### Canvas API URL structure

Canvas REST API uses `/api/<Resource>/` (not `/api/r4/` FHIR format):
```
/api/Patient/
/api/Observation/
/api/Condition/
```

Route interception pattern for capturing Canvas API calls:
```javascript
await context.route(url => {
  const host = new URL(url).hostname;
  const path = new URL(url).pathname;
  return host === 'pxbuilder-aomrani.canvasmedical.com'
    && path.startsWith('/api/');
}, async route => {
  const response = await route.fetch();
  // log request + response
  await route.fulfill({ response });
});
```

### Plugin iframe is sandboxed (`about:srcdoc`)

The modal runs in a sandboxed iframe with `src="about:srcdoc"`. This means:
- `window.frames` from the parent page cannot access iframe content without
  explicit `contentDocument` reference
- SVG elements rendered by d3.js are not in the parent page accessibility tree
- Visual assertions must use `iframe.contentDocument.querySelector(...)` not
  `document.querySelector(...)`

### Playwright session handles login

Chrome cookies from a user profile do not transfer to Playwright. Each debug
session must log in headlessly. The working script is at:
```
.workspace_state/debug/capture_lori_collins.js
```
Credentials come from `.env` — no flags or env var exports needed.

### Lori Collins patient URL

Lori Collins' chart is at a stable URL (confirmed from DOM extraction):
```
/patient/0af123e5cc74483095399463fff6f002
```
Weight Trajectory button is in the Vital Signs section. Button text: `Weight Trajectory`.

---

## Credential management

Credentials are stored in a single `.env` file — never in scripts, session
artifacts, or committed files.

**Location:**
```
extensions/.env        ← actual values, gitignored
extensions/.env.example ← placeholder template, committed
```

**Contents of `.env`** (real values live only in the local gitignored file —
see `.env.example` for the template):
```
CANVAS_HOST=pxbuilder-aomrani.canvasmedical.com
CANVAS_USERNAME=<clinician username>
CANVAS_PASSWORD=<clinician password>
CANVAS_CLIENT_ID=<OAuth client id — see ~/.canvas/credentials.ini>
CANVAS_CLIENT_SECRET=<OAuth client secret — see ~/.canvas/credentials.ini>
```

**`.gitignore` entries (already in place):**
```
.env
.env.*
*.env
```

**`~/.canvas/credentials.ini`** — Canvas CLI credentials for deployment:
```ini
[pxbuilder-aomrani]
client_id=<client id>
client_secret=<client secret>
is_default=true
```
This file is on the local machine only, never in the repo.

**How scripts read credentials:**
```javascript
// In capture_lori_collins.js and any new tools
import { config } from 'dotenv';
config({ path: '/Users/aliomrani/Documents/Canvas-case/canvas/extensions/.env' });
const { CANVAS_USERNAME, CANVAS_PASSWORD } = process.env;
```

**Rule:** Never type a raw credential value into a script, session artifact,
prompt, or doc — including this one. Prompts say "log in with the credentials
from extensions/.env"; scripts load them via `dotenv`. The `.env` approach
keeps credentials out of the artifact trail automatically.

---

## Session structure

Every full debug-capture session creates:

```
.workspace_state/debug/
└── [ISO-timestamp]_[context]/
    ├── session.json              ← master record (agent-readable)
    ├── screenshots/              ← NNN_context_state.png
    ├── api-calls/
    │   ├── network_log.json      ← Canvas API calls + full response bodies
    │   └── console_log.json      ← browser console output with timestamps
    ├── snapshots/
    │   └── visual_assertions.json ← DOM values from plugin iframe
    ├── performance/
    │   └── core_web_vitals.json  ← LCP, CLS, INP, TTFB
    ├── figma-reference/          ← only in figma-reference mode
    │   ├── reference_node.png
    │   └── diff_report.json
    └── agent-handoff/
        ├── brief.md              ← LLM-readable summary + suggested next tests
        └── test_deploy.sh        ← --rerun · --extend · --fix
```

**Figma file for this project:**
`https://www.figma.com/design/zhU3thHKxOblc5D9dL7hbl`
Screenshots from all sessions are uploaded here. Use as visual history.

---

## Installed tools

**`node_modules/` (Playwright):**
```
.workspace_state/debug/2026-06-09T14-00-00Z_full/node_modules/
```
Playwright v1.60.0. Symlinked to `debug/node_modules/` for resolution from any
session folder. No reinstall needed.

**Run the existing Playwright script:**
```bash
cd .workspace_state/debug
node capture_lori_collins.js
```

**debug-capture skill:**
```
~/.claude/skills/debug-capture/SKILL.md
~/.claude/skills/debug-capture/references/
    ├── session-schema.md     ← all JSON schemas
    ├── mode-playbooks.md     ← step-by-step for each mode
    ├── agent-handoff.md      ← brief.md + test_deploy.sh format
    └── figma-integration.md  ← upload + reference modes
```

**Launch script:**
```bash
bash ~/launch_workspace.sh          # full two-panel setup
bash ~/launch_workspace.sh --check  # verify only
bash ~/run_tests.sh                 # 27 automated checks
```

---

## What not to do

| Don't | Do instead |
|---|---|
| Run `full` mode to check if a button exists | Tier 2 one-liner |
| Start a debug session before `canvas list` | Always Tier 0 first |
| Store credentials in a script or session artifact | Use `.env` |
| Modify `~/.claude/skills/debug-capture/` for a new use case | Create a new tool in `debug/tools/` |
| Use `/api/r4/Observation` route interception for plugin data | Read `about:srcdoc` iframe DOM |
| Commit `.env` or `credentials.ini` | They are gitignored and machine-local |
| Build a new debugging tool inside an active debug session | Close the session, design the tool separately |
