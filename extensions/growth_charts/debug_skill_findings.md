# Debug-Capture Skill Findings — v0.2 build

Running log of debug-capture tier usage during the cardiometabolic_tracker
v0.2.0 build (2026-06-09/10), per the spec's skill-evaluation goal. For each
tier: what was asked, whether the tier answered it, and friction.

## Tier 0 — deploy check
- **Asked:** is 0.2.0 installed and enabled after `canvas install`?
- **Answered:** yes, instantly — `cardiometabolic_tracker@0.2.0  enabled`.
- **Friction:** none. Exactly the right tool for the question.

## Tier 1 — quick look
- **Asked:** does P1 render after deploy; anything in plugin logs?
- **Answered:** render yes (folded into the first Tier-2 run — P1's pass
  doubles as the render sanity check; a separate one-sentence look would
  have duplicated a login cycle). Logs: quiet — no errors emitted.
- **Friction:** `DEBUG_TOOLING.md` shows `canvas logs pxbuilder-aomrani`,
  but the installed CLI (0.163.1) requires `canvas logs --host
  pxbuilder-aomrani`. Doc snippet corrected this session. Also: `canvas
  logs` streams forever — wrap with a background-kill pattern for
  scriptable use.

## Tier 2 — targeted assertions
- **Asked:** E1 milestone lines/labels (P1), E2 band + above-band placement
  (P2), E3 badges + velocity (P3/P4), unit normalization (P8); second run:
  regain (P5), sparse (P6), single (P7), dedup (P9).
- **Answered:** yes — 37/37 then 26/26. Two structural advantages found:
  1. The template's top-level layer objects (`MilestoneLayer._data`,
     `ExpectedBandLayer._data`, `StatsBar._data`) are readable from
     `frame.evaluate`, enabling exact numeric assertions (e.g., "patient
     239.9 > band top 238.9") instead of pixel heuristics.
  2. Content-based frame lookup (`#cm-container` across `page.frames()`)
     is robust to presentation-target changes.
- **Finding (addendum question):** after the switch to
  `RIGHT_CHART_PANE_LARGE`, the plugin STILL renders in an `about:srcdoc`
  iframe — existing Tier-2 selector guidance remains valid unchanged.
- **Friction:** the "no console errors" assertion needed two refinement
  passes to scope to plugin-attributable errors. The Canvas host page emits
  a CSP report-only warning plus analytics resource failures
  (`ERR_CONNECTION_REFUSED`, `NotSameOrigin`) on every page, plugin or not.
  Resolution: ignore host-page noise; fail only on pageerrors anywhere or
  resource failures from `about:srcdoc` / the d3 CDN. Worth adding to the
  skill's mode playbook as a documented noise allowlist.

## Tier 3 — focused investigation
- **Not used.** No Tier-2 check failed for plugin reasons. (The console
  noise iterations were test-harness scoping, not plugin defects — they did
  not warrant a mode session.)

## Tier 4 — full session (pre-submission, once)
- **Asked:** full capture on P1 + P8, read-only regression on Lori Collins /
  Samuel Alta / Jane Will, agent-handoff brief.
- **Answered:** yes — 32/32. Session
  `.workspace_state/debug/2026-06-10T05-48-48Z_full_v02_presubmission/` with
  network log (confirming the expected single GraphQL render POST per click
  and NO browser-level clinical-data calls — matches the server-side SDK
  data-access model), console log, screenshots, aria snapshots, page
  timings, `session.json`, `agent-handoff/brief.md` + `test_deploy.sh`.
- **Friction:** Figma upload steps in the skill are now dead weight for this
  project (removed from v0.2 scope) — the skill handled it fine as a skip,
  recorded in `session.json.figma.note`. `page.accessibility.snapshot()` is
  deprecated in Playwright 1.60; `locator.ariaSnapshot()` worked well as the
  replacement and is what the new scripts use.

## Tier 5 — new tooling
- Created under `.workspace_state/debug/tools/` (skill untouched, per the
  non-interference rule):
  - `tier2_v02_assertions.js` — login once, per-patient Tier-2 assertion
    runner driven by `seeded_patients.json`; exits non-zero on any failure.
  - `tier4_v02_full_session.js` — full-session capture producing
    schema-conformant artifacts; includes the regression fixtures.
  - `tier2_v02_output/` — Tier-2 results JSON + screenshots (Tier 2
    deliberately creates no session folder, per the tiering guide).

## Overall assessment
The tiering discipline held: 0→2 answered everything during iteration; 3 was
never needed; one 4 produced the durable record. The highest-leverage habits
this build confirmed: (a) make chart layer state introspectable from the
page — it turns visual checks into exact assertions; (b) drive test scripts
from the seeding manifest so live checks and seeded data can't drift; (c)
scope console-error assertions to attributable sources before calling
anything a failure.

## v0.2.2 hygiene patch (2026-06-10) — tier usage

- **Tier 0:** `canvas list` → `cardiometabolic_tracker@0.2.2  enabled`. Friction: none.
- **Tier 1:** logs tail clean (0 error lines) using the corrected
  `canvas logs --host` background-kill pattern from this doc; Margaret Okafor
  render confirmed as part of the Tier-2 run (same dedup of login cycles as
  v0.2.0 — a separate Tier-1 pass would only repeat the login).
- **Tier 2:** 23/23 via `tools/tier2_v02_assertions.js P1 P3 P9`. The point
  of this run was regression-pinning a refactor (single scaffold scale pass +
  config-driven pad constants): every value byte-identical to v0.2.1 —
  Sylvia Tran plateau badge / SURMOUNT-1 / −0.01%/wk, Carmen Delgado 3
  circles / −0.60%/wk, Margaret dashed=4 / crossed 5+10 / STEP-1.
  Reusable lesson: a selector-stable assertion script turns "the DOM must be
  identical after the refactor" from a claim into a 3-minute check.
- **Tiers 3–5:** not needed; no failures, no new tooling.

## Console-noise friction item — CLOSED (2026-06-10)

The v0.2 friction note above ("worth adding to the skill's mode playbook as a
documented noise allowlist") is now resolved: the debug-capture console-mode
playbook gained a required "plugin attribution" step — classify every console
entry by origin frame (`plugin` | `host` | `unknown`, recorded per entry in
`console_log.json`), assert only on plugin-attributable errors, route
ambiguous entries to the brief for human judgment. This is maintenance of an
existing mode (in-scope for the playbook file), not a new capability.

## v0.2.3 disclosure patch (2026-06-10) — tier usage

- **Tier 0:** `@0.2.3 enabled`.
- **Tier 2 (Gate 4 live smoke):** 32/32 via the extended
  `tier2_v02_assertions.js` on P1/P2/P4 — citation panel assertions added to
  the existing script per Gate 5 (extend, don't duplicate). Proven: SCALE
  legend carries "estimated" + amber disclosure + 2015;373 citation (P4);
  trial-derived bands unmarked with 2021;384 (P1); no-med fallback panel
  cites STEP 1 (P2). All previously pinned values unchanged.
- **Tiers 1/3–5:** Tier 1 folded into the Tier-2 run as before; no failures,
  no new tooling.

## SCALE synthesized-bounds item — CLOSED (2026-06-10, v0.2.4)

The v0.2.3 report's future item "published SCALE percentiles to replace the
synthesized 0.5×–1.5× bounds" is closed: the SCALE band now draws from the
published 56-week mean ± 1 SD (−8.0 ± 6.7%, LOCF, Pi-Sunyer 2015) instead of
mean ×0.5/×1.5, with linear interpolation to the 56-week anchors (no per-week
SDs published). `estimated_bounds` stays True with a changed meaning
(Gaussian ±1 SD approximation of a right-skewed distribution, not
fabrication); the legend reads "SCALE, ±1 SD". Residuals carried forward:
CDF responder anchors shipped data-only (marker rendering deferred per
Gate 5), and the reference file's kg-vs-% cell (8.4) still awaits
regeneration. Full decision record in `assumptions_tests_rationale.md` E2.

## v0.2.5 — patient-unit context + basis wording (2026-06-10)

- **Task A (copy fix):** repo-wide `grep -i completer` drove the correction —
  "trial completers" was wrong for an LOCF basis (LOCF includes dropouts via
  carried-forward values). Corrected source/docs/reference/report; the only
  remaining hits are the deliberate "NOT a completers analysis" explanations
  and a gitignored debug-output JSON that regenerates on the next run.
- **Tier 2 (Gate 4 live smoke):** extended the existing assertion script (Gate
  5 — extend, don't duplicate) for the new milestone label form, the
  dual-metric headline, the SCALE population dual-unit line, and the P8
  single-unit coherence check. Two existing assertions were re-synced to the
  changed label format — same pattern as the pytest re-syncs, since the spec
  moved the milestone label contract.
- **Reusable note:** a "no stray conversion literal" test must strip comments
  before grepping — prose that *cites* the constant value (e.g. "0.45359237 kg
  by definition") is not a stray literal. Caught on first run.

## v0.6.0 — Phase 1 per-point inspection panel (deploy + live Tier-2, 2026-06-24)

CLI deploy of the Web-merged build (`34fb6be5`) to `pxbuilder-aomrani`.
Registered `cardiometabolic_tracker@0.6.0 enabled`, no manifest/load error —
the deploy-critical intra-plugin import
`from cardiometabolic_tracker.protocols.provenance import …` loaded clean.

**Gate-1 field verification (SDK source on disk, 0.163.1 — definitive):**
- `Medication` exposes `start_date` / `end_date` (DateTimeField) — NOT
  `period_start`/`onset_date`/etc. `dose_at_time._PERIOD_*_ATTRS` already had
  them in the fallback list (worked), now reordered verified-first.
- `Medication` has NO `quantity`/`dose` field; the display dose is
  `clinical_quantity_description` (e.g. "Wegovy 0.5 mg/0.5 mL … pen injector"),
  with `erx_quantity` (float) / `potency_unit_code` also present. The shipped
  build's dose resolver (`getattr(med,"quantity") or getattr(med,"dose")`)
  always returned None → blank dose. **Fixed** (one line):
  `clinical_quantity_description` first, then the old candidates. Verified live
  (Margaret → Wegovy 0.5 mg, Sylvia → Zepbound 2.5 mg).
- `Note` exposes `provider` (FK) → care-team detection works (first in
  `_NOTE_AUTHOR_ATTRS`). NONE of `origin`/`source`/`entered_by_patient`/
  `patient_reported` exist; `NoteTypes` has no patient-portal/self-report type
  (closest: `data`/`ccda`, not reliable). So "Patient self-entered" has no
  reliable live signal in 0.163.x — left as honest "Care-team/Unknown source"
  fallback (per contract). All live fixtures classified "Care-team entry".

**Mock gate:** the merged build shipped with a RED pytest gate the Web
container couldn't run — 5 failures: 3 stale version pins (`PLUGIN_VERSION`
code constant left at 0.5.0 while manifest bumped to 0.6.0), 1 intentional
footer-hint copy change (added "double-click … to inspect it"), 1 guard-hook
test-isolation defect (persistent `block_<hash>.count` at n=13 → "REPEATED
BLOCK" not "BLOCKED"). Fixed: bumped the code constant, updated the two literal
pins + the verbatim copy, and isolated the guard counter per call via a fresh
`AGENT_CACHE_DIR` (engine already supports the env override). Gate now
**259 passed / 0 skipped / 0 failed** under the canvas uv python.

**Live Tier-2 (about:srcdoc, 3 fixtures — Alice/Bob/Jane placeholders are stale;
mapped to live patients):** Margaret Okafor (rich), Sylvia Tran (tirzepatide
past-point), Priya Raghunathan (single measurement, no med). All three: panel
opens on double-click of a `.cm-series circle`, shows all four rows
(Weight/Date/Data provenance/Dose at this date), closes with × and Esc; dose
degrades to "No dose on record" for the no-med patient; 0 plugin console
errors; Shift+D diagnostics + Export intact.
- **Reusable note:** Playwright `.dblclick()` on an SVG datapoint across the
  about:srcdoc boundary is unreliable; dispatch a native `MouseEvent('dblclick')`
  on `.cm-series circle` inside `frame.evaluate` (d3 reads the bound datum from
  `__data__`). Esc must be dispatched as a keydown INSIDE the iframe document,
  not via `page.keyboard` (the handler is on the iframe's `document`).
- **Untested live (honest gap):** "Unknown source"/"Patient self-entered"
  provenance branches (no patient-portal fixtures); strict "past dose ≠ today's
  dose" (no med-switch fixture seeded — all GLP-1 patients have one continuous
  period).
