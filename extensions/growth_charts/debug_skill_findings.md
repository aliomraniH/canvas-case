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
