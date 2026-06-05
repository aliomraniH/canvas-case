# Plugin Spec — `cardiometabolic_tracker`

**Status:** SPEC ONLY — no implementation code is written until this is approved.
**Source plugin:** `growth_charts/` (adapted in place — NOT scaffolded fresh).
**Clinical reframe:** pediatric population-percentile growth charts → adult GLP-1
weight-trajectory tracker plotting each patient against their **own baseline**
(first weight observation) on a **calendar-date** X-axis.

> **Two open decisions** (see §D.5 and §F-adjacent notes) are flagged inline as
> `DECISION REQUIRED`. The spec documents the **recommended** option; both are
> implementable. Confirm or override before code is written.

---

## A. Files to Modify

| File | Change | Why |
|---|---|---|
| `CANVAS_MANIFEST.json` | `name` → `cardiometabolic_tracker`; update `description`; keep one protocol whose `class` points at the refactored handler; `data_access.read` → `["Patient","Observation","Note"]` | Rename + accurate metadata; old name/description are pediatric |
| `protocols/growth_charts.py` | **Full rewrite** into the five-section architecture (§D). Removes all `graphs/` imports, sex gating, age-in-months math, and multi-metric queries. Adds Data-Loading / Processing / Validation / Render layers + thin handler | This is the core adaptation; old file is monolithic pediatric logic |
| `templates/chart.html` | **Full rewrite** into the six named JS components (§E) with `init/render/refresh/destroy`, DiagnosticsPanel, Shift+D, `window.refresh*`. Removes WHO/CDC tabs, unit toggle, percentile curves | New visualization model: baseline line + patient trajectory, no population curves |
| `tests/test_cardiometabolic.py` | One targeted fix to `test_handler_class_path_is_valid` (§G). No other test changes | Test has a real bug (treats protocol entries as strings, not dicts) |
| `README.md` | Rewrite to describe the adult GLP-1 tracker, install steps, and the MVP/Phase-2 scope | Currently describes pediatric growth charts |
| `browser_test_protocol.md` | Update manual-test steps to the new modal (baseline line, TBWL annotation, Shift+D) | Currently references WHO/CDC tabs |

Filename note: the Python module **stays** `protocols/growth_charts.py` (the test
imports `from protocols.growth_charts import ...`). Only the *class behavior* and
the *manifest name* change — we do **not** rename the file, to keep the import
contract the tests depend on.

---

## B. Files to Delete

Delete the entire `graphs/` package — every percentile-curve module:

```
graphs/__init__.py
graphs/who_boys_weight_age.py          graphs/who_girls_weight_age.py
graphs/who_boys_length_age.py          graphs/who_girls_length_age.py
graphs/who_boys_weight_length.py       graphs/who_girls_weight_length.py
graphs/who_boys_circumference_age.py   graphs/who_girls_circumference_age.py
graphs/cdc_boys_weight_age.py          graphs/cdc_girls_weight_age.py
graphs/cdc_boys_weight_age_24_240.py   graphs/cdc_girls_weight_age_24_240.py
graphs/cdc_boys_length_age.py          graphs/cdc_girls_length_age.py
graphs/cdc_boys_weight_length.py       graphs/cdc_girls_weight_length.py
graphs/cdc_boys_head_age.py            graphs/cdc_girls_head_age.py
graphs/cdc_boys_weight_stature.py      graphs/cdc_girls_weight_stature.py
graphs/cdc_boys_stature_age.py         graphs/cdc_girls_stature_age.py
graphs/cdc_boys_bmi_age.py             graphs/cdc_girls_bmi_age.py
```

(25 files incl. `__init__.py`.) **Confirmation: zero imports from `graphs/` will
remain.** The new `protocols/growth_charts.py` has no `from growth_charts.graphs...`
lines, and the manifest contains no `graphs/` reference (verified by
`test_no_graphs_directory_referenced`).

---

## C. `CANVAS_MANIFEST.json` Changes

```jsonc
{
  "name": "cardiometabolic_tracker",          // was: "growth_charts"
  "description": "Adult GLP-1 weight-management tracker: plots each patient's weight against their own baseline with % total body weight loss (TBWL) over calendar time.",
  "components": {
    "protocols": [
      {
        "class": "growth_charts.protocols.growth_charts:GenerateVitalsGraphs",
        "description": "Renders an adult cardiometabolic weight trajectory chart from the patient's weight observations.",
        "data_access": {
          "event": "",
          "read": ["Patient", "Observation", "Note"],
          "write": []
        }
      }
    ],
    "commands": [], "content": [], "effects": [], "views": []
  }
}
```

- **`name`** field: `cardiometabolic_tracker` (was `growth_charts`).
- **Handler class path:** `growth_charts.protocols.growth_charts:GenerateVitalsGraphs`
  — the package directory is still `growth_charts/` and the module is still
  `protocols/growth_charts.py`, so the dotted path is unchanged; only the manifest
  `name` and the class internals change. The class name `GenerateVitalsGraphs` is
  retained because the test imports it by that name.

---

## D. `protocols/growth_charts.py` — Full Specification

Organized into the five comment-delimited sections from
`component_architecture.md`. Imports: `datetime`, `Patient`, `Observation`,
`Note` (from `canvas_sdk.v1.data`), `ActionButton`, `LaunchModalEffect`,
`render_to_string`. **No `arrow`, no `graphs/` imports.**

### Section 1 — Data Loading Layer

| Function | Inputs | Output | Canvas SDK calls |
|---|---|---|---|
| `load_patient_demographics(patient_id)` | `patient_id: str` | `dict` with `patient_id`, `sex_at_birth` (kept, **never gates**), `birth_date`, `_loaded_at`, `_component:"patient_demographics"` | `Patient.objects.get(id=patient_id)` wrapped in `try/except Patient.DoesNotExist` |
| `load_weight_observations_raw(patient_id)` | `patient_id: str` | `list[dict]`, each: `id`, `value_original`, `unit_original`, `canvas_note_id`, `_loaded_at` (raw only — **no notes fetched here**) | `Observation.objects.for_patient(patient_id).filter(name="weight")` |
| `batch_load_notes(note_ids)` | `note_ids: list[str]` | `dict[str, Note]` keyed by note id, for O(1) lookup | **`Note.objects.filter(id__in=note_ids)`** — exactly one query (**N+1 fix**) |
| `attach_dates_to_observations(obs_raw, notes_by_id)` | `list[dict]`, `dict[str,Note]` | `list[dict]` — each obs gains `datetime_of_service` from its note | **none** (pure dict join; observations whose note is missing are skipped with a logged warning) |

Notes:
- Weight obs are filtered to `name="weight"` only. `height/length/bmi/head_circumference`
  queries are **removed**.
- `load_weight_observations_raw` reads `obs.value`, `obs.unit`, and the note id.
  Per the test mocks, the note id is reachable as `obs.note.id`; the loader records
  it as `canvas_note_id`. (Old code used `obs.note_id`/`dbid` — updated.)

### Section 2 — Processing Layer (pure functions, no SDK calls)

| Function | Inputs | Output | Behavior |
|---|---|---|---|
| `convert_weight_to_lbs(value, unit)` | `float`, `str` | `float` | `lbs`→×1, `kg`→×2.20462, `oz`→÷16, `g`→×0.00220462. **Case-insensitive** (`unit.strip().lower()`). Unknown unit → `raise ValueError` |
| `compute_baseline(observations)` | `list` (raw obs dicts *or* SDK obs objects) | `float` (baseline weight in lbs) | Sorts ascending by `datetime_of_service`; returns earliest, converted to lbs. Tie on earliest date → higher value (conservative). Empty → `raise ValueError` |
| `calculate_tbwl(baseline_lbs, current_lbs)` | `float`, `float` | `float` | `((baseline - current)/baseline)*100`. `baseline <= 0` → `raise ValueError`. Always returns `float` |
| `calculate_weeks_since_baseline(baseline_date, current_date)` | `datetime`, `datetime` | `float` | `(current - baseline).total_seconds()/ (7*86400)`. Negative if current < baseline (no clamp) |
| `format_date_mmmyyyy(dt)` | `datetime` | `str` | `dt.strftime("%b %Y")` → `"Jan 2024"` (3-letter month) |
| `build_observation_processed(obs_raw, baseline_lbs)` | `dict`, `float` | `dict` | Produces processed fields **plus** nested `raw` (see §H). Raw values never overwritten |
| `build_chart_data(observations_raw, notes_by_id)` | `list`, `dict` | `dict` (full payload, see §D.4) | Orchestrates: `attach_dates` → `compute_baseline` → per-obs `build_observation_processed` → sort ascending → assemble payload with `baseline_data`, `datapoints`, `latest_tbwl_pct`, `_pipeline_timestamps` |

`compute_baseline` and `build_chart_data` must accept the **test's mock observation
objects** (`.value`, `.unit`, `.note.datetime_of_service`) as well as raw dicts —
a small normalizer at the top of each handles both shapes. This is required because
the unit/integration tests call them with `make_observation(...)` Mocks directly,
while the handler calls them with raw dicts. `build_chart_data(observations, baseline)`
in tests is called positionally with a numeric `baseline` second arg in some tests
and `notes_by_id` in others — the implementation treats a numeric/None second arg as
"no pre-fetched notes; read dates off the objects," and a dict as a notes map.

> `DECISION REQUIRED — build_chart_data signature overload.` The architecture doc
> declares `build_chart_data(observations_raw, notes_by_id)`, but the test calls
> `build_chart_data(obs, 250.0)` and `build_chart_data(obs, baseline)`. Recommended:
> accept a second positional param `notes_or_baseline` and branch on its type
> (`dict` → notes map; `float`/`int`/`None` → derive dates from the obs objects and
> ignore as baseline since baseline is recomputed internally). This satisfies both
> the doc's handler call path and the test call path. Awaiting confirmation.

### Section 3 — Validation Layer

`validate_chart_payload(payload) -> tuple[bool, list[str]]` — runs the **8 checks**
in order; returns `(True, [])` if all pass, else `(False, [messages...])`:

1. `baseline_data` key exists **and** `baseline_data["value"] > 0` — else `"Missing or non-positive baseline"`.
2. `datapoints` is a non-empty list — else `"No datapoints to render"`.
3. No future dates: every `dp["date_obj"] <= datetime.now()` — else `"Observation date in the future"`.
4. `latest_tbwl_pct` within `[-20, 50]` — else `"latest TBWL out of plausible range"`.
5. No zero/negative weights: every `dp["value_lbs"] > 0` — else `"Zero or negative weight value"`.
6. `datapoints` sorted ascending by `date_obj` (i.e. `dates == sorted(dates)`) — else `"Datapoints not sorted by date"`.
7. `_pipeline_timestamps` key present — else `"Missing pipeline timestamps"`.
8. All required template keys present (`baseline_data`, `datapoints`, `latest_tbwl_pct`, `_pipeline_timestamps`) — else `"Missing required template key: <k>"`.

Each message contains a keyword the tests grep for (`baseline`, `future`/`date`,
`tbwl`/`range`, `sort`/`order`/`date`).

### Section 4 — Render Layer

`assemble_template_context(patient, baseline, datapoints, pipeline_timestamps) -> dict`
builds the final dict for `render_to_string`. Every top-level component dict carries
**`_component`** (its JS component name) and **`_loaded_at`** (`datetime.now().isoformat()`):

```python
{
  "patient":          {..., "_component": "patient_info",     "_loaded_at": ...},
  "baseline_data":    {"value": float, "unit": "lbs", "source_observation_id": str,
                       "_component": "baseline_layer",  "_loaded_at": ...},
  "datapoints":       [ <processed obs dicts, each with nested raw> ],
  "latest_annotation":{"tbwl_pct": float, "weight_lbs": float, "date_label": str,
                       "_component": "annotation_layer", "_loaded_at": ...},
  "latest_tbwl_pct":  float,
  "chart_config":     {"x_axis_type": "calendar_date", "y_axis_unit": "lbs",
                       "show_benchmark_overlay": False, "benchmark_source": None},
  "_pipeline_timestamps": {
      "demographics_loaded": str, "observations_raw_loaded": str,
      "notes_batch_loaded": str,  "processing_complete": str,
      "validation_passed": str,   "template_context_assembled": str,
  },
}
```

`_pipeline_timestamps` keys (6): `demographics_loaded`, `observations_raw_loaded`,
`notes_batch_loaded`, `processing_complete`, `validation_passed`,
`template_context_assembled`. (`build_chart_data`'s payload additionally exposes
`observations_loaded`, `notes_batch_loaded`, `processing_complete` to satisfy the
integration test's required-timestamp check.) Each component value also carries its
own `_component` + `_loaded_at`, so the DiagnosticsPanel can show per-layer load times.

### Section 5 — ActionButton Handler

```python
class GenerateVitalsGraphs(ActionButton):
    BUTTON_TITLE = "Weight Trajectory"
    BUTTON_KEY = "show_cardiometabolic_tracker"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION
```

`compute()` call sequence — **Load → Process → Validate → Assemble → Render**:

1. **Load:** `patient = load_patient_demographics(<patient id>)`;
   `obs_raw = load_weight_observations_raw(<patient id>)`;
   `notes = batch_load_notes([o["canvas_note_id"] for o in obs_raw])`.
2. **Process:** `payload = build_chart_data(obs_raw, notes)`.
3. **Validate:** `is_valid, errors = validate_chart_payload(payload)`.
   On failure → **return a non-empty error effect, NOT `[]`** (see decision below) —
   the chart modal is **not** rendered.
4. **Assemble:** `context = assemble_template_context(patient, payload["baseline_data"], payload["datapoints"], payload["_pipeline_timestamps"])`.
5. **Render:** `html = render_to_string("templates/chart.html", context)`;
   return `[LaunchModalEffect(content=html).apply()]`.

**No sex gating anywhere** — `sex_at_birth` is loaded but never branched on; there is
no `return []` for a missing/other sex. **No age-in-months.** **No `graphs/` imports.**

> `DECISION REQUIRED — compute() vs handle() (recommend Option B).` SDK
> `ActionButton.compute()` is the dispatcher that emits the `ShowButtonEffect` on
> `SHOW_*_BUTTON` events and calls `handle()` on click. The architecture doc + test
> call `compute()` directly. **Recommended Option B:** keep the pipeline in
> `handle()`; override `compute()` to (a) `return super().compute()` when
> `self.event.name` matches `SHOW_*_BUTTON` (button still renders/click still routes),
> and (b) otherwise `return self.handle()`. Guard the regex match with
> `try/except (AttributeError, TypeError)` so the test's `GenerateVitalsGraphs(Mock(),
> Mock()).compute()` falls through to `handle()` (which then either returns a
> `LaunchModalEffect` list or raises `AttributeError` on the Mock — both accepted by
> `test_handler_does_not_return_empty_on_missing_sex`). Option A (override `compute()`
> outright) is rejected: it breaks button rendering in real Canvas.

> `DECISION REQUIRED — validation-failure effect (recommend Option B).`
> `EffectErrorBanner` does not exist in the SDK. **Recommended Option B:** render the
> joined `errors` into a small error template and return `[LaunchModalEffect(content=
> error_html).apply()]` — non-empty, stops the chart, shows the user why. Option A:
> `AddBannerAlert(...)` — real SDK class but a persistent chart banner with a 90-char
> cap and required `patient_id`/`placement`/`intent`, awkward for a transient render
> error. No test asserts the type; both satisfy "not `[]`."

---

## E. `templates/chart.html` — Full Specification

Single d3-backed template. Data injected as
`const chartData = JSON.parse('{{ chart_data_json|escapejs }}')`. Six JS component
objects, each a singleton with the standard contract; **`DiagnosticsPanel` is defined
first** so other components can call `DiagnosticsPanel.recordTimestamp()` during their
`render()`.

| Component | `init(config)` | `render(data)` | `refresh()` | `destroy()` |
|---|---|---|---|---|
| **ChartScaffold** | Build SVG canvas, calendar-date (time) X-scale, weight (lbs) Y-scale, axes. Runs **first**. Records ts | Re-draw axes for current data extent | Re-run `render(this._data)` | Remove SVG, reset state |
| **BaselineLayer** | Mark initialized, record ts | Draw horizontal **dashed line** at `baseline_data.value_lbs`; guard if not initialized | Re-render same data | Remove line, clear `_data` |
| **DataPointLayer** | Mark initialized, record ts | Draw patient weight **line + dots** over calendar dates from `datapoints[]` | Re-render | Remove series, clear |
| **AnnotationLayer** | Mark initialized, record ts | Draw **% TBWL label** at the latest datapoint from `latest_annotation` | Re-render | Remove label |
| **TooltipManager** | Bind hover/pointer events over datapoints; record ts. **No `render()`** (event-driven) | — | Re-bind handlers | Unbind events |
| **DiagnosticsPanel** | (defined first) `timestamps:{}`, `recordTimestamp(component, ts)`, `render()` builds hidden overlay table, `toggle()` shows/hides | `render()` rebuilds overlay | `render()` | hide/clear |

Every component's `render()` (and `init()` where there's no render) sets
`this._loadedAt = new Date().toISOString()` and calls
`DiagnosticsPanel.recordTimestamp('<Name>.render', this._loadedAt)`; `render()` guards
against being called before `init()`.

**DOMContentLoaded initialization sequence (order matters):**

1. Parse `chartData`.
2. `ChartScaffold.init(chartData.chart_config)`
3. `BaselineLayer.render(chartData.baseline_data)`
4. `DataPointLayer.render(chartData.datapoints)`
5. `AnnotationLayer.render(chartData.latest_annotation)`
6. `TooltipManager.init(chartData.datapoints)`
7. For each `[k,v]` in `chartData._pipeline_timestamps`: `DiagnosticsPanel.recordTimestamp('python.'+k, v)`; then `recordTimestamp('js.domContentLoaded', now)`.
8. Wire keydown: **`Shift+D` → `DiagnosticsPanel.toggle()`**.

**Exposed globals (browser-console debugging):**
- `window.refreshComponent(name)` — looks up `{ChartScaffold, BaselineLayer, DataPointLayer, AnnotationLayer}`, logs, calls `.refresh()`; unknown name → `console.error`.
- `window.refreshAll()` — calls `.refresh()` on all four visual components in order.

**Removed from the old template:** WHO/CDC tab buttons + `onWHOClick/onCDCClick`,
the lbs/kg toggle + `onLbsClick/onKgClick`, percentile-curve rendering, the
`convertValues`/`unitsLabel` machinery.

---

## F. Bug Fixes

**Bug 1 — N+1 Note queries.**
*Old:* `Note.objects.get(dbid=obs.note_id)` called **inside** every per-observation
loop (and once per pair in the nested weight×length loop — O(N·M)).
*Fix:* `batch_load_notes(note_ids)` calls **`Note.objects.filter(id__in=note_ids)`
once** and returns `{note_id: Note}`; the processing loop does O(1) dict lookups.
Verified by `test_batch_fetch_not_get_in_loop` (`.filter` called once, `.get` never)
and `test_batch_returns_dict_keyed_by_id`.

**Bug 2 — Mutable default argument.**
*Old:* `def get_age_in_months(birth_date, date=datetime.datetime.now())` — `now()` is
evaluated **once at import**, so every call sees the import-time clock.
*Fix pattern:* `def f(..., date=None): date = date or datetime.now()`.
*Adult-plugin note:* `get_age_in_months()` is **removed entirely** (the X-axis is the
calendar date, not age). The `date=None` + `date = date or datetime.now()` pattern is
applied to **any** date-defaulting helper that survives (e.g. if a
`now`-defaulting param is used in week/sort helpers). `test_date_default_not_evaluated_at_import`
greps the module source and fails if `date=datetime.now()` appears in any signature —
so **no signature may default a param to `datetime.now()`**.

---

## G. Test Fix — `tests/test_cardiometabolic.py`

**Bug:** `test_handler_class_path_is_valid` iterates `components.protocols` treating
each element as a plain string — `":" in handler`, `handler.split(":", 1)`. The real
manifest stores each protocol as a **dict** with a `"class"` key
(`{"class": "module.path:ClassName"}`), so `":" in handler` checks dict membership and
`handler.split` raises `AttributeError`.

**Fix (per §G of the build prompt):** read the class string off `.get("class","")`:

```python
def test_handler_class_path_is_valid(self):
    manifest = self._load_manifest()
    for handler in manifest.get("components", {}).get("protocols", []):
        class_path = handler.get("class", "") if isinstance(handler, dict) else handler
        self.assertIn(":", class_path, f"Handler path missing colon separator: {class_path}")
        module, classname = class_path.split(":", 1)
        self.assertTrue(len(module) > 0 and len(classname) > 0)
```

This is the **only** test change. It is documented here because the test file is the
contract and this is a genuine test bug (not an implementation accommodation).

---

## H. Data Separation Contract

Every processed observation carries **both** a raw and a processed view, and **raw
fields are never overwritten**:

```python
{
  # processed (derived, recomputable)
  "id": str,
  "value_lbs": float,
  "date_label": str,             # "Jan 2024"
  "date_obj": datetime,
  "weeks_since_baseline": float,
  "tbwl_pct": float,
  "processed_at": str,           # datetime.now().isoformat()
  "processing_version": str,     # bump when conversion logic changes

  # raw (immutable snapshot of what Canvas returned)
  "raw": {
    "value_original": float,
    "unit_original": str,
    "canvas_note_id": str,
    "_loaded_at": str,
  },
}
```

`build_observation_processed` constructs the `raw` sub-dict by copying from the loaded
raw observation and **never** mutates it; all conversions write to the top-level
processed fields only. Satisfies `test_raw_data_preserved_separately`.

---

## I. Removed Features (explicit list)

- ☑ **`graphs/*.py` files** — deleted entirely (§B); zero imports remain.
- ☑ **WHO/CDC tab UI** — removed from `chart.html`; no tab buttons, no `onWHOClick/onCDCClick`.
- ☑ **Sex stratification gating** — removed; `sex_at_birth` is loaded but never gates rendering, and there is **no `return []` for non-M/F sex**.
- ☑ **`head_circumference`, `length`, `bmi` (and `height`) observation queries** — removed; only `name="weight"` is queried.
- ☑ **Unit toggle (lbs/kg)** — removed; **lbs only** for MVP (conversion to lbs happens server-side in `convert_weight_to_lbs`).
- ☑ **`get_age_in_months()` as the X-axis calculation** — removed; the calendar date (`datetime_of_service`) is the X-axis.

---

## J. Spec Self-Check

| Requirement | Spec says |
|---|---|
| X-axis | calendar date / `datetime_of_service` |
| Reference line | the patient's first weight observation (baseline) |
| graphs/ directory | deleted entirely |
| Tabs | none |
| Manifest name | `cardiometabolic_tracker` |
| N+1 fix method | `Note.objects.filter(id__in=...)` (single query) |
| Mutable default fix | `date=None` + `date = date or datetime.now()` |
| validate_chart_payload | called before `LaunchModalEffect` (chart not rendered on failure) |
| Raw data preserved | yes, in a nested `raw` dict; never overwritten |
| DiagnosticsPanel | Shift+D toggle; records timestamps from all 6 components + Python `_pipeline_timestamps` |

---

## Decisions — LOCKED (user selected Option B, 2026-06-05)

1. **`compute()` vs `handle()`** → **Option B (CONFIRMED).** Keep the pipeline in
   `handle()`; override `compute()` to defer to `super().compute()` for `SHOW_*_BUTTON`
   events (button renders + click routes) and otherwise call `self.handle()`, with a
   `try/except (AttributeError, TypeError)` guard around the regex match.
2. **Validation-failure effect** → **Option B (CONFIRMED).** Render the joined
   validation `errors` into an error template and return
   `[LaunchModalEffect(content=error_html).apply()]` — non-empty, chart not drawn.
   `EffectErrorBanner`/`AddBannerAlert` will **not** be used.
3. **`build_chart_data` second-arg overload** → type-branch on `notes_or_baseline`
   (`dict` → notes map; numeric/`None` → derive dates from the obs objects). This
   carries with Option B; flag if you'd rather split into two functions.
