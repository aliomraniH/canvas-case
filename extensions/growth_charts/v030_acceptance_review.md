# v0.3.0 Independent Acceptance Review — cardiometabolic_tracker

Reviewer: independent Desktop review session (read-only toward plugin source
and EHR, separate from the implementation session). Date: 2026-06-11. Scope:
v0.3.0 export build (`c940f8e`..`18732cb`) per the approved v0.3.0 spec
(Export button + browser print pipeline), including the print-dialog →
save-as-PDF visual pass the build handoff left for this session.

## Verdict

**ACCEPTED at v0.3.0, no patch required.** Zero implementation defects found
in the shipped code. Every independently checkable claim in the build
session's outcome report held up. The save-as-PDF visual pass (the deploy
report's one outstanding item) is now done and PASSED. Two minor findings —
one pre-existing, one cosmetic — are recorded as a v0.3.1 candidate; neither
is worth a deploy cycle on its own.

## Evidence (all re-derived independently this session)

- **Tests:** 150 passed / 0 skipped / 0 failed under the canvas uv python
  (`~/.local/share/uv/tools/canvas/bin/python`), 1.15s — matches the claimed
  composition (137 baseline + 13 new, all mocked; the live gate was the build
  session's 15/15 sandbox run). The new suite covers the four required
  behaviors (disclosure survival, milestone derivation, single-observation
  degrade, button visibility) plus manifest↔code version pairing and the
  stray-conversion-literal scan extended to the template (v0.2.5 review
  finding 3, landed as promised).
- **No second data path (constraint 5):** `build_export_summary` is a pure
  mapping over the already-computed payload. Display sign flip
  (`-latest_tbwl_pct`, loss renders negative) exactly matches the v0.2.5
  headline convention; `build_milestone_status` uses the same
  `tbwl_pct >= pct` comparison as `compute_milestone_lines`' crossed-logic
  and is correctly independent of axis-domain line suppression.
- **Disclosure deviation verified correct:** shipped strings are the v0.2.5
  versions (`SCALE_BOUNDS_DISCLOSURE` full text; `legend_qualifier: "±1 SD"`),
  pinned verbatim by test. Shipping these over the build prompt's stale
  v0.2.1 string was the right call (codebase-as-source-of-truth).
- **Button absent on no-data patient is structural, not CSS:** the validation
  failure path emits a separate error HTML document; `chart.html` (and the
  Export button) never ships to that patient. Tests assert both directions.
- **Gate 1 re-verification:** `Patient.first_name` / `Patient.last_name`
  confirmed against the SDK source on disk (`canvas_sdk/v1/data/patient.py`).
- **Template hygiene:** `ExportView` builds all print DOM via `textContent`
  (no injection surface for patient-entered strings);
  `finalizeForPrint`'s d3 selectors match the real classes (same selector
  the animation code itself uses); `beforeprint` covers the browser-menu
  print path, not just the button.
- **Artifacts:** deploy report present (5 embedded screenshots), gap report
  and DEBUG_TOOLING additions match their descriptions. Credential scan of
  all four commits clean (only hits are the literal-scan test's own tokens).

## Save-as-PDF visual pass (closes deploy report §"one item left")

Session `2026-06-12T06-22-43Z_visual` (`.workspace_state/debug/`), 10/10
mechanical checks + page-level visual inspection by the reviewer. Real PDFs
were produced via Chromium print-to-PDF — the same renderer as the print
dialog's "Save as PDF" — from the extracted modal iframe document after
dispatching the shipped `beforeprint` finalize path, for P1
(responder, STEP-1) and P4 (liraglutide, SCALE).

Verified in the PDFs: header (name · DOB · export date · v0.3.0); chart in
final animation state (full series path, no tooltip, band + baseline +
milestone lines + ↓%TBWL annotation); stats block faithful to the payload
(P4 carries "Rapid loss" inline with velocity); SCALE disclosure VERBATIM in
the amber-bordered block on P4 and correctly absent on P1; all three trial
citations in fixed order; single portrait page; zero interactive chrome.

## Findings (v0.3.1 candidates, neither blocking)

1. **Export date stamps the UTC date** (`ExportView.finalizeForPrint`:
   `new Date().toISOString().slice(0, 10)`). This review ran at ~23:22 PT on
   2026-06-11 and the PDFs read "Exported 2026-06-12" — any export after
   ~5pm PT carries tomorrow's date on a clinical document. One-line fix:
   stamp the local date.
2. **Pre-existing (not v0.3.0): `_render_error` interpolates error strings
   into HTML unescaped**, and one path carries observation-entered content
   (`Unknown weight unit: {unit!r}` from `convert_weight_to_lbs`). Since
   `about:srcdoc` inherits the parent (EHR) origin, markup in a unit string
   would execute with that origin. Low likelihood; one-line `html.escape`
   fix plus one mocked test.

Also noted, by design (no action): milestone reached-dates print at month
granularity because they reuse the chart's `date_label` — consistent with
the chart axis; the export does not claim day precision.
