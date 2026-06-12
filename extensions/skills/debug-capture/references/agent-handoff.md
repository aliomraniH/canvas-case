# Agent Handoff Reference

Every debug session produces two files in `agent-handoff/`:
1. `brief.md` — structured brief readable by any LLM agent
2. `test_deploy.sh` — runnable script that can rerun or extend tests

---

## brief.md format

Write this file at the end of every session. It is the primary
artifact for future agents — write it as if you are handing off
to a fresh Claude Code session that has never seen this project.

```markdown
# Debug Session Handoff Brief
**Session:** {session_id}
**Date:** {created_at}
**Mode:** {mode}
**Project:** {project} v{plugin_version}
**Status:** PASS {passed} / FAIL {failed} / WARN {warnings}

---

## What was tested
{1-2 sentence description of what the test covered}

## What was found
{For each failure or warning:}
### Issue: {short title}
- **Severity:** major | minor | warning
- **Element:** {what element or component}
- **Expected:** {what should happen}
- **Actual:** {what actually happened}
- **Evidence:** {path to screenshot or log entry}
- **Root cause:** {if known — check network_log.json and console_log.json}
- **Suggested fix:** {specific code or config change}

## API calls during test
{Summary from network_log.json — N FHIR calls, any errors, slowest request}

## Console errors
{Summary from console_log.json — N errors, key messages}

## Figma comparison
{If figma-reference mode: match_score_pct, key differences listed}
{If not run: "Not compared. Reference: {figma_url if known}"}

---

## Suggested next test scenarios
{For each failure, suggest a new test that would verify the fix:}
1. **{test name}** — {what to test, what assertion to make}
2. ...

## How to rerun
\`\`\`bash
bash .workspace_state/debug/{session_id}/agent-handoff/test_deploy.sh
\`\`\`

## How to extend
Pass this brief to a Claude Code session with:
> "Read agent-handoff/brief.md and generate additional test cases
> targeting the failures listed. Output as test_deploy_v2.sh."
```

---

## test_deploy.sh format

```bash
#!/bin/bash
# =============================================================
# Auto-generated test deploy script
# Session: {session_id}
# Generated: {created_at}
# Mode: {mode}
# =============================================================
# Usage:
#   bash test_deploy.sh           — rerun exact same tests
#   bash test_deploy.sh --extend  — generate new tests from failures
#   bash test_deploy.sh --fix     — apply suggested fixes and rerun
# =============================================================

set -euo pipefail

SESSION_ID="{session_id}"
WORKSPACE="<repo>/extensions"
PLUGIN_DIR="$WORKSPACE/growth_charts"
CANVAS_HOST="<instance>"
BRIEF="$WORKSPACE/.workspace_state/debug/$SESSION_ID/agent-handoff/brief.md"

export PATH="$PATH:$HOME/.local/bin"

echo "================================================="
echo " Rerunning debug session: $SESSION_ID"
echo "================================================="

# --- Verify environment ---
canvas list --host $CANVAS_HOST > /dev/null \
  && echo "✓ Canvas connected" \
  || { echo "✗ Canvas not reachable"; exit 1; }

# --- Run tests ---
# {For each test that was run in the original session, include the
#  equivalent bash or claude command here}
# Example:
#   canvas list --host $CANVAS_HOST | grep cardiometabolic_tracker
#   python3 -m pytest $PLUGIN_DIR/tests/ -x -q

# --- Generate new test scenarios (--extend mode) ---
if [[ "${1:-}" == "--extend" ]]; then
  echo ""
  echo "Generating extended test scenarios from brief..."
  echo "Paste this into Claude Code Desktop:"
  echo ""
  cat "$BRIEF"
  echo ""
  echo "Prompt: Read the brief above and generate"
  echo "  5 additional test cases targeting the failures listed."
  echo "  Output as: test_deploy_v2.sh"
fi

echo ""
echo "✓ Test run complete — check:"
echo "  $WORKSPACE/.workspace_state/debug/$SESSION_ID/session.json"
```

---

## Agent consumption pattern

When a future autonomous agent reads a session, it should:

1. Load `session.json` — get overall status, mode, context
2. If `results.failed > 0`: load `agent-handoff/brief.md`
3. Load relevant detail files based on failures:
   - Console errors → `api-calls/console_log.json`
   - API failures → `api-calls/network_log.json`
   - Visual regressions → `figma-reference/diff_report.json`
4. Generate new test cases from `agent_handoff.suggested_actions`
5. Write new test script as `agent-handoff/test_deploy_v{N+1}.sh`
6. Update `session.json`:
   ```json
   "agent_handoff": {
     "ready_for_agent": true,
     "suggested_actions": [
       "Verify obs.units field name in SDK v0.163.1",
       "Add regression test for baseline line stroke-dasharray"
     ]
   }
   ```

## Listing all sessions for an agent

```python
import os, json, glob

debug_base = '.workspace_state/debug'
sessions = []
for session_json in sorted(glob.glob(f'{debug_base}/*/session.json')):
    with open(session_json) as f:
        s = json.load(f)
    sessions.append({
        'session_id': s['session_id'],
        'created_at': s['metadata']['created_at'],
        'mode': s['mode'],
        'status': f"{s['results']['passed']}P/{s['results']['failed']}F",
        'path': os.path.dirname(session_json)
    })

# Most recent first
sessions.sort(key=lambda x: x['created_at'], reverse=True)
for s in sessions:
    print(f"{s['created_at']}  {s['session_id']}  {s['status']}")
```
