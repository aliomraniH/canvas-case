# v0.2.5 Independent Acceptance Review — cardiometabolic_tracker

Reviewer: independent review session (read-only toward plugin source and EHR,
separate from the implementation session). Date: 2026-06-10. Scope: v0.2.5
build (`e5cbfc2`..`081f502`) per the approved v0.2.5 spec (Task A basis-wording
fix; Task B patient-unit context B1–B6).

## Verdict

**ACCEPTED at v0.2.5, no patch required.** Zero implementation defects found.
Every claim in the build session's outcome report that could be checked
independently held up; three minor reporting/hardening nits are recorded below
as v-next candidates, none worth a deploy cycle on their own.

## Evidence (all re-derived independently this session)

- **Tests:** 137 passed / 0 skipped / 0 failed under the canvas uv python
  (`~/.local/share/uv/tools/canvas/bin/python`) — matches the claimed
  composition. The 8 new `TestV025PatientUnitContext` cases are real
  assertions (round-trip 1e-9, stray-literal grep, headline math, milestone
  labels, dual-unit disclosure, percent-only guard, basis wording).
- **Band geometry byte-identical (Task A claim):** the *independent* v0.2.4
  verification pack (`verification_v0.2.4/`, outside this repo) still passes
  25/25 against the v0.2.5 code — pinned mean/SD/bounds unchanged.
- **Completer sweep:** repo-wide `grep -i completer` clean; every remaining
  hit is a deliberate "NOT a completers analysis" explanation. The v0.2.4
  report was annotated ("*Corrected in v0.2.5*") rather than silently
  rewritten — good provenance.
- **One constant (B1):** `KG_PER_LB = 0.45359237` exact, `LB_PER_KG` derived;
  `_WEIGHT_TO_LBS` kg/g factors derive from it. Reviewer's own repo-wide grep
  (broader than the shipped test — includes `chart.html`/JS) found no stray
  conversion literals in product source.
- **Headline inputs verified at source (Gate 1):** `baseline_data` carries
  `value_lbs` (growth_charts.py ~line 972), so `build_headline` receives real
  patient data; signs consistent (negative = loss in both metrics).
  `_enrich_population_line` copies metadata (no module-constant mutation);
  `lbs_to_display` raises on unknown units instead of returning a wrong
  number.
- **Screenshots inspected at zoom** (extracted from the deploy report and
  cropped — not just counted):
  - Margaret Okafor (P1): headline exactly
    `-12.1% TBWL (-26.6 lb from 220 lb baseline)` (26.6/220 = 12.1%,
    internally consistent); milestone labels `5% — 209 lb / 10% — 198 lb /
    15% — 187 lb`; STEP-1 legend, no invented kg line.
  - Hector Ramirez (P4): B4 population line verbatim with the computed
    `18.5 lb` and "applied to their own baseline"; amber disclosure reads
    "full analysis set with LOCF imputation" — no "completers" in the
    rendered UI; milestones `5% — 247 lb / 10% — 234 lb` correct for the
    260 lb baseline; RAPID LOSS flag plausible at −1.25%/wk.
- **Hygiene:** manifest 0.2.5; after a fresh `git fetch`, 0 ahead / 0 behind
  `canvas-case/main`; deploy report has zero credential-pattern hits and zero
  external links (fully self-contained).

## Findings — v-next candidates (no action required at v0.2.5)

1. **Test-count claim off by one (reporting only).** The outcome said "9 new"
   tests; the v0.2.5 diff adds 8 test functions. "Was 124" also conflates
   commits: 124→129 happened in the preceding reference-fix commit
   (`e5cbfc2`); v0.2.5 proper took 129→137. The tests themselves are sound.
2. **B2 quietly narrowed.** Spec: "display unit = the patient's predominant
   recorded unit; default lb." Shipped: `DISPLAY_UNIT = "lb"` hardcoded,
   predominant-unit selection deferred. Disclosed in the code comment and
   rationale but not in the outcome summary. Structurally safe in this
   sandbox (pipeline normalizes everything to lb, so P8 kg/lb mixing is
   impossible by construction) — but implement predominant-unit selection
   before any deployment where kg-recording patients exist.
3. **Stray-literal test slightly weaker than spec'd.** It omits the spec's
   `2.2 ` token and scans only `growth_charts.py`, not the template/JS. A
   bare `2.2 *` in `chart.html` would slip through. One-line hardening:
   extend the scanned-file list and token set. (The frozen v0.1 suite's
   `2.20462` oracle literals are fine — deliberate per Gate 3, `places=2`
   absorbs the precision change.)
4. **P8 has no screenshot evidence.** The deploy report embeds screenshots
   for 2 of the 4 patients in the claimed 42/42 Tier-2 pass. P8 — the
   mixed-unit case, the one most likely to expose a kg/lb mixing bug — rests
   on the tier log plus the pipeline-level unit test. Acceptable here;
   close it out with a one-patient Tier-2 re-render of P8 in the next
   deploy's report.
5. **Cosmetic:** spec example strings use the Unicode minus (−); shipped
   strings use ASCII hyphen-minus. The UI is internally consistent; align
   only if a style pass happens anyway.

## Process notes worth keeping

- The build session's first-pass red was a test-regex bug (required a leading
  space before `8.4 kg`; the rendered text was byte-correct). Fixing the test
  rather than the product was the right call — a red check is sometimes the
  test, not the code; read the failure detail first.
- Reviewer initially cited the deploy-report screenshots as corroboration
  without opening them; on challenge, extracted and zoomed them (they held
  up, and certified more than credited). Rule: don't cite evidence you
  haven't actually inspected — counting images is not reviewing them.
