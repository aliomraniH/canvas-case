cardiometabolic_tracker
=======================

Adult GLP-1 weight-management tracker for Canvas. Plots each patient's weight
against their **own baseline** (first weight observation) over calendar time,
annotated with % total body weight loss (TBWL). Adapted from the pediatric
growth_charts plugin — no population percentiles, no sex stratification.

> **Toolbox:** the master index of every debug/test tool, skill, test suite,
> and setup artifact for this plugin lives at
> [`extensions/TOOLBOX.md`](../TOOLBOX.md).

## What it shows (v0.2.0)

A **Weight Trajectory** action button in the chart-summary Vitals section
opens a large right chart pane containing:

- **Patient weight line** with hover tooltips (date, weight, %TBWL) and the
  latest %TBWL annotation.
- **Baseline reference line** (dashed) at the first observed weight.
- **%TBWL milestone lines** at 5 / 10 / 15% below baseline, labeled at the
  right edge, rendered only when they fall inside the chart's y-range and
  colored by whether the patient's latest TBWL has crossed them.
- **Expected-response band** — a low-opacity corridor of expected %TBWL from
  published GLP-1 trials, selected by detecting the patient's active GLP-1
  medication: semaglutide → STEP-1, tirzepatide → SURMOUNT-1, liraglutide →
  SCALE. No match / ambiguous / lookup error falls back to STEP-1 (legend
  shows the source).
- **4-week velocity stat** (%TBWL per week, interpolated across irregular
  visit spacing) plus informational flags: **Plateau**, **Regain**, and
  **Rapid loss**. Flag copy is descriptive decision support, never directive.
- Designed degraded states for single-measurement, sparse, and zero-data
  patients.

Decision rationale, band-table citations, and edge-case behavior live in
`assumptions_tests_rationale.md`; trial data in `glp1_science_reference.md`.

## Architecture

`protocols/growth_charts.py` is organized in five layers (see
`component_architecture.md`): Data Loading (SDK queries) → Processing (pure
functions — all v0.2 math lives here and is unit-testable) → Validation
(payload checks before any modal) → Render (template context) →
ActionButton handler (thin orchestration). The d3 template is
`templates/chart.html`.

## Tests

```bash
~/.local/share/uv/tools/canvas/bin/python -m pytest tests/ -q   # 107 tests
```

`tests/test_cardiometabolic.py` (v0.1, 58) + `tests/test_v02_enhancements.py`
(v0.2, 49), mocked at the SDK boundary. Pytest green is necessary but not
sufficient — live validation tiers are the second gate (see
`debug_skill_findings.md` and `extensions/DEBUG_TOOLING.md`).

## Install

```bash
canvas install . --host pxbuilder-aomrani
canvas list --host pxbuilder-aomrani | grep cardiometabolic
```

## Test data

`tools/seed_zztest_patients.py` seeds the nine demo patients (P1–P9) with
weight series and GLP-1 medication records, then
`tools/rename_and_annotate_patients.py` gives them distinct realistic names
(Margaret Okafor, Derek Vance, Sylvia Tran, …) and attaches a chart note
describing each scenario — see the v0.2 table in `demo_patients.md` for the
full name → scenario → patient-key mapping. Sandbox observation writes are
permanent: the scripts only ever write to patients created/verified by their
own run (guarded), credentials come from `extensions/.env`, and seeding
re-runs create fresh run-tagged patients. Pre-existing patients are
read-only fixtures.

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
