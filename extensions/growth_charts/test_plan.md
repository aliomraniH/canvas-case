# Cardiometabolic Tracker — Integrated Test Plan
# Companion execution guide for post-build verification
# Maps PDF test cases (TC-01–TC-10) → pytest tests → Chrome connector checks → bash greps
# Priority order: P0 first (must pass), then P1 (should pass), then P2 (time permitting)

---

## Execution Order After CPA Completes Implementation

```
1. BASH STATIC CHECKS    → run immediately after code is written (no deploy needed)
2. PYTEST SUITE          → run after static checks pass
3. CHROME BROWSER CHECKS → run after successful deploy only
```

---

## ── PRIORITY 0: Core MVP (Must Pass) ──────────────────────────────────────

### TC-01 | E2E Render
**Question:** Does the modal open and show a working SVG chart with calendar-date X-axis?
**When:** After deploy — Chrome connector
**How:**
```
Chrome: Navigate to patient chart → click plugin button
Assert: Modal opens (not blank, not spinner)
Assert: <svg> element present in modal DOM
Assert: X-axis labels match "MMM YYYY" format (e.g. "Jan 2024", "Mar 2024")
Assert: Y-axis labeled "lbs" or "Weight (lbs)"
Assert: Patient data points visible (line + dots)
```
**Pytest coverage (run first, before browser):**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_output_has_required_keys or test_datapoints_sorted_by_date_ascending" -v
```
**Pass gate:** Modal opens + SVG present + no "age in months" labels + "lbs" visible
**Fail → diagnose:** Check `canvas logs` for Python traceback; check browser console for JS errors

---

### TC-02 | Baseline Logic
**Question:** Is the dashed reference line at the patient's FIRST weight, not a population metric?
**When:** After deploy — Chrome connector + console
**How:**
```
Chrome console: BaselineLayer._data
Assert: value is a non-zero number (e.g. 230.5)
Assert: _component === "baseline_layer"
Assert: source_observation_id is a real observation ID (not null)
Visual: Horizontal dashed line visible on chart at baseline weight value
```
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_baseline_is_first_observation_not_last or test_earliest_date_is_baseline \
      or test_out_of_order_observations or test_single_observation_is_baseline" -v
```
**Pass gate:** `BaselineLayer._data.value` = patient's first recorded weight; dashed line visible
**Fail → diagnose:** Console `BaselineLayer._data` → null means validate_chart_payload blocked it or compute() never set it

---

### TC-03 | TBWL Calculation
**Question:** Is the % TBWL label mathematically correct and present on the chart?
**When:** After deploy — Chrome connector + console + pytest (math verification)
**How:**
```
Chrome console: AnnotationLayer._data
Assert: tbwl_pct is present (not null)
Assert: Math check — ((baseline - current) / baseline) × 100 matches displayed value
  baseline = BaselineLayer._data.value
  current  = DataPointLayer._data[DataPointLayer._data.length - 1].value_lbs
  expected = ((baseline - current) / baseline) * 100   ← compute this in console
Visual: A "% TBWL" text label visible at the rightmost data point
```
**Console verification script:**
```javascript
const b = BaselineLayer._data?.value;
const pts = DataPointLayer._data;
const latest = pts?.[pts.length - 1]?.value_lbs;
const expected = ((b - latest) / b * 100).toFixed(1);
const displayed = AnnotationLayer._data?.tbwl_pct?.toFixed(1);
console.log(`Expected: ${expected}%, Displayed: ${displayed}%, Match: ${expected === displayed}`);
```
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "UnitTest_TBWLCalculation or ClinicalTest_TBWLRanges \
      or test_tbwl_annotated_on_each_point or test_latest_tbwl_is_positive" -v
```
**Pass gate:** 9 TBWLCalculation tests pass + math check returns `Match: true` in console
**Fail → diagnose:** If `tbwl_pct` is null → `assemble_template_context` missing `latest_annotation`; if math wrong → `calculate_tbwl` formula error

---

### TC-04 | Scope Containment
**Question:** Are all pediatric/WHO/CDC artifacts completely absent?
**When:** After code written — bash static checks + Chrome visual
**How (bash — run immediately after CPA writes code):**
```bash
export PLUGIN_ROOT=/Users/aliomrani/Documents/Canvas-case/canvas/extensions/growth_charts

# No graphs/ imports
echo "=== graphs/ imports (must be 0) ==="
grep -rn "from graphs" $PLUGIN_ROOT/protocols/ | wc -l

# No WHO/CDC references in template
echo "=== WHO/CDC in HTML (must be 0) ==="
grep -in "WHO\|CDC\|percentile\|age_in_months" $PLUGIN_ROOT/templates/chart.html | wc -l

# No sex stratification gating
echo "=== Sex gating (must be 0) ==="
grep -n "sex == 'M'\|sex == 'F'\|sex_at_birth ==" $PLUGIN_ROOT/protocols/growth_charts.py | wc -l

# No head/length/bmi queries
echo "=== Pediatric metrics (must be 0) ==="
grep -in "head_circumference\|length\|bmi" $PLUGIN_ROOT/protocols/growth_charts.py | wc -l

# No unit toggle in HTML
echo "=== Unit toggle (must be 0) ==="
grep -in "toggle\|kg.*lbs\|lbs.*kg" $PLUGIN_ROOT/templates/chart.html | wc -l

# graphs/ directory should be gone or empty
echo "=== graphs/ directory ==="
ls $PLUGIN_ROOT/graphs/ 2>/dev/null && echo "FAIL — graphs/ still exists" || echo "PASS — graphs/ deleted"
```
**Chrome visual:** Inspect modal — no tabs, no "WHO", no "CDC", no "age" labels
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_no_graphs_directory_referenced or test_missing_sex_does_not_block_chart \
      or test_handler_does_not_return_empty_on_missing_sex" -v
```
**Pass gate:** All grep checks = 0; no WHO/CDC/tabs visible in browser

---

## ── PRIORITY 1: Architectural Integrity (Should Pass) ─────────────────────

### TC-05 | Data Immutability
**Question:** Is raw SDK data kept separate from processed data — never overwritten?
**When:** After code written — code review + pytest
**How (code review — grep checks):**
```bash
export PLUGIN_ROOT=/Users/aliomrani/Documents/Canvas-case/canvas/extensions/growth_charts

# Confirm 'raw' nested dict exists in processed observations
echo "=== raw nested dict present ==="
grep -n '"raw"' $PLUGIN_ROOT/protocols/growth_charts.py

# Confirm value_original is preserved
echo "=== value_original preserved ==="
grep -n "value_original" $PLUGIN_ROOT/protocols/growth_charts.py

# Confirm processing_version present (shows intentional versioning)
echo "=== processing_version ==="
grep -n "processing_version" $PLUGIN_ROOT/protocols/growth_charts.py

# Confirm processed_at timestamp present
echo "=== processed_at ==="
grep -n "processed_at" $PLUGIN_ROOT/protocols/growth_charts.py
```
**Expected:** Each grep returns ≥1 match showing raw/processed separation
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_raw_data_preserved_separately or test_timestamps_in_pipeline_metadata" -v
```
**Pass gate:** `test_raw_data_preserved_separately` PASSES; grep shows both `value_original` and `value_lbs` in separate dicts
**Fail → diagnose:** Read `build_observation_processed()` — if raw fields are missing from the `raw` sub-dict, CPA collapsed them

---

### TC-06 | Component Isolation
**Question:** Does `window.refreshAll()` re-render cleanly with independent component logs?
**When:** After deploy — Chrome connector console
**How:**
```javascript
// Run in browser console while modal is open:

// Step 1 — verify all components initialized
console.log('--- Component Init State ---');
console.log('Scaffold:', ChartScaffold._isInitialized);
console.log('Baseline:', BaselineLayer._isInitialized);
console.log('DataPoints:', DataPointLayer._isInitialized);
console.log('Annotation:', AnnotationLayer._isInitialized);

// Step 2 — run refreshAll and watch console for independent logs
console.log('--- Triggering refreshAll() ---');
window.refreshAll();
// Expected console output:
//   [ChartScaffold] refresh() triggered
//   [BaselineLayer] refresh() triggered
//   [DataPointLayer] refresh() triggered
//   [AnnotationLayer] refresh() triggered

// Step 3 — verify no duplicate DOM elements after refresh
const svgs = document.querySelectorAll('svg');
console.log('SVG count after refresh (should be 1):', svgs.length);
```
**Pass gate:** All `_isInitialized = true`; console shows 4 component refresh logs; SVG count = 1 (no duplicates)
**Fail → diagnose:**
- `NOT_DEFINED` → component JS object missing from chart.html
- SVG count > 1 → `refresh()` calls `init()` instead of just re-rendering (scaffold re-created)
- No logs → `refresh()` not implemented or `_data` is null (guard not triggered)

---

### TC-07 | Legacy Debt Removal
**Question:** Are both bugs (N+1 query + mutable default) provably gone from the code?
**When:** After code written — bash grep + pytest
**How (bash — definitive):**
```bash
export PLUGIN_ROOT=/Users/aliomrani/Documents/Canvas-case/canvas/extensions/growth_charts

echo "=== TC-07A: N+1 Bug Check (must be 0) ==="
grep -n "Note.objects.get" $PLUGIN_ROOT/protocols/growth_charts.py | wc -l
grep -n "Note.objects.get" $PLUGIN_ROOT/protocols/growth_charts.py

echo ""
echo "=== TC-07B: Mutable Default Bug Check (must be 0) ==="
grep -n "date=datetime.now()" $PLUGIN_ROOT/protocols/growth_charts.py | wc -l
grep -n "date=datetime.now()" $PLUGIN_ROOT/protocols/growth_charts.py

echo ""
echo "=== TC-07C: Batch query exists (must be ≥1) ==="
grep -n "filter(id__in" $PLUGIN_ROOT/protocols/growth_charts.py

echo ""
echo "=== TC-07D: None default exists (must be ≥1 if date param survives) ==="
grep -n "date=None" $PLUGIN_ROOT/protocols/growth_charts.py
```
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "IntegrationTest_N1QueryFix or EdgeCaseTest_MutableDefaultBug" -v
```
**Pass gate:**
- `Note.objects.get` grep → 0 matches
- `date=datetime.now()` grep → 0 matches
- `filter(id__in` grep → ≥1 match
- `test_batch_fetch_not_get_in_loop` → PASS
- `test_date_default_not_evaluated_at_import` → PASS

---

## ── PRIORITY 2: Edge Cases & Telemetry (If Time Allows) ───────────────────

### TC-08 | Zero-Data Fallback
**Question:** Does validate_chart_payload() gracefully block the modal for patients with no weight data?
**When:** After deploy — Chrome connector
**How:**
```
Chrome: Navigate to a patient with NO weight observations
Click plugin button
Assert: EffectErrorBanner shown (NOT blank modal, NOT Python 500, NOT spinner)
Assert: Error text contains "weight" or "observation" or "no data"
```
**Pytest coverage:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_empty_datapoints_fails or test_missing_baseline_fails \
      or test_single_observation_renders_without_error" -v
```
**Pass gate:** `test_empty_datapoints_fails` PASSES + browser shows graceful error message

---

### TC-09 | Diagnostic Telemetry
**Question:** Does Shift+D show sequentially-ordered timestamps from all pipeline stages?
**When:** After deploy — Chrome connector
**How:**
```
Chrome: Modal open → press Shift+D
Assert: Dark overlay panel appears (bottom-right corner)
Assert: Panel shows python.* timestamps (from Python pipeline)
Assert: Panel shows JS component timestamps (init/render calls)
Assert: Timestamps are chronologically sequential

Console verification:
  Object.entries(DiagnosticsPanel.timestamps)
    .sort((a,b) => a[1].localeCompare(b[1]))
    .forEach(([k,v]) => console.log(k, v));
```
**Pass gate:** ≥6 timestamps visible (python.* stages + JS component stages); Shift+D toggles panel on/off

---

### TC-10 | Clinical Plausibility Guard
**Question:** Does validate_chart_payload() block a TBWL of 60% (outside [-20, 50] range)?
**When:** After code written — pytest only (no deploy needed)
**How:**
```bash
cd $PLUGIN_ROOT && /Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py \
  -k "test_implausible_tbwl_flagged or test_zero_weight_observation_fails \
      or test_future_date_observation_flagged or test_unsorted_dates_flagged \
      or test_missing_pipeline_timestamps_flagged" -v
```
**Pass gate:** All EdgeCaseTest_PreRenderValidation tests PASS (8 tests)

---

## Master Test Run Commands

### After CPA writes code (pre-deploy):
```bash
export PLUGIN_ROOT=/Users/aliomrani/Documents/Canvas-case/canvas/extensions/growth_charts
cd $PLUGIN_ROOT

# 1. Static checks (TC-04, TC-07)
echo "=== Static Code Checks ===" && \
  echo "N+1 bugs: $(grep -n 'Note.objects.get' protocols/growth_charts.py | wc -l) (must=0)" && \
  echo "Mutable defaults: $(grep -n 'date=datetime.now()' protocols/growth_charts.py | wc -l) (must=0)" && \
  echo "graphs/ imports: $(grep -rn 'from graphs' protocols/ | wc -l) (must=0)" && \
  echo "Sex gating: $(grep -n "sex == 'M'\|sex == 'F'" protocols/growth_charts.py | wc -l) (must=0)"

# 2. Full pytest suite
/Users/aliomrani/.local/share/uv/tools/canvas/bin/python \
  -m pytest tests/test_cardiometabolic.py -v --tb=short 2>&1 | tee /tmp/test_output.txt

# Summary
grep -E "(PASSED|FAILED|SKIPPED|ERROR)" /tmp/test_output.txt | tail -5
```

### After deploy (post-deploy browser check = §13):
Run §13 protocol (Chrome connector auto-triggered by "deployed" keyword).

---

## Test Coverage Matrix

| TC ID | Priority | Pytest Tests | Bash Grep | Chrome |
|-------|----------|-------------|-----------|--------|
| TC-01 | P0 | test_output_has_required_keys, test_datapoints_sorted | — | SVG + dates + lbs |
| TC-02 | P0 | test_baseline_is_first_observation_not_last, test_earliest_date | — | BaselineLayer._data + dashed line |
| TC-03 | P0 | UnitTest_TBWLCalculation (9 tests), ClinicalTest_TBWLRanges (4) | — | Annotation math check |
| TC-04 | P0 | test_no_graphs_directory_referenced, sex field tests | graphs/WHO/sex/toggle grep | No tabs/metrics |
| TC-05 | P1 | test_raw_data_preserved_separately, test_timestamps | value_original grep | — |
| TC-06 | P1 | — | — | window.refreshAll() + SVG count |
| TC-07 | P1 | IntegrationTest_N1QueryFix (2), MutableDefaultBug (1) | Note.objects.get=0, date=datetime.now()=0 | — |
| TC-08 | P2 | test_empty_datapoints_fails, test_missing_baseline | — | Empty patient graceful error |
| TC-09 | P2 | — | — | Shift+D overlay + timestamps |
| TC-10 | P2 | EdgeCaseTest_PreRenderValidation (8 tests) | — | — |

**Total pytest tests covering P0+P1: 20 tests**
**Total pytest tests covering P2: 8+ tests**
**Total unique greps for P0+P1: 6 bash checks**
**Total browser steps: §13 protocol (Steps A–H)**
