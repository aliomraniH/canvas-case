# GLP-1 Weight Management Science Reference
# For cardiometabolic_tracker Canvas Plugin
# Created: companion session — do not edit manually; regenerate from session

---

## Purpose

This document provides the scientific foundation for weight projection in the
cardiometabolic tracker. All benchmark trajectories are derived from published
Phase 3 clinical trials. This data is used to:
1. Draw expected-trajectory reference lines on the chart
2. Classify patients as "early responders" at week 12
3. Contextualize observed weight loss vs. published benchmarks
4. Power the program template data structure doctors select from

---

## Published Trial Data

### Semaglutide 2.4 mg/week (Ozempic / Wegovy)
**Source:** Wilding JPH et al. "Once-Weekly Semaglutide in Adults with Overweight or Obesity."
NEJM 2021;384:989-1002 (STEP 1 trial).

**Trial design:** 1961 adults without T2DM, BMI ≥30 (or ≥27 + comorbidity),
68-week duration, 2.4mg SC weekly vs placebo.

**Primary endpoint TBWL (semaglutide arm):**
| Week | Mean % TBWL | 5th–95th percentile range (approx) |
|------|------------|-------------------------------------|
| 4    | 2.0        | 0.5 – 4.5                          |
| 8    | 3.5        | 1.0 – 7.0                          |
| 12   | 6.0        | 2.0 – 11.0   ← early-response checkpoint |
| 16   | 7.8        | 3.0 – 13.5                         |
| 20   | 9.2        | 4.0 – 15.0                         |
| 24   | 10.6       | 5.0 – 16.5                         |
| 36   | 12.5       | 6.0 – 19.0                         |
| 52   | 14.1       | 7.0 – 21.0                         |
| 68   | 14.9       | 7.5 – 22.0   ← trial endpoint      |

**STEP 4 note (Rubino et al. NEJM 2021):** Patients who discontinued semaglutide
regained ~2/3 of lost weight within 1 year — discontinuation must be tracked.

---

### Tirzepatide (Mounjaro / Zepbound) — GIP/GLP-1 dual agonist
**Source:** Jastreboff AM et al. "Tirzepatide Once Weekly for the Treatment of Obesity."
NEJM 2022;387:205-216 (SURMOUNT-1 trial).

**Trial design:** 2539 adults without T2DM, BMI ≥30 (or ≥27 + comorbidity),
72-week duration, doses 5mg / 10mg / 15mg SC weekly.

**Primary endpoint TBWL (15mg arm — highest dose):**
| Week | Mean % TBWL | 5th–95th percentile range (approx) |
|------|------------|-------------------------------------|
| 4    | 2.8        | 0.8 – 5.5                          |
| 8    | 5.5        | 2.0 – 10.0                         |
| 12   | 8.5        | 3.5 – 14.5   ← early-response checkpoint |
| 16   | 11.5       | 5.0 – 18.0                         |
| 24   | 15.0       | 8.0 – 22.0                         |
| 36   | 18.5       | 10.0 – 26.0                        |
| 52   | 20.5       | 12.0 – 28.5                        |
| 72   | 22.5       | 13.0 – 31.0  ← trial endpoint      |

**SURMOUNT-2 note (Garvey et al. NEJM 2023):** In T2DM patients, tirzepatide
produces ~15% TBWL at 52 weeks vs ~22.5% in non-T2DM — adjust benchmarks
if patient has T2DM.

---

### Liraglutide 3.0 mg/day (Saxenda) — GLP-1 agonist
**Source:** Pi-Sunyer X et al. "A Randomized, Controlled Trial of 3.0 mg of Liraglutide
in Weight Management." NEJM 2015;373:11-22 (SCALE trial).

**Trial design:** 3731 adults without T2DM, BMI ≥30, 56-week duration.

**Primary endpoint TBWL (liraglutide arm):**
| Week | Mean % TBWL |
|------|------------|
| 12   | 4.2        |
| 24   | 6.4        |
| 40   | 7.8        |
| 56   | 8.4        |

---

## Key Clinical Rules Encoded in the Plugin

### Rule 1: Early Response Threshold (Week 12)
```
≥5% TBWL at week 12 → "early responder" → continue medication
<5% TBWL at week 12 → consider dose escalation or discontinuation
```
Reference: AACE/ACE guidelines; consistent across STEP and SURMOUNT trials.
The chart should annotate the week-12 point if data is available.

### Rule 2: TBWL Formula
```
% TBWL = ((baseline_weight_lbs - current_weight_lbs) / baseline_weight_lbs) × 100
```
- Positive value = weight lost (good)
- Negative value = weight gained
- baseline = FIRST weight observation (sorted ascending by datetime_of_service)

### Rule 3: T2DM Adjustment
When `has_type2_diabetes = True`, reduce expected trajectory by ~25%:
```python
adjusted_tbwl = expected_tbwl * (0.75 if has_type2_diabetes else 1.0)
```
(Approximate — based on SURMOUNT-2 vs SURMOUNT-1 comparison)

### Rule 4: Discontinuation Detection
If >12 weeks pass with no new weight observation and last TBWL > 5%, consider
flagging as "possible discontinuation — verify medication adherence."

---

## Patient Data Model

### PatientBaseline — immutable snapshot at enrollment
```python
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

@dataclass(frozen=True)   # frozen=True → immutable after creation
class PatientBaseline:
    """
    Created once at enrollment. NEVER updated.
    If baseline changes (e.g., wrong value entered), create a new record
    with a correction_note, keep the old one.
    """
    patient_id: str
    baseline_weight_lbs: float         # from first observation
    baseline_weight_source_id: str     # Observation.id this came from
    baseline_date: date                # datetime_of_service of first obs
    baseline_bmi: Optional[float]      # computed from height + weight if available
    enrolled_at: datetime              # when this record was created
    enrolled_by: str                   # user who triggered enrollment
```

### PatientEnrollment — links patient to a program template
```python
@dataclass
class PatientEnrollment:
    patient_id: str
    program_template_id: str           # key into PROGRAM_TEMPLATES dict
    medication_name: str               # actual prescribed medication
    medication_start_date: date
    baseline: PatientBaseline          # immutable snapshot

    # Patient factors for trajectory modeling
    age_at_enrollment: int
    sex_at_birth: Optional[str]        # 'M' | 'F' | None — not used for sex stratification
    has_type2_diabetes: bool
    baseline_hba1c: Optional[float]

    # Program tracking
    is_active: bool = True
    discontinued_date: Optional[date] = None
    discontinuation_reason: Optional[str] = None
```

### WeightObservationRaw — what Canvas SDK returned (never modified)
```python
@dataclass(frozen=True)   # immutable
class WeightObservationRaw:
    observation_id: str
    canvas_note_id: str
    datetime_of_service: datetime      # from Note — this is the X-axis value
    value_original: float              # as stored in Canvas
    unit_original: str                 # "oz", "kg", "lbs" — as stored
    loaded_at: str                     # datetime.now().isoformat() at load time
```

### WeightObservationProcessed — derived, recomputable
```python
@dataclass
class WeightObservationProcessed:
    observation_id: str                # FK to WeightObservationRaw
    value_lbs: float                   # converted from raw
    date_label: str                    # formatted "MMM YYYY" for chart X-axis
    date_obj: datetime                 # for sorting and week calculation
    weeks_since_baseline: float        # for benchmark comparison
    tbwl_pct: float                    # % TBWL at this point
    processed_at: str                  # datetime.now().isoformat()
    processing_version: str            # bump when conversion logic changes
```

---

## Program Templates (Doctor-Selectable)

```python
PROGRAM_TEMPLATES = {
    "semaglutide_standard": {
        "display_name": "Semaglutide Standard Protocol",
        "medication": "semaglutide",
        "benchmark_source": "STEP-1 (Wilding JPH, NEJM 2021)",
        "benchmark_population": "Adults without T2DM, BMI ≥30",
        "expected_tbwl_by_week": {
            4: 2.0, 8: 3.5, 12: 6.0, 16: 7.8,
            20: 9.2, 24: 10.6, 36: 12.5, 52: 14.1, 68: 14.9
        },
        "early_responder_threshold_week12_pct": 5.0,
        "response_check_weeks": [4, 12, 24, 52],
        "t2dm_trajectory_adjustment_factor": 0.85,
        "dose_schedule": [
            {"weeks": "1–4",  "dose_mg_weekly": 0.25, "route": "SC"},
            {"weeks": "5–8",  "dose_mg_weekly": 0.5,  "route": "SC"},
            {"weeks": "9–12", "dose_mg_weekly": 1.0,  "route": "SC"},
            {"weeks": "13+",  "dose_mg_weekly": 2.4,  "route": "SC"},
        ],
        "monitoring_frequency_weeks": 4,
    },

    "tirzepatide_standard": {
        "display_name": "Tirzepatide Standard Protocol",
        "medication": "tirzepatide",
        "benchmark_source": "SURMOUNT-1 (Jastreboff AM, NEJM 2022)",
        "benchmark_population": "Adults without T2DM, BMI ≥30",
        "expected_tbwl_by_week": {
            4: 2.8, 8: 5.5, 12: 8.5, 16: 11.5,
            24: 15.0, 36: 18.5, 52: 20.5, 72: 22.5
        },
        "early_responder_threshold_week12_pct": 5.0,
        "response_check_weeks": [4, 12, 24, 52],
        "t2dm_trajectory_adjustment_factor": 0.75,   # SURMOUNT-2 shows ~25% less in T2DM
        "dose_schedule": [
            {"weeks": "1–4",   "dose_mg_weekly": 2.5,  "route": "SC"},
            {"weeks": "5–8",   "dose_mg_weekly": 5.0,  "route": "SC"},
            {"weeks": "9–12",  "dose_mg_weekly": 7.5,  "route": "SC"},
            {"weeks": "13–16", "dose_mg_weekly": 10.0, "route": "SC"},
            {"weeks": "17+",   "dose_mg_weekly": 15.0, "route": "SC"},
        ],
        "monitoring_frequency_weeks": 4,
    },

    "liraglutide_standard": {
        "display_name": "Liraglutide Standard Protocol",
        "medication": "liraglutide",
        "benchmark_source": "SCALE (Pi-Sunyer X, NEJM 2015)",
        "benchmark_population": "Adults without T2DM, BMI ≥30",
        "expected_tbwl_by_week": {
            12: 4.2, 24: 6.4, 40: 7.8, 56: 8.4
        },
        "early_responder_threshold_week12_pct": 4.0,  # Lower bar for liraglutide
        "response_check_weeks": [12, 24, 56],
        "t2dm_trajectory_adjustment_factor": 0.80,
        "dose_schedule": [
            {"weeks": "1",  "dose_mg_daily": 0.6, "route": "SC"},
            {"weeks": "2",  "dose_mg_daily": 1.2, "route": "SC"},
            {"weeks": "3",  "dose_mg_daily": 1.8, "route": "SC"},
            {"weeks": "4",  "dose_mg_daily": 2.4, "route": "SC"},
            {"weeks": "5+", "dose_mg_daily": 3.0, "route": "SC"},
        ],
        "monitoring_frequency_weeks": 4,
    },

    "custom": {
        "display_name": "Custom Program",
        "medication": None,                  # Doctor specifies
        "benchmark_source": None,            # No benchmark overlay shown
        "benchmark_population": None,
        "expected_tbwl_by_week": {},         # Empty → no expected line drawn
        "early_responder_threshold_week12_pct": 5.0,   # Clinical standard default
        "response_check_weeks": [],
        "t2dm_trajectory_adjustment_factor": 1.0,
        "dose_schedule": [],                 # Doctor defines
        "monitoring_frequency_weeks": 4,    # Default
    }
}
```

---

## Data Assumptions & Flags (for Written Walkthrough)

The following assumptions should be documented in the written deliverable:

1. **Unit assumption:** Weight observations in Canvas may be stored as oz, kg, or lbs.
   The plugin converts all to lbs. If unit metadata is missing, the plugin logs a
   warning and skips the observation rather than guessing.

2. **Baseline definition:** Baseline = observation with the earliest `datetime_of_service`,
   regardless of how it was entered. If two observations share the same earliest date,
   use the one with the higher value (conservative baseline → larger denominator).

3. **Sex field:** Captured in PatientEnrollment for potential future trajectory adjustment.
   NOT used for stratification in MVP (unlike pediatric plugin). Absent sex doesn't
   block the chart from rendering.

4. **T2DM detection:** MVP assumes manual entry via program template selection. 
   Phase 2 would automate this from Condition queries.

5. **Dose tracking:** Not in MVP scope. Phase 2 would query MedicationRequest to track
   actual dose vs. scheduled escalation.

6. **Data source for benchmarks:** Published peer-reviewed trials only. No proprietary
   data. Benchmark lines are labeled with trial name and citation in the chart tooltip.

---

## Roadmap Implications

| Phase | Feature | Data needed |
|-------|---------|-------------|
| MVP   | Weight trajectory + baseline + % TBWL | Canvas Observation (weight) |
| 2     | Benchmark overlay vs. published trial | Program template (medication + start date) |
| 2     | Early-responder flag at week 12 | Program template + enrollment date |
| 2     | Dose escalation timeline | MedicationRequest queries |
| 3     | Multi-metric: HbA1c, BP, lipids | Additional Observation codes |
| 3     | Responder classification ML model | Patient factors + trajectory data |
| 4     | Doctor-configurable program templates | Custom data module in Canvas |
| 4     | Cohort view (population response) | Patient cohort + data aggregation |
