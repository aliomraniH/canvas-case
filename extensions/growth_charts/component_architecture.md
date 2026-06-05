# Component Architecture — cardiometabolic_tracker
# Canvas Medical Plugin
# Version: 1.0 — for CPA reference during build

---

## Purpose

This document defines how the plugin must be structured so that:
1. Each component can be loaded and tested independently
2. Each data transfer to HTML is traceable and refreshable
3. Debugging isolates failures to a specific layer
4. Future components can be added without restructuring existing ones

CPA must follow this architecture. Desktop companion will verify compliance
by reading the generated files against this spec.

---

## Python Layer — `protocols/growth_charts.py`

### Structure requirement
The file must be organized in clearly delimited sections with comments:

```
# ─────────────────────────────────────────────────────────────
# SECTION 1: Data Loading Layer
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# SECTION 2: Processing Layer
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# SECTION 3: Validation Layer
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# SECTION 4: Render Layer (template context assembly)
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# SECTION 5: ActionButton Handler
# ─────────────────────────────────────────────────────────────
```

### Section 1: Data Loading Layer

```python
# All functions in this section:
# - Accept only primitive types or Canvas SDK objects as inputs
# - Return simple Python dicts/lists (no side effects)
# - Can be called independently in unit tests with mocked SDK

def load_patient_demographics(patient_id: str) -> dict:
    """
    Returns: {
        "patient_id": str,
        "sex_at_birth": str | None,   ← kept for future use, NOT used for stratification
        "birth_date": date | None,
        "_loaded_at": str,            ← datetime.now().isoformat()
        "_component": "patient_demographics"
    }
    """

def load_weight_observations_raw(patient_id: str) -> list[dict]:
    """
    Queries Observation.objects for weight observations only.
    Does NOT fetch Notes (that's batch_load_notes' job).
    Returns: list of WeightObservationRaw dicts.
    Each dict contains:
        "id", "value_original", "unit_original",
        "canvas_note_id", "_loaded_at"
    """

def batch_load_notes(note_ids: list[str]) -> dict[str, object]:
    """
    SINGLE query: Note.objects.filter(id__in=note_ids)
    Returns: {note_id: Note} for O(1) lookup in processing.
    This is the N+1 fix.
    """

def attach_dates_to_observations(
    observations_raw: list[dict],
    notes_by_id: dict
) -> list[dict]:
    """
    Joins observations with their note dates using the pre-fetched notes dict.
    Returns each observation with "datetime_of_service" added.
    No DB calls in this function — pure dict manipulation.
    """
```

### Section 2: Processing Layer

```python
# All functions in this section:
# - Pure functions (no DB calls, no side effects)
# - Accept only Python primitives/dicts
# - Can be imported and tested standalone with pytest

def convert_weight_to_lbs(value: float, unit: str) -> float:
    """Converts any weight unit to lbs. Raises ValueError for unknown units."""

def compute_baseline(observations_with_dates: list[dict]) -> dict:
    """
    Selects earliest observation as baseline.
    Returns: {"value_lbs": float, "date": datetime, "source_id": str}
    """

def calculate_tbwl(baseline_lbs: float, current_lbs: float) -> float:
    """((baseline - current) / baseline) * 100. Raises ValueError if baseline <= 0."""

def calculate_weeks_since_baseline(baseline_date: datetime, current_date: datetime) -> float:
    """Returns float weeks between two dates. Negative if current < baseline."""

def format_date_mmmyyyy(dt: datetime) -> str:
    """Returns 'Jan 2024' style formatted date string."""

def build_observation_processed(obs_raw: dict, baseline_lbs: float) -> dict:
    """
    Converts a single raw observation to its processed form.
    Output structure:
    {
        # Processed fields
        "value_lbs": float,
        "date_label": str,         ← "Jan 2024"
        "date_obj": datetime,
        "weeks_since_baseline": float,
        "tbwl_pct": float,
        "processed_at": str,       ← timestamp
        "processing_version": str,

        # Raw fields preserved (nested)
        "raw": {
            "value_original": float,
            "unit_original": str,
            "canvas_note_id": str,
            "_loaded_at": str,
        }
    }
    """

def build_chart_data(observations_raw: list[dict], notes_by_id: dict) -> dict:
    """
    Orchestrates Processing Layer.
    Calls: attach_dates → compute_baseline → build_observation_processed (per obs)
    Returns the full template context dict (see Render Layer).
    """
```

### Section 3: Validation Layer

```python
def validate_chart_payload(payload: dict) -> tuple[bool, list[str]]:
    """
    Run BEFORE LaunchModalEffect.
    Returns (True, []) if valid.
    Returns (False, [error_message, ...]) if any check fails.

    Checks (in order):
    1. baseline_data key exists and has value > 0
    2. datapoints list is non-empty
    3. No future observation dates
    4. latest_tbwl_pct is in [-20, 50] range
    5. No zero/negative weight values
    6. datapoints sorted ascending by date_obj
    7. _pipeline_timestamps key exists
    8. All required template keys present
    """
```

### Section 4: Render Layer

```python
def assemble_template_context(
    patient: dict,
    baseline: dict,
    datapoints: list[dict],
    pipeline_timestamps: dict,
) -> dict:
    """
    Assembles the final dict passed to render_to_string().
    Each top-level key corresponds to a named JS component in chart.html.
    Every component dict includes _loaded_at and _component keys.

    Output:
    {
        "patient": {..., "_component": "patient_info", "_loaded_at": ...},
        "baseline_data": {..., "_component": "baseline_layer", "_loaded_at": ...},
        "datapoints": [...],   # list of processed observation dicts
        "latest_annotation": {..., "_component": "annotation_layer", ...},
        "chart_config": {
            "x_axis_type": "calendar_date",
            "y_axis_unit": "lbs",
            "show_benchmark_overlay": False,   # MVP: False
            "benchmark_source": None,
        },
        "_pipeline_timestamps": {
            "demographics_loaded": str,
            "observations_raw_loaded": str,
            "notes_batch_loaded": str,
            "processing_complete": str,
            "validation_passed": str,
            "template_context_assembled": str,
        }
    }
    """
```

### Section 5: ActionButton Handler

```python
class GenerateVitalsGraphs(ActionButton):
    """
    Thin orchestration layer only.
    Business logic lives in Sections 1-4.
    compute() calls each layer in sequence and handles errors.
    """

    def compute(self):
        # 1. Load
        patient = load_patient_demographics(self.patient.id)
        obs_raw = load_weight_observations_raw(self.patient.id)
        note_ids = [o["canvas_note_id"] for o in obs_raw]
        notes = batch_load_notes(note_ids)

        # 2. Process
        payload = build_chart_data(obs_raw, notes)

        # 3. Validate
        is_valid, errors = validate_chart_payload(payload)
        if not is_valid:
            # Return error banner instead of modal
            return [EffectErrorBanner(title="Chart Error", body="\n".join(errors))]

        # 4. Assemble context
        context = assemble_template_context(...)

        # 5. Render
        html = render_to_string("chart.html", context)
        return [LaunchModalEffect(content=html)]
```

---

## HTML/JS Layer — `templates/chart.html`

### Required JS component structure

Each visualization layer must be a named JS object with this interface:

```javascript
const ComponentName = {
    // State
    _data: null,
    _loadedAt: null,
    _isInitialized: false,

    // Required methods
    init(config) {
        // Called once after DOM is ready
        // config comes from Python-rendered JSON in template
        this._isInitialized = true;
        this._loadedAt = new Date().toISOString();
        console.log(`[ComponentName] init() at ${this._loadedAt}`);
        DiagnosticsPanel.recordTimestamp('ComponentName.init', this._loadedAt);
    },

    render(data) {
        // Called to draw/update this component
        if (!this._isInitialized) {
            console.error('[ComponentName] render() called before init()');
            return;
        }
        this._data = data;
        this._loadedAt = new Date().toISOString();
        console.log(`[ComponentName] render() at ${this._loadedAt}`);
        DiagnosticsPanel.recordTimestamp('ComponentName.render', this._loadedAt);
        // ... d3 or DOM manipulation ...
    },

    refresh() {
        // Re-renders with the same data (e.g., after resize or debug trigger)
        if (!this._data) {
            console.warn(`[ComponentName] refresh() called with no data`);
            return;
        }
        console.log(`[ComponentName] refresh() triggered`);
        this.render(this._data);
    },

    destroy() {
        // Cleanup if component is removed (e.g., for future hot-reload support)
        this._data = null;
        this._isInitialized = false;
    }
};
```

### Required components (in render order)

```javascript
// 1. Scaffold — must run first, sets up SVG canvas and axes
const ChartScaffold = { init, render, refresh, destroy };

// 2. BaselineLayer — horizontal dashed line at baseline weight
const BaselineLayer = { init, render, refresh, destroy };
// Data: { value_lbs: float, _loaded_at: str, _component: "baseline_layer" }

// 3. DataPointLayer — patient weight over time (line + dots)
const DataPointLayer = { init, render, refresh, destroy };
// Data: array of { value_lbs, date_label, date_obj, tbwl_pct }

// 4. AnnotationLayer — % TBWL label at the latest data point
const AnnotationLayer = { init, render, refresh, destroy };
// Data: { tbwl_pct: float, weight_lbs: float, date_label: str, _component: "annotation_layer" }

// 5. TooltipManager — hover tooltip for all data points
const TooltipManager = { init, refresh };  // no render() — tooltip is event-driven

// 6. DiagnosticsPanel — hidden overlay (Shift+D to toggle)
const DiagnosticsPanel = {
    timestamps: {},
    recordTimestamp(component, ts) { ... },
    render() { ... },
    toggle() { ... }
};
```

### Required initialization sequence

```javascript
// Bottom of chart.html — executed after all component definitions:
document.addEventListener('DOMContentLoaded', () => {
    // Data is injected by Python template rendering
    const chartData = JSON.parse('{{ chart_data_json|escapejs }}');

    // Strict initialization order
    ChartScaffold.init(chartData.chart_config);
    BaselineLayer.render(chartData.baseline_data);
    DataPointLayer.render(chartData.datapoints);
    AnnotationLayer.render(chartData.latest_annotation);
    TooltipManager.init(chartData.datapoints);

    // Log pipeline timestamps from Python
    Object.entries(chartData._pipeline_timestamps || {}).forEach(([k, v]) => {
        DiagnosticsPanel.recordTimestamp(`python.${k}`, v);
    });
    DiagnosticsPanel.recordTimestamp('js.domContentLoaded', new Date().toISOString());

    // Wire Shift+D toggle
    document.addEventListener('keydown', e => {
        if (e.shiftKey && e.key === 'D') DiagnosticsPanel.toggle();
    });
});
```

### Global refresh function (for debugging during live session)

```javascript
// Exposed on window so it can be called from browser console:
// window.refreshComponent('BaselineLayer')
// window.refreshAll()
window.refreshComponent = function(name) {
    const components = { ChartScaffold, BaselineLayer, DataPointLayer, AnnotationLayer };
    if (!components[name]) { console.error(`Unknown component: ${name}`); return; }
    console.log(`[DEBUG] Refreshing ${name}`);
    components[name].refresh();
};

window.refreshAll = function() {
    [ChartScaffold, BaselineLayer, DataPointLayer, AnnotationLayer].forEach(c => c.refresh());
};
```

---

## Data Flow Diagram

```
ActionButton.compute()
│
├─► SECTION 1: Data Loading
│   ├─ load_patient_demographics(patient_id)        → patient_dict
│   ├─ load_weight_observations_raw(patient_id)     → [obs_raw, ...]
│   └─ batch_load_notes(note_ids)                   → {note_id: Note}
│       └─ ONE query, not N queries (N+1 fix)
│
├─► SECTION 2: Processing
│   ├─ attach_dates_to_observations(obs_raw, notes)
│   ├─ compute_baseline(obs_with_dates)             → baseline_dict
│   └─ build_observation_processed(obs, baseline)   → processed_dict (per obs)
│       └─ raw fields preserved in nested 'raw' key
│
├─► SECTION 3: Validation
│   └─ validate_chart_payload(payload)
│       ├─ PASS → continue
│       └─ FAIL → return EffectErrorBanner (STOP — no modal rendered)
│
├─► SECTION 4: Render
│   └─ assemble_template_context(...)               → context dict
│       └─ every component dict has _loaded_at and _component
│
└─► SECTION 5: Handler
    └─ render_to_string("chart.html", context)
    └─ LaunchModalEffect(content=html)

──────────────────────────────────────────────
In chart.html (after LaunchModalEffect opens):

DOMContentLoaded
│
├─ ChartScaffold.init(config)    ← sets up SVG, axes
├─ BaselineLayer.render(data)    ← dashed horizontal line
├─ DataPointLayer.render(data)   ← patient weight line + dots
├─ AnnotationLayer.render(data)  ← % TBWL label
├─ TooltipManager.init(data)     ← hover events
└─ DiagnosticsPanel timestamps   ← records all above
```

---

## Testing Each Component Independently

### Testing Python components in isolation

```bash
# From the plugin root directory:

# Test ONLY the processing functions (no Canvas SDK needed)
python -m pytest tests/test_cardiometabolic.py -k "Unit" -v

# Test a single function
python3 -c "
from protocols.growth_charts import calculate_tbwl
print(calculate_tbwl(250.0, 212.5))  # should print 15.0
"

# Test the validation layer with a crafted payload
python3 -c "
from protocols.growth_charts import validate_chart_payload
payload = {}  # empty — should fail
is_valid, errors = validate_chart_payload(payload)
print('valid:', is_valid, 'errors:', errors)
"
```

### Testing HTML components in isolation

Each JS component can be tested by opening chart.html with mock data injected.
Create `templates/chart_test.html` (CPA should generate this):

```html
<!-- chart_test.html — standalone test harness for JS components -->
<!-- Open in browser to test without Canvas -->
<script>
// Inject mock data that would normally come from Python template
const MOCK_CHART_DATA = {
    chart_config: { x_axis_type: "calendar_date", y_axis_unit: "lbs" },
    baseline_data: {
        value: 250.0, unit: "lbs",
        _loaded_at: new Date().toISOString(), _component: "baseline_layer"
    },
    datapoints: [
        { value_lbs: 250.0, date_label: "Jan 2024", tbwl_pct: 0.0 },
        { value_lbs: 240.0, date_label: "Feb 2024", tbwl_pct: 4.0 },
        { value_lbs: 232.5, date_label: "Mar 2024", tbwl_pct: 7.0 },
        { value_lbs: 225.0, date_label: "Apr 2024", tbwl_pct: 10.0 },
    ],
    latest_annotation: { tbwl_pct: 10.0, weight_lbs: 225.0, date_label: "Apr 2024" },
    _pipeline_timestamps: { mock: new Date().toISOString() }
};
</script>
<!-- then include all the same JS component code from chart.html -->
```

---

## Compliance Checklist for Desktop Companion

When reviewing CPA-generated code, verify each item:

**Python file (`protocols/growth_charts.py`):**
- [ ] Five distinct sections with comment headers
- [ ] `load_weight_observations_raw()` exists and returns raw dicts
- [ ] `batch_load_notes()` uses `.filter(id__in=...)` not `.get()` in loop
- [ ] Processing functions are pure (no DB calls inside)
- [ ] Each observation has both raw and processed data
- [ ] `_loaded_at` timestamp in every component dict
- [ ] `_component` name in every component dict
- [ ] `validate_chart_payload()` called before `LaunchModalEffect`
- [ ] `compute()` returns `EffectErrorBanner` on validation failure
- [ ] No `sex == 'M' or sex == 'F'` gating anywhere
- [ ] No imports from `graphs/` directory
- [ ] `date=None` with `date = date or datetime.now()` (not `date=datetime.now()`)

**HTML file (`templates/chart.html`):**
- [ ] `DiagnosticsPanel` defined before any component `render()` calls
- [ ] Each component has `init()`, `render()`, `refresh()`, `destroy()` methods
- [ ] `_loadedAt` recorded in each component's `render()`
- [ ] `DiagnosticsPanel.recordTimestamp()` called in each component
- [ ] Python `_pipeline_timestamps` rendered into JS and recorded in DiagnosticsPanel
- [ ] `window.refreshComponent()` exposed for console debugging
- [ ] `window.refreshAll()` exposed for console debugging
- [ ] Shift+D toggles diagnostics overlay
- [ ] Strict initialization order: Scaffold → Baseline → DataPoints → Annotation → Tooltip
- [ ] No WHO/CDC tabs, no unit toggle, no sex stratification UI
