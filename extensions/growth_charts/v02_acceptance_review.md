# v0.2 Independent Acceptance Review — cardiometabolic_tracker

Reviewer: independent verification session (oracle-based test pack, separate
from the implementation session). Date: 2026-06-10. Scope: v0.2.0 build
(`cd507c1`..`330ed13`) per the approved plan addendum (A1–A7, A3 scope change,
E4 polish, Figma removal).

## Verdict

**ACCEPTED at v0.2.0; two defects fixed immediately in v0.2.1** (this commit).
Zero implementation defects in the clinical math: every velocity, flag state,
milestone visibility, legend, and dedup value matched a spec-derived oracle
exactly across all nine seeded scenarios plus three regression patients.

Evidence (full detail in the verification pack, `verification_v0.2/` outside
this repo):

- Backend: implementer suite 107/107 (58 legacy tests byte-identical, sha
  `210bcf…`); independent oracle suite 54 pass / 1 deliberate skip — closed
  live by the SURMOUNT-1 legend check.
- Data safety: protected patients unchanged (Lori Collins 58 obs / 4 meds,
  Samuel Alta 92 obs / 1 med vs. pre-build snapshot); all nine demo patients
  verified by ID — renames, weight multisets, medication seeds (P1
  semaglutide / P3 tirzepatide / P4 liraglutide / others none).
- Live Tier 2: 12/12 surfaces, ~240 assertions. Key proofs: SURMOUNT-1 legend
  on Sylvia Tran (agent detection), STEP-1 on Derek Vance (no-med fallback),
  regain badge on Janelle Whitfield with plateau correctly absent, 3-circle
  average dedup on Carmen Delgado, unit normalization on Tobias Lindqvist,
  Samuel Alta still blocked, zero-data patient degrades gracefully.

## Findings — fixed in v0.2.1 (this commit)

1. **Timezone-mix TypeError class** (`protocols/growth_charts.py`). Mixing
   FHIR-created (tz-aware) and UI-created (naive) observation dates crashed
   four comparison sites: `dedupe_same_day`'s `min()`, the validator's
   `sorted(dates)` check, and `calculate_weeks_since_baseline`'s subtraction
   (the fourth was found by the new pipeline-level regression test, not by
   line review — write pipeline tests). Fix: module-level `_strip_tz` used as
   the key/operand for every date sort/min/delta. Three regression tests
   added in `tests/test_v02_enhancements.py` (110 total).
2. **StatsBar badge clipping** (`templates/chart.html`). `.cm-container` was
   fixed at 760px while the right-chart-pane viewport can be narrower
   (observed 575px) — the right-aligned badge column rendered off-screen, so
   flag explanation cards looked missing. Fix: fluid container
   (`max-width: 760px`) + `flex-wrap` on the StatsBar. Verified live: badge
   right edge now at 540px inside a 575px pane.

## Findings — recommended for v0.2.2 / v0.3 (not blocking)

3. `detect_glp1_agent` N+1: `med.codings.all()` per medication — add
   `prefetch_related("codings")` to the queryset.
4. Template: every layer's `render()` re-runs `ChartScaffold.render()`,
   rebuilding scales/axes/gridlines 4–5× per chart open. One scale pass after
   all layers set `_data` suffices.
5. `tools/` scripts duplicate `.env` loading, OAuth token fetch, and HTTP
   plumbing with diverging shapes — extract a shared helper module.
6. The axis-domain rule (pad = max(0.1·range, 2)) is dual-maintained in
   Python (`_axis_domain`) and JS (`ChartScaffold`) with no drift guard —
   ship the pad constants in `chart_config` so JS reads the server's values.
7. `GLP1_AGENT_KEYWORDS` and `EXPECTED_RESPONSE_BANDS` are coupled by
   identical string keys with silent STEP-1 fallback on mismatch — add a
   test asserting the key sets are equal.
8. `axis_weights` is hand-assembled at the `build_chart_data` call site;
   nothing enforces that everything plotted feeds the milestone-suppression
   domain. Consider a single collector the band/milestone/scaffold all share.

## Accepted deviations (documented, no action)

- Seeding used FHIR (fumage) endpoints for all writes (spec §3.4 said
  `/api/`); safety rests on the verified ZZTEST pre-write guard covering both
  Observation and MedicationStatement POSTs.
- The ZZTEST sort-to-bottom naming convention was retired by the demo-patient
  rename; scenario chart notes are now the test-data identifier. Future write
  scripts lose the "obviously test data" cue — keep the manifest-ID guard
  pattern (`tools/rename_and_annotate_patients.py`) for any new write tool.
- A2's server-side milestone suppression is intentionally conservative vs
  d3 `.nice()` (documented in `assumptions_tests_rationale.md`).
