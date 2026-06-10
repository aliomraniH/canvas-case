# Browser Verification Protocol
# cardiometabolic_tracker — Canvas Medical Plugin
# Run after EVERY /cpa:deploy via Chrome connector
# Instance: pxbuilder-aomrani.canvasmedical.com (credentials in extensions/.env)

---

## Overview

This document is the Chrome connector's standing order for post-deploy verification.
Trigger: companion hears "deployed" → runs this protocol automatically without prompting.

Chrome connector status at session start: ✅ VERIFIED LIVE
- URL: https://pxbuilder-aomrani.canvasmedical.com/schedule/day#location=UHJhY3RpY2VMb2NhdGlvbjo%3D
- Logged in as: the clinician account from extensions/.env (CANVAS_USERNAME)
- Clinicians on schedule: Richard Wilson MD, Amanda Miller DO, Christopher Taylor NP

---

## Pre-Check: Canvas CLI Confirmation (Desktop bash, run first)

```bash
# Confirm deploy actually succeeded before opening browser
canvas list --host pxbuilder-aomrani | grep -E "(cardiometabolic|growth)"
# Expected after rename: cardiometabolic_tracker   [version]   [status: active]
# Fail signal: still shows growth_charts, or shows error

canvas logs pxbuilder-aomrani 2>&1 | tail -20
# Expected: no Python tracebacks, no ImportError, no AttributeError
```

Only proceed to Chrome steps if CLI pre-check passes.

---

## STEP A — Find a Test Patient with Weight Observations

**Navigate:**
```
https://pxbuilder-aomrani.canvasmedical.com/schedule/day
```

Look for any scheduled appointment and click through to the patient chart.
If schedule is empty, navigate to:
```
https://pxbuilder-aomrani.canvasmedical.com/patients/
```
Search for any patient — pick one with existing vitals.

**Log:**
- Patient URL (format: `/patient/{id}/`)
- Patient name (for reference)
- Whether patient has existing weight observations visible in the vitals section

---

## STEP B — Plugin Button in Vitals Section

**What to look for:**
In the patient chart, find the **Vital Signs** or **CHART_SUMMARY_VITALS_SECTION** card.
This is typically in the right or center panel of the chart view.

**Pass criteria:**
```
✅ PASS_BUTTON      Button is visible, labeled appropriately (not "Growth Charts")
                   Acceptable labels: "Weight Tracker", "Cardiometabolic",
                   "Cardiometabolic Tracker", or whatever display_name is in CANVAS_MANIFEST.json
```

**Fail criteria:**
```
❌ FAIL_MISSING     No button appears anywhere in the vitals section
                   → Diagnosis: install may have failed, or manifest component path wrong
                   → Action: check `canvas list` + CANVAS_MANIFEST.json components.protocols

❌ FAIL_OLD_LABEL   Button exists but still labeled "Growth Charts"
                   → Diagnosis: CANVAS_MANIFEST.json name not updated, or old install cached
                   → Action: re-read manifest → confirm name = cardiometabolic_tracker → redeploy

❌ FAIL_ERROR_STATE Button exists but shows error badge/icon
                   → Diagnosis: Python protocol imported but handler raised on load
                   → Action: check canvas logs for ImportError or AttributeError at load time
```

---

## STEP C — Modal Opens and Renders

**Action:** Click the plugin button.

**Timing:** Give it up to 5 seconds for the modal to appear and render.

**Pass criteria:**
```
✅ PASS_MODAL_OPEN   Modal dialog appears with non-empty content.
                    Doesn't need to be perfect — just not blank/errored.
```

**Fail criteria:**
```
❌ FAIL_BLANK_MODAL  Modal opens but body is white/empty
                    → Likely cause: render_to_string returned empty, or JS fatal error
                    → Check browser console FIRST before canvas logs

❌ FAIL_SPINNER      Modal shows loading indicator that never resolves (>5 sec)
                    → Likely cause: Python compute() is blocking / infinite loop / timeout
                    → Check canvas logs for hanging process

❌ FAIL_CANVAS_ERROR Modal shows Canvas system error (red error panel)
                    → Paste full error text → check canvas logs for Python traceback

❌ FAIL_NO_MODAL     Nothing happens on click
                    → Likely cause: LaunchModalEffect not returned from compute()
                    → Check ActionButton handler returns [LaunchModalEffect(...)]
```

---

## STEP D — Chart Element Verification

With modal open, verify each visual element.

### Visual inspection (Chrome view):

| # | Element | How to identify | Pass | Fail |
|---|---------|----------------|------|------|
| D1 | SVG chart present | An SVG graphic visible in modal body | ✅ | ❌ no chart area |
| D2 | X-axis has dates | Axis labels like "Jan 2024", "Mar 2024" | ✅ | ❌ shows "months" or numbers |
| D3 | X-axis is NOT age | No labels like "0", "6", "12" (months) | ✅ | ❌ old pediatric axis |
| D4 | Y-axis in lbs | Axis label says "lbs" or "Weight (lbs)" | ✅ | ❌ no label or wrong unit |
| D5 | Patient data line | A line connecting data points visible | ✅ | ❌ no data plotted |
| D6 | Data dots | Individual circular markers on the line | ✅ | ❌ line only, no markers |
| D7 | Baseline dashed line | Horizontal dashed line (reference) | ✅ | ❌ no reference line |
| D8 | TBWL annotation | A text label near the latest point showing "%" | ✅ | ❌ no annotation |
| D9 | No WHO/CDC tabs | No tab buttons for WHO or CDC datasets | ✅ | ❌ tabs still present |
| D10 | No unit toggle | No lbs/kg toggle button | ✅ | ❌ toggle still present |

**Report:** `D: [n]/10 passed — [list of failures if any]`

---

## STEP E — Browser Console Diagnostic Commands

Open DevTools console (or use Chrome connector console access).
Run each command and record output:

### E1 — Component initialization check
```javascript
const initCheck = {
  Scaffold:    typeof ChartScaffold !== 'undefined' ? ChartScaffold._isInitialized : 'NOT_DEFINED',
  Baseline:    typeof BaselineLayer !== 'undefined' ? BaselineLayer._isInitialized : 'NOT_DEFINED',
  DataPoints:  typeof DataPointLayer !== 'undefined' ? DataPointLayer._isInitialized : 'NOT_DEFINED',
  Annotation:  typeof AnnotationLayer !== 'undefined' ? AnnotationLayer._isInitialized : 'NOT_DEFINED',
  Tooltip:     typeof TooltipManager !== 'undefined' ? 'defined' : 'NOT_DEFINED',
  Diagnostics: typeof DiagnosticsPanel !== 'undefined' ? 'defined' : 'NOT_DEFINED',
};
console.table(initCheck);
```
Expected: all values `true` or `defined`

### E2 — Data pipeline check
```javascript
const dataCheck = {
  baseline_value:   typeof BaselineLayer !== 'undefined' ? BaselineLayer._data?.value : 'N/A',
  baseline_loaded:  typeof BaselineLayer !== 'undefined' ? BaselineLayer._loadedAt : 'N/A',
  datapoints_count: typeof DataPointLayer !== 'undefined' ? DataPointLayer._data?.length : 'N/A',
  tbwl_latest:      typeof AnnotationLayer !== 'undefined' ? AnnotationLayer._data?.tbwl_pct : 'N/A',
};
console.table(dataCheck);
```
Expected: baseline_value is a number >0, datapoints_count ≥1, tbwl_latest is a number

### E3 — Pipeline timestamps (raw/processed separation trace)
```javascript
if (typeof DiagnosticsPanel !== 'undefined') {
  console.log('=== Pipeline Timestamps ===');
  Object.entries(DiagnosticsPanel.timestamps).forEach(([k, v]) => {
    console.log(`  ${k}: ${v}`);
  });
} else {
  console.error('DiagnosticsPanel not defined');
}
```
Expected: timestamps for python.* pipeline stages AND js.* component stages

### E4 — Refresh test
```javascript
// If this works without errors, component architecture is correct
if (typeof window.refreshAll === 'function') {
  window.refreshAll();
  console.log('refreshAll() completed without error');
} else {
  console.error('window.refreshAll is not defined');
}
```
Expected: "refreshAll() completed without error", no exceptions

### E5 — Individual component refresh (spot check)
```javascript
// Test each component's refresh independently
if (typeof window.refreshComponent === 'function') {
  ['BaselineLayer', 'DataPointLayer', 'AnnotationLayer'].forEach(name => {
    try {
      window.refreshComponent(name);
      console.log(`✅ ${name}.refresh() OK`);
    } catch(e) {
      console.error(`❌ ${name}.refresh() failed:`, e.message);
    }
  });
}
```

**Report for Step E:**
```
E: Console clean? [YES | NO — paste errors]
   Scaffold init:   [true | false | NOT_DEFINED]
   Baseline init:   [true | false | NOT_DEFINED]
   DataPoints init: [true | false | NOT_DEFINED]
   Annotation init: [true | false | NOT_DEFINED]
   Baseline value:  [number | null | N/A]
   Datapoints:      [count | null]
   TBWL latest:     [number | null]
   Python timestamps: [n found | 0 — tracing not wired]
   refreshAll():    [OK | ERROR]
```

---

## STEP F — Diagnostics Panel (Shift+D)

While modal is open:
1. Click inside the modal to focus it
2. Press **Shift+D**

**Pass criteria:**
```
✅ PASS_DIAG   Dark overlay panel appears in bottom-right corner of modal
               Shows entries like:
                 python.observations_loaded: 2026-06-05T...
                 python.processing_complete: 2026-06-05T...
                 ChartScaffold.init: 2026-06-05T...
                 BaselineLayer.render: 2026-06-05T...
                 [etc.]
```

**Fail criteria:**
```
❌ FAIL_NO_TOGGLE   Shift+D does nothing
                   → keydown listener not attached or DiagnosticsPanel.toggle() missing

❌ FAIL_PANEL_EMPTY Panel appears but no timestamps shown
                   → DiagnosticsPanel.recordTimestamp() not called from components

❌ FAIL_PYTHON_TS_MISSING  Panel shows JS timestamps but no python.* timestamps
                           → _pipeline_timestamps not passed from Python template context
```

Press Shift+D again to hide the panel before moving to Step G.

---

## STEP G — Edge Case: Patient with No Weight Data

Navigate to a **different patient** (try one with a new/empty chart).

If you cannot find a patient with no weight data:
```javascript
// Simulate the empty state from console — CPA may expose a test trigger
// This is a nice-to-have; skip G if no suitable patient is findable
```

Click the plugin button. Verify:

```
✅ PASS_EDGE    Modal shows a clear, friendly error message
                Examples: "No weight observations found for this patient"
                          "Chart unavailable — please record at least one weight"
               NOT: blank modal, Python traceback, or Canvas system error

❌ FAIL_CRASH   Canvas error / Python 500 error in modal
                → validate_chart_payload() may not be returning EffectErrorBanner correctly

❌ FAIL_SILENT  Modal opens blank with no message
                → Validation passed but template received empty datapoints

❌ FAIL_SPINNER Plugin hangs on empty patient
                → compute() not handling empty observation set defensively
```

---

## STEP H — Cross-Check: Browser vs. Canvas Logs

After completing Steps A–G, run in Desktop bash:
```bash
canvas logs pxbuilder-aomrani 2>&1 | tail -30
```

Match any browser errors to log entries:
| Browser sees | Canvas log shows | Likely cause |
|---|---|---|
| Blank modal | `AttributeError` on any line | Python bug in compute() |
| Blank modal | No log entry at all | Template rendered empty |
| Spinner | No log entry | compute() hanging |
| Canvas error 500 | Python `Exception` traceback | Unhandled exception |
| Modal renders fine | Any `WARNING` entries | Non-fatal — note for writeup |

---

## STEP H — Final Report Format

```
════════════════════════════════════════════════
DEPLOY_CHECK REPORT — [ISO timestamp]
Plugin: cardiometabolic_tracker
Instance: pxbuilder-aomrani.canvasmedical.com
────────────────────────────────────────────────
A. Patient:    [URL + name]
B. Button:     [✅ PASS_BUTTON | ❌ FAIL_* + details]
C. Modal:      [✅ PASS_MODAL_OPEN | ❌ FAIL_* + details]
D. Elements:   [n/10 ✅ — failed: D#, D#]
E. Console:    [✅ clean | ❌ n errors — pasted below]
F. Shift+D:    [✅ PASS_DIAG | ❌ FAIL_* + details]
G. Edge case:  [✅ PASS_EDGE | ❌ FAIL_* | ⚠️ SKIPPED — no empty patient found]
H. Log check:  [✅ no tracebacks | ⚠️ n warnings | ❌ ERROR — pasted below]
────────────────────────────────────────────────
OVERALL: [✅ ALL PASS | ⚠️ PARTIAL (n/8) | ❌ BLOCKED]
Blocking issues: [list if any]
Recommended next action: [specific fix or "ready for walkthrough"]
════════════════════════════════════════════════
```

---

## Quick Reference: Failure → Fix Mapping

| Failure code | Most likely cause | First thing to check |
|---|---|---|
| FAIL_BUTTON_MISSING | Plugin not installed or manifest path wrong | `canvas list --host pxbuilder-aomrani` |
| FAIL_OLD_LABEL | Manifest name not updated | `cat CANVAS_MANIFEST.json` → name field |
| FAIL_BLANK_MODAL | JS fatal error or empty template context | Browser console errors |
| FAIL_SPINNER | Python compute() not completing | `canvas logs` for hanging process |
| FAIL_CANVAS_ERROR | Python exception in compute() | `canvas logs` for full traceback |
| FAIL_NO_DIAG_TOGGLE | keydown not wired to DiagnosticsPanel | Read chart.html bottom of file |
| FAIL_PANEL_EMPTY | recordTimestamp() never called | Check each component's render() |
| FAIL_PYTHON_TS_MISSING | _pipeline_timestamps not in template context | Check assemble_template_context() |
| FAIL_CRASH (edge) | Empty obs list not handled defensively | Check compute() guard before build_chart_data() |
| D3 fail (age axis) | Old pediatric X-axis not replaced | Read chart.html d3 x-scale definition |
| D7 fail (no baseline line) | BaselineLayer.render() not called or data null | Console: BaselineLayer._data |
| D8 fail (no TBWL label) | AnnotationLayer data missing tbwl_pct | Console: AnnotationLayer._data |
