# Phase 1 — Deploy Checklist (Web build → CLI hand-off)

**Plugin:** `cardiometabolic_tracker` (pkg dir `growth_charts/`)
**Version:** 0.5.0 → **0.6.0**
**Phase:** 1 — Per-Point Inspection Panel (READ-ONLY; no writes anywhere)
**Built by:** Web session (spec + code + tests + this checklist). **Deploy + live Tier 2 = CLI.**

---

## What shipped in this phase

| Area | File | Change |
|---|---|---|
| Provenance (1a) | `protocols/provenance.py` *(new)* | Pure `derive_provenance(obs, note, metadata)` → one of *Automatic scale / Patient self-entered / Care-team entry / Unknown source* |
| Dose-at-time (1b) | `protocols/dose_at_time.py` *(new)* | `load_glp1_medication_periods()` (bulk, 1 query) + pure `dose_covering_date()` (covers / before / gap / overlapping→most-recent) |
| Wiring | `protocols/growth_charts.py` | Additive `build_point_inspection()`; loads med periods once, resolves per datapoint (no N+1); new top-level context key `point_inspection` |
| Panel (1c) | `templates/chart.html` | `PointInspectionPanel` JS component + `dblclick` on datapoint dots; reads `chartData.point_inspection`; read-only, no save |
| Manifest | `CANVAS_MANIFEST.json` | `plugin_version` → `0.6.0` (no class/path change; `Medication` already in `read`) |
| Tests | `tests/test_phase1_provenance.py`, `tests/test_phase1_dose.py` *(new)* | 20 behavior tests, all pure (run without SDK) |

**Degrades gracefully:** if the medication load fails or returns nothing, the panel
shows "No dose on record" and still renders provenance + value/date. If
`point_inspection` is absent entirely, the panel falls back to the datapoint's own
value/date. Phases 2–4 are independent of this.

---

## Gate status (from the Web build)

- **field_names** (`0.163.x`): **CLEAN** on both new modules. They use neither
  `obs.units` nor `dbid__in`, so the two waived rules below don't even apply here.
- **sandbox_imports** (`0.163.x`): **1 genuine issue fixed** — removed an
  `import logging` + `__name__` from `dose_at_time.py` (really sandbox-illegal).
  The remaining linter rejections are **false-positives contradicted by deployed
  live code** — see "Linter divergences" below.
- **fhir_immutability:** N/A — Phase 1 performs **no writes**.
- **pytest (mock gate):** the 20 new Phase 1 tests pass under plain `unittest`.
  ⚠️ The pre-existing SDK-dependent suite cannot fully run in the Web container
  (no `canvas[test-utils]`, no `pytest`): `251 collected / 227 skipped / 2 errors`,
  both errors environmental (`test_guard_hook` imports `pytest`; `test_v02` reads
  an SDK-guarded symbol) — **not** caused by Phase 1. **CLI must run the full
  `pytest` mock gate green before deploy.**

### Linter divergences (deployed-code wins; documented per Bundle A)
The `canvas-sdk-tools` linters run a stricter-than-Canvas RestrictedPython and
flag patterns the **live, deployed** codebase uses and runs. Treated as
false-positives, with proof:

1. **`obs.units` / `dbid__in`** flagged → *keep*. Deployed `growth_charts.py:610,707`
   uses both; Gate-1 known-facts confirm them for 0.163.1. (Not used by the new
   Phase 1 modules anyway.)
2. **Single-underscore names** flagged (`_helper`, `_CONST`) → *keep*. Deployed
   `assistant` ships `_SPEC_COUNT_PATIENTS`; `growth_charts.py` ships `_now_iso`
   etc. The real Canvas runtime allows them.
3. **Intra-plugin imports** (`from cardiometabolic_tracker.protocols.X import`)
   flagged "not in ALLOWED_MODULES" → *keep*. Deployed `assistant`
   (`from assistant.chat_tools_lib import …`) and `clinical_pathways`
   (`from clinical_pathways.handlers import …`) use exactly this pattern live.

> The sandbox gate still earned its keep this phase: it caught the genuine
> `logging`/`__name__` bug and forced the import fix from a (zero-precedent)
> relative import to the deployed-proven absolute form.

---

## CLI live-verify items (MUST confirm before trusting output)

These were written against documented/candidate field paths the Web container
could not verify (no SDK installed). Each is centralized for a one-line fix.

1. **Medication coverage-period fields** — `dose_at_time.py:_PERIOD_START_ATTRS /
   _PERIOD_END_ATTRS`. Confirm which (if any) of
   `period_start/start_date/effective_start/onset_date` (and the `*_end` set) the
   live 0.163.x `Medication` model exposes. Until confirmed, periods resolve
   open-ended (→ "current dose" behavior). The deployed code historically avoided
   effective dates (seeded-data unreliability) — verify on a real GLP-1 patient.
2. **Note provenance fields** — `provenance.py:_NOTE_AUTHOR_ATTRS /
   _NOTE_ORIGIN_ATTRS`. Confirm the live `Note` exposes an author/provider and an
   origin/type signal. Until confirmed, most points classify "Unknown source"
   (the honest fallback — not a bug).
3. **Patient fixtures** — the build spec's Tier-2 list names **Carol Singh**, which
   Gate-1 marks **stale**. Use the no-data patient **Jane Will**
   (`53e062d0dc5249eb9309cb900754a050`) where a no-data case is needed; confirm
   the live names for Alice Reyes / Bob Harmon.

---

## Install steps (CLI)

1. `canvas install extensions/growth_charts` against `pxbuilder-aomrani.canvasmedical.com`.
2. Confirm version `0.6.0` registered; no manifest/load errors.

## Tier-2 browser checks (CLI, per debug-capture)

Open the **Weight Trajectory** chart for each fixture and:

- [ ] **Alice Reyes** — chart renders; **double-click** a datapoint dot → panel opens
      showing Weight (`lb`), Date, Data provenance, Dose at this date. Close with ×
      and with **Esc**.
- [ ] **Bob Harmon** — same; verify a point on a **past** date shows the dose in
      effect *then* (not today's), assuming live-verify item 1 confirms periods.
- [ ] **Carol Singh → use Jane Will** if a no-/sparse-data case: confirm the panel
      degrades (value/date present, "No dose on record", provenance "Unknown source")
      rather than erroring.
- [ ] Existing behavior intact: hover tooltip, `Shift+D` diagnostics, Export — all
      unchanged (Phase 1 is additive).
- [ ] No new console/plugin errors in the `about:srcdoc` iframe.

Capture findings to `debug_skill_findings.md` (tiered). On deploy close, emit the
versioned HTML report to `extensions/deploy_reports/` per the `deploy-report` skill.
