# v0.5.0 Independent Acceptance Review — cardiometabolic_tracker

Reviewer: independent review session (read-only toward plugin source, tests,
manifest, and EHR; separate from the implementation session). Date:
2026-06-13 (review executed ~01:30–02:05Z; live pass on `pxbuilder-aomrani`).
Scope: v0.5.0 "Provider-entered manual baseline + medication selection +
billing-aware note" — commits `aaf3215 → c452945 → 9ae3405 → 6e40979` on top
of `1aca10e`, against the 15-point contract (features 1–15) plus Amendments
1–4 and the five approved option dispositions. Every checkable claim was
re-derived this session; nothing was taken on the build session's word.
READ-ONLY throughout — no code changes, no commits, no FHIR writes, no
`canvas install`; the only browser writes were the plugin's own provider-flow
on the new fixtures (P10/P11) and the manual baseline Ali set on Jane Will.

## Verdict

**ACCEPTED at v0.5.0, no patch required.** Zero implementation defects found.
All distinct checks in this review's own independent live pass passed,
including the decisive Amendment-1 backdated-band-offset measurement. Seven
of 35 raw assertions in my first live script reported FAIL; on triage **all
seven were artifacts of my own assertion strings or console classifier, not
plugin behavior** (detailed under "Triage of raw failures" — recorded in full
so the conclusion is auditable). Two outcome-summary items are imprecisely
worded and one contract clause is internally contradictory with another; all
three are reporting/spec nits, not code defects, and are listed separately.

## Evidence (all re-derived independently this session)

- **Tier 0 — installed & enabled:** `canvas list` on `pxbuilder-aomrani`
  shows `cardiometabolic_tracker@0.5.0  enabled`. (CLI also prints the
  0.163.1→0.166.0 upgrade notice — deferred, pre-existing, not a v0.5.0
  concern.)

- **Commits & hygiene:** exactly four commits on `1aca10e`: `aaf3215`
  (feat(wip): python layer), `c452945` (feat: UI + manifest + tests),
  `9ae3405` (fix: live-found sandbox + event-log bugs), `6e40979` (docs:
  deploy report + env facts). Conventional-commit format, accurate bodies.
  `git status`: `main...canvas-case/main [ahead 4]` — local only, **nothing
  pushed**, matching the build session's "local only, per the process gate."
  Credential scan of the full `1aca10e..HEAD` diff and the deploy report
  against all five `.env` values: the only hit is `CANVAS_HOST`
  (`pxbuilder-...`), which already appears in 13 files at the base commit —
  the established instance-hostname convention, not a new secret exposure.
  The four sensitive `.env` values (username, password, client id/secret) are
  absent from every artifact.

- **Tests — 235 passed / 0 skipped / 0 failed** in 1.28s under the canvas uv
  python (`~/.local/share/uv/tools/canvas/bin/python`; system python3
  under-collects per the project's known env fact). Composition verified, not
  assumed: `git diff 1aca10e..HEAD -- tests/` shows only the new
  `test_v05_manual_baseline.py` (+792) plus **12 lines** in
  `test_v04_event_log.py` — the latter being exactly two version-pin
  assertions made symbolic (`== PLUGIN_VERSION`, manifest↔code pairing). The
  other three baseline suites are byte-untouched. New file contributes
  exactly **56** tests; 179 baseline + 56 = 235. ✓ (See nit #1 on the
  "byte-untouched" wording.)

- **The new tests assert the contract** (opened and read, not counted):
  - `test_backdated_band_week0_anchors_to_baseline_date` and
    `test_reference_is_provider_baseline_not_visit_1` cover Amendment 1
    (band/%TBWL/reference anchored to `baseline_date`, not `set_at_utc`).
  - `test_header_verbatim` + `test_correction_header_prepended_first` pin the
    Amendment-3 correction header string verbatim and assert first-save has
    no header.
  - `test_constant_referenced_only_from_manual_baseline_path` is a real
    scope-guard (Amendment 4) — asserts `ADULT_WEIGHT_PLAUSIBILITY_LB` is
    unreachable from pediatric-lineage paths.
  - `test_unknown_patient_400_no_effects`, `test_validation_errors_400_no_effects`,
    `test_bounds_confirm_required_no_effects` cover "400 → zero effects."
  - `test_unknown_schema_versions_fail_closed`, `test_malformed_values_fail_closed`
    cover schema-"2" fail-closed parsing.
  - `test_loader_keys_pre_existing_unchanged_created_added` pins the additive
    `created` passthrough (feature 12) — all prior loader keys/values
    unchanged.
  - Structural-absence both directions:
    `test_empty_state_structural_absence` (no chart/panel/export markup in
    empty state) + `test_error_document_still_has_no_baseline_ui`.
  - **Gap (v0.5.1 candidate #1, below):** the missing-NoteType / missing-
    PracticeLocation **fail-closed 5xx** path is implemented but has no test —
    the `_run` harness always mocks both lookups present.

- **Source spot-checks (read):**
  - `PLUGIN_VERSION = "0.5.0"` (growth_charts.py:64); manifest
    `plugin_version` = 0.5.0 — paired. Manifest registers `ManualBaselineAPI`
    with `data_access.write` = PatientMetadata / Note / Command **only**
    (verified by walking the JSON). ✓ features 9, 11.
  - `MANUAL_BASELINE_CUTOVER = datetime(2026, 6, 12, 18, 0, 0, tzinfo=utc)`
    (line 86) — present with a UTC value; gate compares earliest observation
    `created` against it (line 1820). ✓ feature 2b.
  - No `str.format(`/`format_map` anywhere in `protocols/` (the only
    `.format` token is a comment explaining the f-string rebuild at
    line 1851). ✓ live-bug-1 fix real.
  - `window.DiagnosticsPanel = DiagnosticsPanel;` exported at chart.html:505;
    dialog reads it at growth_charts.py:288. ✓ live-bug-2 fix real.
  - `ADULT_WEIGHT_PLAUSIBILITY_LB` (line 95) referenced only from the form
    validator (1924) and the save handler (2418) — never from band/pediatric
    code. ✓ scope guard holds in source, not just in the test.
  - Fail-closed 5xx present: `select_counteling_note_type() is None → 500`
    (2349) and `PracticeLocation ... is None → 500` (2354), both returning a
    single JSONResponse with zero effects. ✓ feature 9 (untested — see #1).
  - SCALE band: `legend_qualifier = "±1 SD"`, `estimated_bounds = True`,
    `disclosure = SCALE_BOUNDS_DISCLOSURE` (lines 469–470, design since
    v0.2.4); band builders reused, not modified. ✓ disclosure intact.

- **Independent live pass (own headless Playwright script, own assertions,
  read-only except the plugin's own P10/P11 flow + Ali's Jane Will baseline;
  scripts and JSON under
  `.workspace_state/debug/2026-06-13T01-52-18Z_visual-console_v05_review/`):**

  - **Jane Will** (`53e062d0…`, the baseline Ali set this session): resolves
    to **manual mode**; `Provider-confirmed baseline: 152.0 lb as of
    2026-06-12`; **STEP-1 band** (`semaglutide_step1`, so Semaglutide was
    selected), band week-0 at 2026-06-12, **band-only chart (0 datapoints)**
    because she has no weight observations; no discrepancy notice; "Adjust
    baseline" button present; no empty-state copy. Screenshot
    `001_jane_will_chart.png` independently confirms the **full note-narrative
    contract (feature 4)** live: the counseling note renders "Baseline weight:
    152.0 lb (as of 2026-06-12). Medication: Semaglutide (Wegovy). Provider
    note: Visit for GLP-1 treatment. **Time spent: 15 minutes**" — all four
    narrative fields present, Time-spent populated (not fabricated). The note
    is **encounter-capable** (Sign / Coding / "Add a CPT" present), authored
    "with Richard Wilson, MD at California location" → provider_id from the
    staff session and practice_location from runtime lookup, as specified.

  - **P10 Noor Haddad** (zero data): manual mode, **SURMOUNT-1**
    (`tirzepatide_surmount1`), band-only chart with **0 datapoints / 5 band
    points**, no discrepancy notice (no active GLP-1). The Note section holds
    **five** "Weight management — provider-confirmed baseline" notes = the
    original + four corrections — independent live confirmation that the
    Amendment-3 revision chain creates a distinct note per re-save. Notes are
    encounter-capable (Coding/CPT section visible, `102_p10_notes.png`).

  - **P11 Marcus Bell** (gated follow-ups + active semaglutide): **DECISIVE
    Amendment-1 check passed** — after the backdated baseline, the STEP-1
    band's **week-0 anchors at `2026-04-10T00:00:00`** (the backdated clinical
    date), **not** the record-creation/`set_at_utc` time; 4 datapoints
    rendered; **agreement path → no discrepancy notice**. This is the single
    most important check in the contract and it is observed, not inferred.

  - **Regression P1 / P4 / P7:** all **legacy mode**, no Set-baseline button,
    no empty-state copy, chart + v0.4 export button + event-log panel markup
    intact. P1 visit-1 baseline **220.0** unchanged. P1 support-report
    download works in the srcdoc iframe; `schema_version` still **"1"**,
    `plugin_version` "0.5.0", 23 entries, all pre-existing keys present
    (`entries, generated_at, launch_target, patient_fhir_id, plugin_version,
    schema_version, user_agent`). P4 legend renders `Expected response
    (SCALE, ±1 SD)` with the disclosure intact. P7 single measurement, no
    band (no GLP-1 on file).

  - **Console triage:** 106 error/warning entries captured across the pass;
    after classification **zero are plugin-attributable.** The six my first
    classifier tagged "plugin" are all the identical host message — *"The
    Content Security Policy directive 'upgrade-insecure-requests' is ignored
    when delivered in a report-only policy"* — emitted by the platform's
    report-only CSP wrapper around the `about:srcdoc` iframe, not by plugin
    code (same host-noise class the build session and the v0.4.0 review both
    recorded). Remainder are S3/asset/host.

## Triage of raw failures (all seven explained; none are defects)

| Raw FAIL | Root cause | Disposition |
|---|---|---|
| P10 "SURMOUNT-1 band" | band agent key is `tirzepatide_surmount1`; my assertion checked for bare `tirzepatide` | PASS — correct band |
| P11 "STEP-1 band" | band agent key is `semaglutide_step1`; same too-strict assertion | PASS — correct band (and the decisive offset check passed) |
| P1 "export carries pre-existing keys" | real key is `entries`, my assertion read `events`; all keys in fact present, schema "1" | PASS — export intact |
| P4 "SCALE estimated qualifier" | actual qualifier is `±1 SD` (v0.2.4 design); the contract's word "estimated" is the prompt author's paraphrase | PASS — disclosure intact (nit #2) |
| console "zero plugin errors" | classifier keyed `about:srcdoc` URL as plugin; the 6 hits are host CSP report-only | PASS — zero genuine plugin errors |
| JW "counseling note visible" | note narrative lives in a PlanCommand component, not `body.innerText`; confirmed via screenshot 001 | PASS — note present & complete |
| P10 "CORRECTION header in Note section" | committed note bodies are collapsed in the timeline and render as locked artifacts, not page text; two DOM text reads returned nothing | PASS by convergent evidence (see note) |

Note on the correction header: I made two read-only attempts to extract the
verbatim header from the live committed-note body and both returned no text —
Canvas renders signed/committed notes as locked command artifacts that the
timeline does not expose as `innerText`. I stopped at two attempts (project
stop-loss rule). The header is nonetheless verified by convergence: (a)
`test_header_verbatim` pins the exact string and passes; (b) source builds it
with f-strings at growth_charts.py:1851 (the live-fixed sandbox bug); (c) the
**five-note chain on P10 is confirmed live**, which is only producible by the
correction re-save path; (d) the build session's deploy report screenshots it
in the Note section. The header's *rendered* text was not independently
re-derivable from the live DOM by text scan — a review-tooling limitation, not
a plugin defect.

## Findings

### BLOCKING (defects requiring a patch)
**None.**

### v0.5.1 candidates
1. **Add the missing-NoteType / missing-PracticeLocation fail-closed test.**
   The 5xx-zero-effects behavior is implemented (growth_charts.py:2349–2358)
   and named in contract feature 9 and the review protocol, but the
   `TestManualBaselineAPI._run` harness always mocks both lookups present, so
   no test exercises the `None → 500` branches. Add two cases
   (`select_counseling_note_type → (None, …)` and
   `PracticeLocation…first → None`) asserting status 500 and zero effects.
   *Evidence:* tests/test_v05_manual_baseline.py:543–566; source 2349–2358.
2. **Persist baseline-action events.** (Build session already flagged.) The
   dialog's baseline-action events live only in the open session's panel; a
   support report pulled after a chart reopen won't carry them. Persist recent
   action events into PatientMetadata or a second key if support reports must
   survive reopens. *Evidence:* agent-handoff/brief.md, this session's P1
   export shows only render-lifecycle entries.
3. **Review-tooling note (low priority):** committed Canvas note bodies are
   not reachable via frame `innerText`; a future live-review script that needs
   to assert note-narrative text should screenshot + visually confirm (as this
   review did for Jane Will) or open the note's command API, rather than scan
   page text. Worth a line in DEBUG_TOOLING.md's Canvas-iframe section.
4. CLI 0.163.1→0.166.0 upgrade still deferred (pre-existing, not introduced
   here).

### By-design, recorded, no action
- **Note-type fallback ships unexercised.** Tier-1 inventory found active
  Encounter types (`chronic_care_management_note`, SNOMED 308335008), so the
  chart-review REVIEW fallback path is present but never taken — recorded in
  the deploy report and reflected in the reminder copy, exactly as feature 4
  requires.
- **Empty-state + dialog are inline Python-constant HTML**, not separate
  `.html` templates — assembled like the proven error-document pattern; keeps
  the structural-absence guarantee identical and avoids `render_to_string`
  plugin-context failures in unit tests. Defensible deviation, disclosed.
- **Two v0.4 version-pin assertions made symbolic** — forced by the 0.5.0
  bump; see nit #1. Disclosed in the test docstrings and commit message.

## Reporting / spec nits (separate from defects)
1. **The "byte-untouched tests" clause is internally contradictory.**
   Contract feature 14 demands `git diff -- tests/` show only the new file,
   while feature 11 demands version 0.5.0 — but the v0.4 suite hard-pinned
   `"0.4.0"` in two assertions, which cannot both stay byte-identical and
   pass after the bump. The build resolved it the only correct way (two pins
   made symbolic, everything else untouched, disclosed). The contract wording,
   not the build, is at fault; future prompts should say "byte-untouched
   except version-pin literals, which become symbolic."
2. **Outcome-summary / contract wording "SCALE, estimated".** The live and
   source qualifier is `(SCALE, ±1 SD)`; "estimated" is the prompt's paraphrase
   of the `estimated_bounds` flag that *drives* the ±1 SD disclosure. The
   disclosure is intact; the word "estimated" never appears in the legend by
   design (v0.2.4). Conclusion holds; wording is loose.
3. **Review-protocol "enumerate commits since 1aca10e".** That base is correct
   for this cycle (the four v0.5.0 commits), but a reviewer enumerating "since
   1aca10e" with no upper bound will also sweep the already-pushed
   toolbox/skills/v0.4-review commits below it; scope to the four unpushed
   commits.

---

*Review complete. This file is left uncommitted for Ali per the read-only
protocol. Live-pass scripts, JSON results, console log, P1 support-report, and
nine screenshots are under
`extensions/.workspace_state/debug/2026-06-13T01-52-18Z_visual-console_v05_review/`.*
