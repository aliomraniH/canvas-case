# Assumptions, Tests & Rationale — cardiometabolic_tracker v0.2.0

Decision record for the v0.2 enhancements (E1 milestones, E2 expected band,
E3 velocity/flags, E4 presentation) plus the A-series decisions approved in
the v0.2 plan addendum. Companion docs: `glp1_science_reference.md` (trial
data), `debug_skill_findings.md` (live-validation tiering log),
`demo_patients.md` (v0.1 read-only fixtures).

---

## E1 — %TBWL milestone lines

**Computation** (`compute_milestone_lines`): weight at 5/10/15% TBWL =
`baseline_lbs × (1 − pct/100)`. Computed server-side in the Processing Layer
(approved A1 — the "client-side" wording in the spec was about avoiding new
SDK queries, which holds: milestones derive purely from the existing payload).

**Suppression rule** (approved A2): a milestone renders only when its weight
falls inside the y-domain the chart will use. The server mirrors the
template's axis rule exactly — `pad = max((hi − lo) × 0.1, 2)` over all
plotted weights (datapoints + baseline + expected-band edges, gathered by the
single `_collect_axis_weights` collector since v0.2.2). Milestones never
widen the axis. **Drift guard (v0.2.2, review finding 6):** the pad constants
(`AXIS_PAD_FRACTION` = 0.1, `AXIS_PAD_MIN_LBS` = 2.0) are defined once in
Python and shipped to the template via `chart_config.axis_pad_fraction` /
`axis_pad_min_lbs`; the JS scaffold reads them from there instead of
hardcoding, so the rendered domain cannot drift from `_axis_domain`'s
suppression decisions. This is deliberately conservative versus d3's
`.nice()`, which may round the rendered domain slightly outward: a milestone
sitting in the niced margin is suppressed even though it would technically
fit. Accepted trade-off for a single server-side source of truth.

**Consequences verified live:**
- P7 (single observation): degenerate domain (~±2 lb) → all milestones
  suppressed automatically; no special case in code.
- P2 (2.1% loss): the 15% line is suppressed, but 5% AND 10% render because
  the expected band legitimately stretches the axis down to ~215 lb. The
  spec's "5% line visible but uncrossed" holds; 10% visible is a superset.
- `crossed` reflects the LATEST TBWL, not the historical maximum: P5 (regain
  to 3.95%) shows its 5% line uncrossed even though it was crossed at week
  16. Flagged in the Tier-4 brief as a v0.3 styling decision.

## E2 — Expected-response band

**Table** (`EXPECTED_RESPONSE_BANDS`): static `(week, lower_pct, upper_pct)`
rows per agent; linear interpolation between rows; clipped to the patient's
observed week span so the band never stretches the x-axis; band absent with
fewer than 2 observations (zero observed span).

| Agent key | Label | Source |
|---|---|---|
| `semaglutide_step1` | STEP-1 | Wilding et al., NEJM 2021;384:989-1002 (semaglutide 2.4 mg arm, ~5th–95th pct) |
| `tirzepatide_surmount1` | SURMOUNT-1 | Jastreboff et al., NEJM 2022;387:205-216 (15 mg arm, ~5th–95th pct) |
| `liraglutide_scale` | SCALE | Pi-Sunyer et al., NEJM 2015;373:11-22 |

**SCALE approximation (superseded in v0.2.4, below):** the SCALE publication
tables in `glp1_science_reference.md` carry means only (4.2/6.4/7.8/8.4% at
weeks 12/24/40/56). Bounds were synthesized at mean×0.5 / mean×1.5 — the
relative spread the STEP-1 and SURMOUNT-1 percentile columns exhibit —
through v0.2.3.

**Band provenance disclosure (v0.2.3):** STEP-1 and SURMOUNT-1 bounds are
trial-derived; SCALE's are synthesized (mean ×0.5/×1.5). A clinician
previously could not tell the difference, so the disclosure now lives where
their eyes are: the SCALE legend reads "Expected response (SCALE, estimated)"
and every band carries an ⓘ panel ("About this reference band") with trial
name, one-line outcome summary, and the NEJM citation — SCALE's panel adds an
amber note that its band width is illustrative, not statistical. Citation
volume/page strings were verified against `glp1_science_reference.md` before
hardcoding (Gate 1; the file's hyphenated page ranges win over the prompt's
en dashes). Data-quality flag for v0.3: the reference file's SURMOUNT-1 table
(15 mg, 22.5% at wk 72) and SCALE table (8.4% at wk 56) differ from the
published primary-endpoint means quoted in the panel summaries (−20.9% by
dose at 72 wk; −8.0%/8.4 kg at 56 wk) — likely estimand and kg-vs-% mixups in
the reference tables. Band geometry was NOT changed in v0.2.3 (no-behavior-
change constraint); reconciling the tables is a v0.3 item.

**SCALE band replacement (v0.2.4):** the synthesized bounds (mean ×0.5/×1.5,
above) are retired. The band now draws from the published 56-week LOCF
distribution in Pi-Sunyer 2015 (NEJM 2015;373:11-22): mean −8.0%, SD 6.7
percentage points → −1.3% (mean + 1 SD, toward zero) to −14.7% (mean − 1 SD,
toward greater loss). Published dispersion replaces invented dispersion — the
band's width is now a trial statistic, not a ratio borrowed from other
trials' percentile columns. Three caveats, all stated in the new disclosure
copy: (1) weight-loss response is right-skewed, so a symmetric Gaussian
±1 SD band is an approximation — `estimated_bounds` therefore stays True for
SCALE, but its MEANING changes from "fabricated bounds" to
"imputation/normality basis"; the legend moves from "(SCALE, estimated)" to
"(SCALE, ±1 SD)" accordingly. (2) The basis is the full analysis set with
56-week LOCF imputation — NOT a completers analysis (LOCF carries dropouts'
last value forward, so it includes them; completers would exclude them).
(3) No per-week SDs were published, so intermediate
weeks linearly interpolate between week 0 and the 56-week anchors — the
mid-course band shape is a modeling choice, not data. The disclosure also
quotes the published responder rates (≥5% / >10% / >15% of body weight lost
by 63% / 33% / 14% of patients). Those three categorical CDF anchors
(5% → 63.2%, 10% → 33.1%, 15% → 14.4%) ship in SCALE metadata as DATA ONLY:
Gate 5 deferred marker rendering to v-next, so adding the markers later is a
rendering-only change against data already pinned here. Gate-1 finding:
`glp1_science_reference.md`'s SCALE table lists the 56-week mean as 8.4 in
the %TBWL column — that is the published KILOGRAM figure (−8.0% = 8.4 kg),
the kg-vs-% transcription error already flagged in the v0.2.3 passage above.
v0.2.4 ships the published −8.0%; the reference file carries a
do-not-edit-manually header, so regenerating it remains a v-next item.

**SCALE reference correction (2026-06-10, post-v0.2.4, no version bump):** the
v-next item above is now RESOLVED. Adjudication: 8.4 is the published
**kilogram** change (−8.4 kg), not a percent — the reference had put the kg
value under a "Mean % TBWL" header (the 12/24/40-wk cells, 4.2/6.4/7.8,
already matched the published *percent* trajectory, so only the 56-wk cell was
mislabeled). The authority is the paper (Pi-Sunyer 2015), not the code or the
reference — both are caches of it, so "code matches reference" would be
circular. We corrected the **reference**, not the code: the band already
shipped the correct −8.0% / SD 6.7 / CDF anchors in v0.2.4, so no plugin code
or behavior changed (verified: empty `git diff` over the plugin package, no
version bump, no deploy). The do-not-edit file has no generator script
("regenerate from session" = an LLM session), so the fix was an explicit
logged un-freeze → correct → re-freeze recorded in the file header: 56-wk %
cell → 8.0, a `Mean change (kg)` column preserves the 8.4 datum, and the SD +
CDF rows the band actually uses were added, each inline-cited to NEJM
2015;373:11–22. **Tripwire:** `TestGate1ReferenceConcordance` now pins the
corrected state (code's SCALE numbers == the reference's == the paper's) — it
trips if the reference regresses or the code's SCALE figures drift from it.
(The plan framed this as "inverting" a prior disagreement-tripwire, but no
such test existed — the v0.2.4 kg-vs-% issue lived only in a commit note, this
rationale, and a code comment; reported and created fresh instead.) The code's
kg-vs-% explanatory comment in `EXPECTED_RESPONSE_BANDS` is kept — it still
documents why 8.4 ≠ −8.0. Remaining v-next: file-wide citation retrofit (only
the SCALE rows are inline-cited so far) and the SURMOUNT-1 estimand
discrepancy noted above.

**Weight-space inversion:** `upper_pct` (more loss) maps to the LOWER weight
on screen. The band's visual top edge is `lower_pct`'s weight. The P2
"patient above band" assertion is therefore `last_weight > lower_lbs(last)`.

**Agent selection (A3, scope-changed into v0.2):**
`detect_glp1_agent(patient_id)` queries
`Medication.objects.for_patient(id).active()` (committed, not
entered-in-error, status=active — verified against canvas_sdk 0.163.1 source
AND docs.canvasmedical.com/sdk/data-medication/ before coding, per the
addendum's doc-verification requirement) and substring-matches coding
`display` text against generic + brand keywords (semaglutide/Wegovy/Ozempic;
tirzepatide/Zepbound/Mounjaro; liraglutide/Saxenda/Victoza). Exactly one
agent matched → that band. No match, multiple matches, or ANY exception →
`semaglutide_step1` default with the fallback reason logged. The broad
except is a deliberate addendum requirement (schema surprises must degrade,
never crash the chart) and is scoped to this one lookup.

**Live finding:** FHIR-created MedicationStatements DO surface in the SDK
`Medication` model — P1 (Wegovy) → STEP-1, P3 (Zepbound) → SURMOUNT-1,
P4 (Saxenda) → SCALE, P2 (none) → STEP-1 fallback, all proven in Tier 2.

## E3 — Velocity and flags

**Velocity** (`compute_velocity`): TBWL at `last_date − 28d` is linearly
interpolated between the bracketing observations (irregular spacing handled);
velocity = ΔTBWL/Δweeks over that window. Requires ≥2 observations spanning
≥14 days, else `None` → displayed `—`. **Display sign:** internal TBWL is
positive-for-loss; the displayed velocity negates it (loss reads
`-0.19%/wk`), matching the spec mock. P6 (two obs, 90 days apart) QUALIFIES
under the ≥14-day rule and shows the interpolated linear rate (−0.21%/wk),
per the approved plan (A4).

**Flags** (`detect_flags`) — informational decision support, descriptive
copy only, evaluated only when the velocity data-quality rule is met:

| Flag | Trigger | Note |
|---|---|---|
| Plateau (amber) | last obs > week 8 AND \|ΔTBWL\| < 0.5 over trailing 8 wk | The ABSOLUTE-value test is the load-bearing choice: a literal "<0.5% loss" reading would fire on regain. |
| Regain (amber, A5 addition) | last obs > week 8 AND ΔTBWL ≤ −0.5 over trailing 8 wk | Added in v0.2 per addendum; P5 is its positive fixture. Mutually exclusive with plateau by construction. |
| Rapid loss (red) | trailing 4-week velocity > 1.0 %TBWL/wk | The rolling 4-week average IS the "sustained" test — a single-interval spike inside a longer flat window won't exceed it. |

Shape verification (pytest + live): P3 fires plateau (Δ8wk ≈ 0.13%); P2 does
NOT (Δ8wk ≈ 1.27% — the magnitude rule, not the week-8 gate, is what spares
it at week 14); P5 fires regain only; P4 fires rapid (1.25%/wk) ; P1 fires
nothing; a flat series before week 8 fires nothing.

## A6 — Same-day dedup

Same-calendar-day observations are **averaged** (in lbs; mixed-unit days are
converted first and emitted as a synthetic `lbs` record carrying
`deduped_from` provenance). Chosen over latest-wins because Observation ids
are UUIDs and same-day entries can share a `datetime_of_service`, leaving
"latest" with no deterministic tie-break; averaging is order-independent and
damps re-measurement noise. P9: (247.0, 246.4) → one 246.7 point; 3 rendered
points from 4 observations; velocity unaffected (verified live).

The v0.1 baseline tie-break (higher value on a tied earliest date) is now
vestigial in the pipeline — dedup leaves at most one observation per day —
but is retained for direct `compute_baseline()` callers.

## E4 — Presentation

- Launch target switched to `LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE`
  (title "Weight Trajectory"); the error pane uses the same target. **Live
  finding:** plugin content still renders in an `about:srcdoc` iframe, so all
  existing DEBUG_TOOLING selectors remain valid.
- Fixed z-order via scaffold-owned layer groups (band < baseline < milestones
  < series < annotation < tooltip) — refresh order can no longer change
  stacking.
- StatsBar above the chart: large velocity figure, muted small-caps label,
  right-aligned badges (plateau/regain amber, rapid red) with descriptive
  message lines.
- Designed degraded states: single-measurement note (P7), sparse-data note
  (P6: n=2, or mean gap > 30 days), zero-data error pane (unchanged v0.1
  path).
- Draw-in animation runs once after the final refresh pass (a path dash
  trick; attributes removed on completion). Gridlines are plain `line`
  elements WITHOUT dasharray, so the Tier-2 `line[stroke-dasharray]`
  selector still counts exactly baseline + milestones.
- Validation: the four v0.2 payload keys are shape-checked only when present,
  so legacy payloads (and the byte-untouched v0.1 test suite) stay valid;
  `build_chart_data` always emits them, asserted by the v0.2 tests.

## Out of scope — v0.3 candidates

Dose-titration markers from medication records; non-responder week-12
banner; BMI transition markers; trend extrapolation; mid-series agent-change
band handling; published SCALE percentiles; milestone styling for
historically-crossed-then-regained thresholds.

## Test inventory

- `tests/test_cardiometabolic.py` — 58 v0.1 tests, byte-untouched (A7).
- `tests/test_v02_enhancements.py` — 49 new tests: milestones (6), band (7),
  agent detection incl. error fallback (8), velocity (7), flags (8),
  dedup (4), mixed units (1), payload/validation/context (8).
- Live: Tier 2 — 37/37 (P1–P4, P8) + 26/26 (P5–P7, P9); Tier 4 — 32/32
  (P1, P8, Lori Collins, Samuel Alta, Jane Will). Mocked tests cannot catch
  SDK field-name drift (the v0.1 `obs.unit` lesson) — live validation is the
  second gate, and it ran against every seeded shape.

## Seeding notes

`tools/seed_zztest_patients.py` — FHIR API on the fumage host (the
v0.1-verified path; the legacy `/api/...` host endpoints are not used).
Pre-write guard: every Observation and MedicationStatement POST requires the
target patient id to have been returned by a Patient create IN THIS RUN and
read-back-verified to carry the `ZZTEST-GLP1` family-name prefix; any guard
failure aborts the run. Re-runs create new patients (run-tagged given name);
nothing pre-existing is ever written to. Two schema lessons cost one aborted
run each: Patient create requires the us-core-birthsex extension, and weight
observations must use unit `lb` (not `lbs`). One empty ZZTEST patient from
the aborted runs remains on the sandbox (harmless, sorts to bottom).

**Post-sign-off rename (2026-06-10):** the ZZTEST-GLP1 role names were hard
to distinguish in patient lists, so `tools/rename_and_annotate_patients.py`
renamed the nine patients to distinct realistic names and attached one
"Office visit" note per chart whose title describes the scenario (name →
scenario table in `demo_patients.md`). Patient ids, observations, and
medication records were untouched — FHIR Patient PUT is permitted on this
sandbox even though Observation PUT/DELETE is blocked. Its write guard:
targets only ids from the seeding manifest, and the read-back must show
either the ZZTEST-GLP1 family name or the already-applied target name. All
nine patients re-verified post-rename: 63/63 Tier-2 assertions passed with
chart values identical to the pre-rename runs (the added empty notes carry
no observations, so chart data is unaffected).
