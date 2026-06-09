# Demo Patients — cardiometabolic_tracker Test Data
# Created: 2026-06-05 via Canvas FHIR API (fumage-pxbuilder-aomrani.canvasmedical.com)
# Instance: pxbuilder-aomrani.canvasmedical.com

---

## DEMO PATIENT 1 — Good Responder (TC-01, TC-02, TC-03, TC-06)
**Name:** Lori Collins
**Patient Key:** `0af123e5cc74483095399463fff6f002`
**Chart URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/0af123e5cc74483095399463fff6f002
**Vitals URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/0af123e5cc74483095399463fff6f002/chart/vitals
**Scenario:** Semaglutide good responder — early responder at week 12 (>5% TBWL)

| Date       | Weight (lbs) | TBWL %  | Clinical note            |
|------------|-------------|---------|--------------------------|
| 2025-08-01 | 248.0       | 0.0%    | **Baseline** (visit 1)   |
| 2025-09-01 | 243.5       | 1.8%    | Week 4                   |
| 2025-10-01 | 238.0       | 4.0%    | Week 8                   |
| 2025-11-01 | 231.5       | 6.7%    | Week 12 — ✅ Early responder (≥5%) |
| 2025-12-01 | 225.0       | 9.3%    | Week 16                  |
| 2026-01-01 | 218.0       | 12.1%   | Week 20 (latest)         |

**What to verify on this patient:**
- TC-01: Modal opens, SVG present, X-axis shows "Aug 2025" → "Jan 2026"
- TC-02: Dashed baseline line at 248 lbs
- TC-03: Annotation reads ~12.1% TBWL at Jan 2026 data point
- TC-06: `window.refreshAll()` re-renders cleanly

---

## DEMO PATIENT 2 — Non-Responder / TC-08 Zero-Data Edge Case
**Name:** Jane Will
**Patient Key:** `53e062d0dc5249eb9309cb900754a050`
**Chart URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/53e062d0dc5249eb9309cb900754a050
**Vitals URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/53e062d0dc5249eb9309cb900754a050/chart/vitals
**Scenario:** Zero weight observations — tests TC-08 (graceful error state)

| Date | Weight | Notes |
|------|--------|-------|
| —    | —      | No weight observations recorded |

**What to verify on this patient:**
- TC-08: Click plugin button → graceful error banner shown ("No weight data available" or similar)
- Must NOT show blank modal, Python traceback, or spinner
- validate_chart_payload() intercepts and returns EffectErrorBanner

---

## DEMO PATIENT 3 — Minimal Responder
**Name:** Maria GLP1 Demo
**Patient Key:** `9ea44c99abed47679e345e397623911b`
**Chart URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/9ea44c99abed47679e345e397623911b
**Vitals URL:** https://pxbuilder-aomrani.canvasmedical.com/patient/9ea44c99abed47679e345e397623911b/chart/vitals
**Scenario:** Slow/non-responder — only 1.5% TBWL at week 12 (below 5% threshold)

| Date       | Weight (lbs) | TBWL %  | Clinical note              |
|------------|-------------|---------|----------------------------|
| 2025-09-15 | 218.0       | 0.0%    | **Baseline** (visit 1)     |
| 2025-10-15 | 217.0       | 0.5%    | Week 4                     |
| 2025-11-15 | 215.5       | 1.1%    | Week 8                     |
| 2025-12-15 | 214.8       | 1.5%    | Week 12 — ⚠️ NOT early responder (<5%) |
| 2026-01-15 | 214.0       | 1.8%    | Week 16 (latest)           |

**What to verify on this patient:**
- Chart renders without errors (validation passes — 1.8% TBWL is within [-20, 50])
- Annotation shows ~1.8% TBWL at Jan 2026 data point
- Baseline dashed line at 218 lbs
- Chart demonstrates contrast vs. Lori Collins (good responder)

---

## Test Coverage Map

| TC ID | Patient to use           | Verification tool |
|-------|--------------------------|-------------------|
| TC-01 | Lori Collins             | Chrome connector  |
| TC-02 | Lori Collins             | Chrome + console  |
| TC-03 | Lori Collins             | Chrome + console  |
| TC-04 | Any deployed patient     | Chrome visual     |
| TC-05 | Code review (Python)     | Bash grep + pytest|
| TC-06 | Lori Collins             | Chrome console    |
| TC-07 | Code review (Python)     | Bash grep + pytest|
| TC-08 | Jane Will (0 obs)        | Chrome connector  |
| TC-09 | Lori Collins             | Chrome (Shift+D)  |
| TC-10 | Pytest only              | pytest suite      |

---

## FHIR API Reference (used to create this data)

```bash
# Auth token
TOKEN=$(curl -s -X POST "https://pxbuilder-aomrani.canvasmedical.com/auth/token/" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=1FAe5bKiy1LcwXrQ7OlI3iSXEIDStznv9QHirewL&client_secret=..." \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

# Create one weight observation (requires 2 calls: panel + weight)
# Step 1: POST /Observation  →  Vital Signs Panel (85353-1)
# Step 2: POST /Observation  →  Weight (29463-7) with derivedFrom pointing to Step 1
# FHIR base URL: https://fumage-pxbuilder-aomrani.canvasmedical.com
```

---

## Notes on Samuel Alta (41fb2a51a18d4948afb9d874a7a2adcb)
- Has contaminated data: pre-existing 160 lb obs (Aug 2025) + accidentally added 262+ lb obs
- TBWL from 160 → 262 = -63.8% (outside [-20, 50] range)
- Plugin will show EffectErrorBanner for this patient
- Use as unplanned "validation failure" test case if needed
- Do NOT use as a primary demo patient
