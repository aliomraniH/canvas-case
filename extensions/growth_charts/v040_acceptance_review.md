# v0.4.0 Independent Acceptance Review — cardiometabolic_tracker

Reviewer: independent review session (read-only toward plugin source, tests,
manifest, and EHR; separate from the implementation session). Date:
2026-06-12, review executed ~11:16–11:21 PDT (America/Los_Angeles). Scope:
v0.4.0 "Diagnostics panel hardening + review fixes" (`af289e7` + `1aca10e`
on top of `21b6b38`) against the approved R1/R2 + D1–D4 spec and the three
approved judgment-call dispositions. Every checkable claim was re-derived
this session; nothing was taken on the build session's word.

## Verdict

**ACCEPTED at v0.4.0, no patch required.** Zero implementation defects
found. All 60 checks in this review's own independent live pass passed —
including four classes of checks the build session's Gate 5 did not run
(no-data structural absence, python↔js skew measurement, value-level D4
spot-checks, and the R1 decisive cross-midnight case, now **observed**, not
just structural). One outcome-summary claim was imprecisely worded (console
triage, finding 3 below) but its conclusion holds; it is a reporting nit,
not a code defect.

## Evidence (all re-derived independently this session)

- **Commits & hygiene:** exactly two commits on `21b6b38`: `af289e7` (feat:
  impl + tests) and `1aca10e` (docs: deploy report + environment facts).
  Conventional-commit format, accurate bodies. `git status`:
  `main...canvas-case/main [ahead 2]` — local only, nothing pushed.
  Credential scan of both diffs: the only hits are the scan-test's own
  `token` variable names (same acceptable class as v0.3.0).
- **Tests: 179 passed / 0 skipped / 0 failed** in 1.29s under the canvas uv
  python. Composition verified, not assumed: `git diff 21b6b38..HEAD --
  tests/` shows ONLY the new `test_v04_event_log.py` (+405 lines) — the 150
  baseline tests are byte-untouched; the new file contributes exactly 29.
  All 179 mocked/pure (Gate 4 composition honest in the test docstring,
  commit message, and deploy-report badges).
- **The new tests assert what the spec demands** (each opened and read):
  - PHI guard (`test_no_demographics_anywhere`) is genuinely **recursive**
    (`keys_of` walks nested dicts/lists); `name` is excluded only inside
    entries where it is the event name, and the exact top-level key set is
    separately pinned so a stray top-level demographic key cannot hide.
  - R2 test uses the exact observation-entered shape
    `Unknown weight unit: '<img src=x onerror=alert(1)>'` and asserts the
    markup renders inert (`&lt;img` present, `<img` absent), plus a
    multi-error-path case and a plain-readability case.
  - Disposition-(a) scan asserts the template contains **no**
    `schema_version` / `patient_fhir_id` / `launch_target` literals and
    **does** contain the three permitted fills.
  - Disposition-(c) regression test correctly does not exist — Gate 2 was
    negative (below) and the loader is untouched in the diff.
- **R1 in source:** `finalizeForPrint` builds the stamp from
  `getFullYear()/getMonth()+1/getDate()`; `toISOString().slice(0,10)` absent
  from the template (both spacing variants pinned by test; my grep agrees —
  remaining `toISOString()` calls are the export `generated_at` and event
  timestamps, where UTC is the spec).
- **R2 in source:** `_render_error` escapes every interpolated value
  (`html.escape(str(e))` per item; all other markup static). The incidental
  `html`→`rendered_html`/`error_html` rename was genuinely required — the
  local assignment would have made `html.escape` raise `UnboundLocalError`.
- **`_now_iso()`** emits `datetime.now(timezone.utc).isoformat()` with
  `+00:00`→`Z` — UTC-Z at the source.
- **Purity:** `build_log_export` and `build_table_rows` read only their
  arguments and module constants (`LOG_EXPORT_SCHEMA_VERSION`,
  `PLUGIN_VERSION`, `LOG_ORIGINS`, `SOURCE_METHOD_NOT_RECORDED`); no
  queries, no globals, no second data path. `log_export_base` is built in
  `assemble_template_context` from the pipeline-timestamps dict with
  `patient.get("patient_id")` only.
- **textContent-only:** the entire DiagnosticsPanel render path (log rows,
  table head/body/cells, caveat, fallback `<pre>`) uses
  `createElement`/`textContent`; the panel's former `innerHTML` row builder
  is gone. `innerHTML` survivors in the template are `= ''` clears or
  pre-existing v0.2.x regions (StatsBar headline, band-info panel) that
  interpolate only server-computed numerics and plugin constants — no
  observation-entered strings, and outside the v0.4.0 touched regions
  (finding 4).
- **Verbatim pins:** both D3 strings match character-for-character in source
  (tag-stripped) and rendered live (`===` comparison, em-dash included).
  The "diagnos" scan covers both template and protocol source with the
  approved two-token allowlist — broader than the spec asked.
- **Version pairing:** manifest `plugin_version` == `PLUGIN_VERSION` ==
  `"0.4.0"`; the manifest diff touches nothing else (class-path prefix and
  flat layout unchanged).
- **Gate 2 re-derived:** I read
  `canvas_sdk/v1/data/observation.py` and `device.py` on disk myself.
  `Observation` carries `patient, is_member_of, category, units, value,
  note_id, name, effective_datetime` + audit/id base fields — **no `method`,
  no `device`**, and `Device` has no relation to Observation at all. Also
  double-sourced against docs.canvasmedical.com/sdk/data-observation
  (attribute table confirms: no method, no device). **My verdict matches the
  build session's**; "Not recorded" universally is the only compliant
  rendering, and disposition (c) is moot.
- **Tier 0:** `canvas list` run by me: `cardiometabolic_tracker@0.4.0
  enabled`.
- **Deploy report:** `extensions/deploy_reports/v0.4.0_2026-06-12.html`
  (1,400,069 bytes, 4 embedded screenshots, self-contained). Badges carry
  the honest composition (`179 collected · 0 skipped · 179 mocked · 0
  live` + `47/47 live`); names the shipped download tier with rationale
  ("Blob + anchor (Tier 1) … fallbacks were never needed — recorded as the
  shipped tier"); records the Gate 2 verdict and the disposition-(b) audit
  result. DEBUG_TOOLING.md additions match their commit description.

## Independent live pass — 60/60 checks PASSED

Session `2026-06-12T18-16-27Z_console` (`.workspace_state/debug/`), own
script with own assertions (not a rerun of the build's Gate 5), headless
Chromium, read-only, zero FHIR writes. Patients: P1 Okafor (dense
responder), P4 Ramirez (SCALE), P7 Raghunathan (single measurement), Jane
Will (no-data fixture). Artifacts kept: `review_results.json`, both
downloaded support reports, classified console log, 5 screenshots.

- **D1:** Shift+D opens AND closes (true toggle); × closes; Esc closes; all
  three return focus to `#cm-container` (`document.activeElement` checked),
  and the returned focus is real — Shift+D reopens from it **without a
  re-click** (keyboard-flow check).
- **D2:** Blob+anchor download fired in the `about:srcdoc` iframe on P1 and
  P4 (shipped tier observed first-hand). Both payloads validated: exact
  7-key schema, `schema_version "1"`, `plugin_version "0.4.0"`,
  `launch_target right_chart_pane_large`, `patient_fhir_id` == the ID and
  nothing else, browser-filled `generated_at`/`user_agent`, all 23 entries
  exact `{name, timestamp_utc, origin}` shape with Z-suffixed UTC
  timestamps including the seven `python.*` entries. Filename
  `cardiometabolic_tracker_log_2026-06-12T18-19-32Z.json` pattern-exact.
  **PHI beyond the key scan:** value-level sweep of both downloaded reports
  for the patients' actual names, DOB year, and "zztest" — zero hits.
  **Timestamp skew (the v0.3.x 5h bug): measured 0.2s (P1) and 0.1s (P4)**
  between the latest python.* and earliest js entry — gone at the source.
  All 23 on-screen panel rows appear verbatim (name + timestamp) in the
  export — the two surfaces cannot disagree.
- **D3:** header and footer strings rendered exactly as pinned; no
  "diagnos" in any visible text on P1 or P4.
- **D4:** P1 — 15 rows == 15 chart datapoints; **every row's** weight and
  %TBWL matched `DataPointLayer._data` exactly; last row ↓12.1% matches
  both the chart annotation and the stats headline; Δ-baseline arithmetic
  verified against the 220 lb baseline; "Not recorded" universal; full ISO
  (Z-suffixed) in every title attr; no caveat on the dense patient. P7 —
  exactly 1 row with sane values (Δ +0.0 lb, ↓0.0%, no velocity artifacts)
  and the single-measurement caveat mirrored verbatim from `#cm-data-note`.
- **Structural absence (no-data, Jane Will):** the error document renders
  ("Cannot compute baseline from zero observations"); panel, download
  button, weight table, and any Shift+D affordance are **absent from the
  DOM**, not hidden — both directions confirmed (markers present in
  chart.html, absent in the error payload, per the structural-absence
  tests; and live).
- **R1:** at the runner's wall clock (~11:19 PDT, America/Los_Angeles,
  local date == UTC date) the stamp matched the local date. Then the
  decisive case, which the build session could not observe: a
  **Pacific/Kiritimati (UTC+14) browser context** where local
  (2026-06-13) ≠ UTC (2026-06-12) — the export stamped **2026-06-13, the
  LOCAL date**. The original ~5pm-PT-rollover defect is demonstrably fixed,
  not just structurally absent.
- **Console triage (DEBUG_TOOLING taxonomy):** 106 error-class entries
  across all five pages; 93 unknown + 9 host + 4 plugin-classified — all 4
  the identical host-delivered CSP report-only notice
  (`upgrade-insecure-requests` ignored) surfacing in the srcdoc frame.
  **Zero plugin-attributable errors.**

## Findings

**BLOCKING: none.**

**v0.4.1 candidates:**

1. **Console-triage classifier counts host CSP notices as "plugin"** (by
   URL `about:srcdoc`). Harmless — the check allowlists CSP text — but it
   made the build's outcome summary state "84 error-class entries, all
   classified host/unknown" when its own log records 81 host/unknown + 3
   plugin-classified CSP notices. Tighten the classifier (CSP report-only
   notices are host-policy artifacts) so the summary line can be generated
   from the log without caveats.
2. (Carried from build, confirmed real) **`host` origin is unreachable in
   production reports** — every entry in both sessions' downloaded reports
   is `origin: "plugin"` by construction. The proposed
   `window.onerror`/`unhandledrejection` hook is the right shape.
3. (Carried from build, confirmed real) **Event-log growth is unbounded** —
   `recordTimestamp` appends per component render with no cap.
4. (Build's candidate 3 — **already done by this review**): the TZ-pinned
   R1 rerun. The Kiritimati observation above closes it; no further action
   needed unless the stamp code changes.
5. (Carried, chore) Canvas CLI 0.163.1 → 0.166.0 between cycles, with a
   full suite re-run.

**By-design / recorded, no action:**

- **The download-tier ladder's middle tier (print-pipeline reuse) exists as
  documentation, not code** — the runtime chain is Blob+anchor →
  copyable-`<pre>` guard. Compliant: the spec's ladder governed what ships,
  Tier 1 verified working in two independent live sessions, and the shipped
  tier is recorded in the deploy report as required.
- **`_capture_iso` naive passthrough:** the table's title attr is full
  UTC-Z ISO for tz-aware (FHIR-created) observations; a hypothetical naive
  (UI-created) observation would carry its naive ISO rather than a
  guessed-offset "UTC". Deliberate, pinned by test, consistent with the
  fixed-at-source normalization rule (never guess offsets); every row on
  this instance rendered Z-suffixed. The spec's "full UTC ISO" wording is
  met everywhere it can be met without inventing data.
- **Support-report filename uses seconds precision** (milliseconds
  dropped, `Z` re-appended) — matches the spec's
  `<ISO8601-UTC, colons→hyphens>` requirement; noted only for exactness.
- **Pre-existing (v0.2.x) `innerHTML` in StatsBar/band-info** interpolates
  server-computed numerics and plugin constants only (no
  observation-entered strings — the R2 class does not apply); outside
  v0.4.0's touched regions. Candidate for opportunistic textContent
  conversion in a future cosmetic pass, not a defect.

## Dispositions & gates

- **(a) JS schema boundary — COMPLIANT.** `downloadSupportReport` fills
  exactly `generated_at`, `user_agent`, and `entries` (python base entries
  + its own `{name, timestamp_utc, origin:'plugin'}` appends) over the
  server-built base; the template-scan test enforces no other schema-key
  literals, and my grep of the template agrees.
- **(b) UTC-Z audit — AUDIT HAPPENED AND ITS CONCLUSION IS CORRECT.** The
  deploy report records the audit; I re-derived it: `_loaded_at` /
  `processed_at` / `_pipeline_timestamps` are referenced **nowhere** in the
  template (grep: zero hits — the old JS consumer of
  `_pipeline_timestamps` was removed; entries now arrive pre-classified in
  `log_export_base`). The only clinician-facing datetime added (table date
  column) converts to local at the display point (`toLocaleString()`);
  UTC-Z appears only on the two technical surfaces (panel, export) where it
  is the spec'd format.
- **(c) Loader pass-through — MOOT, CORRECTLY.** Gate 2 negative (verified
  by me against SDK source AND docs); the diff contains no loader change of
  any kind, so the additive-only condition and its regression test do not
  arise.
- **Gate 3 (spec freeze):** new test file pinned `# Verifies: v0.4.0 —
  spec approved 2026-06-12`; baseline suites byte-untouched.
- **Gate 4 (gates measure reality):** mock/live composition stated honestly
  in all three places; the live gate was run separately (build 47/47; this
  review 60/60, superset).
- **Gate 5 (over-development):** artifacts sized to scope — one test file,
  one panel extension, two pure builders; no shadow verification stack. The
  runtime copyable-view guard is the one speculative branch and it is small,
  justified, and was exercised never (Tier 1 works).
- **House rules:** SCALE_BOUNDS_DISCLOSURE / `legend_qualifier "±1 SD"` /
  citation pins live in the byte-untouched baseline suites and pass;
  `from __future__ import annotations` retained in the touched module and
  present in the new test file; underscore-prefixed keys accessed via
  `.get()` throughout the new code; flat layout and manifest class-path
  prefix unchanged; chart data pipeline / milestone / velocity logic and
  the v0.3.0 export path untouched beyond R1; email transport, method
  inference, and seeding correctly absent.

## Outcome-summary cross-check

Every independently checkable claim in the build session's outcome summary
was checked. All held, with one wording imprecision: the console-triage
line "84 error-class entries, all classified host/unknown" — the session's
own log shows 81 host/unknown + 3 plugin-classified CSP report-only notices
(deliberately allowlisted by the check). The substantive claim — zero
plugin-attributable errors — is true, and my own 106-entry capture
reproduces the same shape (finding 1). Claims verified true include: Tier 0
enablement; commit range and local-only status; 179/0/0 with byte-untouched
baseline + 29 new; 47/47 Gate 5 results file with both downloaded reports
present; Tier 1 shipped with fallbacks unused (guard present in code); both
pinned strings; 15-row/1-row table behavior; Gate 2 double-sourcing; the
disposition-(b) audit; the `html`-shadowing fix's necessity; deploy-report
size/contents; and the DEBUG_TOOLING.md / build-discipline known-facts
additions.

— Left uncommitted for Ali to review and commit, per the review brief.
