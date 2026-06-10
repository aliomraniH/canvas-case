"""
cardiometabolic_tracker — adult GLP-1 weight-trajectory plugin.

Adapted from the pediatric growth_charts plugin. Plots each patient's weight
against their OWN baseline (first weight observation) on a calendar-date X-axis,
annotated with % total body weight loss (TBWL). No population percentile curves,
no sex stratification, no age-in-months math.

Organized into five layers (see component_architecture.md):
  Section 1 — Data Loading Layer   (SDK calls, returns plain dicts/lists)
  Section 2 — Processing Layer      (pure functions, no SDK calls)
  Section 3 — Validation Layer      (payload checks, run before any modal)
  Section 4 — Render Layer          (template-context assembly)
  Section 5 — ActionButton Handler  (thin orchestration)
"""

# Defer annotation evaluation (PEP 563): the Canvas RestrictedPython sandbox does
# not expose every builtin (e.g. `object`), and without this, annotations like
# `dict[str, object]` are evaluated at definition time and raise NameError.
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton, SHOW_BUTTON_REGEX
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient, Observation, Note, Medication

try:
    # Canvas sandbox provides the runtime logger.
    from logger import log
except ImportError:  # running outside the sandbox (e.g. local pytest)
    class _NoopLog:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    log = _NoopLog()

PROCESSING_VERSION = "1.0"

# Required keys the template context must always carry.
REQUIRED_TEMPLATE_KEYS = (
    "baseline_data",
    "datapoints",
    "latest_tbwl_pct",
    "_pipeline_timestamps",
)

# Weight-unit conversion factors to pounds.
_WEIGHT_TO_LBS = {
    "lbs": 1.0,
    "lb": 1.0,
    "kg": 2.20462,
    "oz": 1.0 / 16.0,
    "g": 0.00220462,
}

# ─── v0.2 constants (E1 milestones, E2 expected band, E3 velocity/flags) ───

MILESTONE_PCTS = (5.0, 10.0, 15.0)

# Y-axis padding rule, shared with the template: Python `_axis_domain` is the
# source of truth for milestone suppression; the JS scaffold reads these same
# values from chart_config instead of hardcoding them (drift guard).
AXIS_PAD_FRACTION = 0.1
AXIS_PAD_MIN_LBS = 2.0

DEFAULT_AGENT = "semaglutide_step1"

# Agent detection (A3): lower-case substring match against active-medication
# coding display text. Generic + US brand names per agent.
GLP1_AGENT_KEYWORDS = {
    "semaglutide_step1": ("semaglutide", "wegovy", "ozempic"),
    "tirzepatide_surmount1": ("tirzepatide", "zepbound", "mounjaro"),
    "liraglutide_scale": ("liraglutide", "saxenda", "victoza"),
}

# Expected %TBWL corridors, (week, lower_pct, upper_pct) per agent.
# lower_pct = least expected loss (5th pct), upper_pct = most (95th pct).
# Sources (see glp1_science_reference.md / assumptions_tests_rationale.md):
#   STEP-1     Wilding et al., NEJM 2021;384:989-1002
#   SURMOUNT-1 Jastreboff et al., NEJM 2022;387:205-216 (15 mg arm)
#   SCALE      Pi-Sunyer et al., NEJM 2015;373:11-22 — means only published;
#              bounds synthesized at mean x0.5 / x1.5 (the relative spread the
#              STEP-1 and SURMOUNT-1 percentile columns show). Approximation.
# SCALE published means only — its band bounds are synthesized, and the UI
# must disclose that (v0.2.3). Shown only when estimated_bounds is True.
SCALE_BOUNDS_DISCLOSURE = (
    "Band bounds are estimated as 0.5×–1.5× of the published trial mean; "
    "SCALE did not report percentile distributions. Interpret the band width "
    "as illustrative, not statistical."
)

# Citation volume/page strings verified against glp1_science_reference.md
# (Gate 1, 2026-06-10): 2021;384:989-1002 / 2022;387:205-216 / 2015;373:11-22.
EXPECTED_RESPONSE_BANDS = {
    "semaglutide_step1": {
        "label": "STEP-1",
        "metadata": {
            "trial": "STEP 1",
            "citation": (
                "Wilding JPH, et al. Once-Weekly Semaglutide in Adults with "
                "Overweight or Obesity. N Engl J Med 2021;384:989-1002."
            ),
            "summary": "Mean −14.9% body weight at 68 weeks vs −2.4% placebo (n=1,961).",
            "estimated_bounds": False,
        },
        "points": (
            (0, 0.0, 0.0), (4, 0.5, 4.5), (8, 1.0, 7.0), (12, 2.0, 11.0),
            (16, 3.0, 13.5), (20, 4.0, 15.0), (24, 5.0, 16.5), (36, 6.0, 19.0),
            (52, 7.0, 21.0), (68, 7.5, 22.0),
        ),
    },
    "tirzepatide_surmount1": {
        "label": "SURMOUNT-1",
        "metadata": {
            "trial": "SURMOUNT-1",
            "citation": (
                "Jastreboff AM, et al. Tirzepatide Once Weekly for the "
                "Treatment of Obesity. N Engl J Med 2022;387:205-216."
            ),
            "summary": "Mean −15.0% to −20.9% at 72 weeks by dose vs −3.1% placebo (n=2,539).",
            "estimated_bounds": False,
        },
        "points": (
            (0, 0.0, 0.0), (4, 0.8, 5.5), (8, 2.0, 10.0), (12, 3.5, 14.5),
            (16, 5.0, 18.0), (24, 8.0, 22.0), (36, 10.0, 26.0),
            (52, 12.0, 28.5), (72, 13.0, 31.0),
        ),
    },
    "liraglutide_scale": {
        "label": "SCALE",
        "metadata": {
            "trial": "SCALE",
            "citation": (
                "Pi-Sunyer X, et al. A Randomized, Controlled Trial of 3.0 mg "
                "of Liraglutide in Weight Management. N Engl J Med 2015;373:11-22."
            ),
            "summary": "Mean −8.0% (8.4 kg) at 56 weeks vs −2.6% placebo (n=3,731).",
            "estimated_bounds": True,
            "disclosure": SCALE_BOUNDS_DISCLOSURE,
        },
        "points": (
            (0, 0.0, 0.0), (12, 2.1, 6.3), (24, 3.2, 9.6),
            (40, 3.9, 11.7), (56, 4.2, 12.6),
        ),
    },
}

VELOCITY_WINDOW_WEEKS = 4.0
VELOCITY_MIN_SPAN_DAYS = 14.0
PLATEAU_WINDOW_WEEKS = 8.0
PLATEAU_MIN_WEEK = 8.0          # plateau/regain evaluated only after week 8
PLATEAU_ABS_DELTA_PCT = 0.5     # |ΔTBWL| over trailing 8 wk below this = plateau
REGAIN_DELTA_PCT = -0.5         # ΔTBWL at or below this over trailing 8 wk = regain
RAPID_VELOCITY_PCT_PER_WEEK = 1.0

# Informational decision support only — copy is descriptive, never directive.
FLAG_DEFINITIONS = {
    "plateau": {
        "key": "plateau",
        "label": "Plateau",
        "severity": "amber",
        "message": "Weight loss has slowed — consider reviewing dose/adherence.",
    },
    "regain": {
        "key": "regain",
        "label": "Regain",
        "severity": "amber",
        "message": "Weight is trending upward over the last 8 weeks — consider reviewing adherence and follow-up.",
    },
    "rapid_loss": {
        "key": "rapid_loss",
        "label": "Rapid loss",
        "severity": "red",
        "message": "Weight loss has exceeded 1.0% per week over the last 4 weeks — consider reviewing nutrition and tolerability.",
    },
}


def _now_iso() -> str:
    """Current time as an ISO-8601 string (helper, no mutable default anywhere)."""
    return datetime.now().isoformat()


def _json_default(value):
    """JSON serializer for datetimes — emits ISO-8601 so JS `new Date()` parses cleanly."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _strip_tz(dt):
    """Strip timezone info so aware (FHIR-created) and naive (UI-created)
    datetimes compare without TypeError. Use as the key for every
    sort/min/max over observation dates — never compare them raw."""
    if dt is not None and hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# ─────────────────────────────────────────────────────────────
# SECTION 1: Data Loading Layer
# ─────────────────────────────────────────────────────────────
# All functions here perform SDK calls and return plain dicts/lists with no
# side effects, so they can be exercised in isolation with a mocked SDK.


def load_patient_demographics(patient_id: str) -> dict:
    """Load patient demographics.

    `sex_at_birth` is captured for future use but NEVER gates rendering.
    Returns a plain dict tagged with `_component` and `_loaded_at`.
    """
    sex_at_birth = None
    birth_date = None
    try:
        patient = Patient.objects.get(id=patient_id)
        sex_at_birth = getattr(patient, "sex_at_birth", None)
        birth_date = getattr(patient, "birth_date", None)
    except Patient.DoesNotExist:
        log.warning("Patient %s not found while loading demographics", patient_id)

    return {
        "patient_id": patient_id,
        "sex_at_birth": sex_at_birth,
        "birth_date": birth_date,
        "_component": "patient_info",
        "_loaded_at": _now_iso(),
    }


def load_weight_observations_raw(patient_id: str) -> list[dict]:
    """Query weight observations only. Does NOT fetch notes (that's batch_load_notes).

    Each returned dict carries raw values plus the originating note id.
    """
    observations = Observation.objects.for_patient(patient_id).filter(name="weight")

    raw: list[dict] = []
    for obs in observations:
        if obs.value is None:
            continue
        raw.append(
            {
                "id": getattr(obs, "id", None),
                "value_original": obs.value,
                "unit_original": getattr(obs, "units", None),  # SDK field is 'units' (plural)
                "canvas_note_id": _note_id_of(obs),
                "_loaded_at": _now_iso(),
            }
        )
    return raw


def batch_load_notes(note_ids: list[str]) -> dict[str, object]:
    """SINGLE query for all notes — the N+1 fix.

    Observation.note_id is a BigIntegerField storing Note.dbid (the integer PK),
    NOT the Note.id UUID field. Filter on dbid, key the result by str(dbid) so
    that attach_dates_to_observations can do O(1) lookups by the same value.

    Returns {str(note_dbid): Note} for O(1) lookup during processing.
    """
    if not note_ids:
        return {}
    # Convert to integers (Observation.note_id is BigIntegerField)
    int_ids: list[int] = []
    for nid in note_ids:
        try:
            int_ids.append(int(nid))
        except (ValueError, TypeError):
            log.warning("Skipping non-integer note_id: %r", nid)
    if not int_ids:
        return {}
    notes = Note.objects.filter(dbid__in=int_ids)
    return {str(getattr(note, "dbid", "")): note for note in notes}


def attach_dates_to_observations(
    observations_raw: list[dict],
    notes_by_id: dict,
) -> list[dict]:
    """Join observations with their note dates using the pre-fetched notes dict.

    Pure dict manipulation — no DB calls. Observations whose note is missing are
    skipped with a logged warning rather than silently guessing a date.
    """
    joined: list[dict] = []
    for obs in observations_raw:
        note = notes_by_id.get(str(obs.get("canvas_note_id")))
        if note is None:
            log.warning(
                "No note for observation %s (note_id=%s); skipping",
                obs.get("id"),
                obs.get("canvas_note_id"),
            )
            continue
        dos = getattr(note, "datetime_of_service", None)
        if dos is None:
            log.warning("Note %s has no datetime_of_service; skipping", obs.get("canvas_note_id"))
            continue
        enriched = dict(obs)
        enriched["datetime_of_service"] = dos
        joined.append(enriched)
    return joined


def detect_glp1_agent(patient_id: str) -> str:
    """Detect which GLP-1 agent the patient is on, for expected-band selection.

    Matches active-medication coding display text against GLP1_AGENT_KEYWORDS.
    Exactly one agent matched → that agent. No match, multiple matches, or ANY
    query/schema error → DEFAULT_AGENT with the fallback reason logged.

    The broad except is a deliberate addendum requirement: a medication-model
    schema surprise must degrade to the default band, never crash the chart.
    Field access verified against canvas_sdk 0.163.1 source + docs:
    Medication.objects.for_patient(id).active(); med.codings.all() → .display.
    """
    try:
        medications = (
            Medication.objects.for_patient(patient_id)
            .active()
            .prefetch_related("codings")  # one query for all codings, not one per med
        )
        matched: set[str] = set()
        for med in medications:
            texts: list[str] = []
            codings = getattr(med, "codings", None)
            if codings is not None:
                for coding in codings.all():
                    display = getattr(coding, "display", None)
                    if display:
                        texts.append(str(display).lower())
            for agent, keywords in GLP1_AGENT_KEYWORDS.items():
                if any(kw in text for text in texts for kw in keywords):
                    matched.add(agent)
        if len(matched) == 1:
            return next(iter(matched))
        if matched:
            log.warning(
                "Multiple GLP-1 agents matched for patient %s (%s); defaulting to %s",
                patient_id, sorted(matched), DEFAULT_AGENT,
            )
        else:
            log.info(
                "No GLP-1 medication matched for patient %s; defaulting to %s",
                patient_id, DEFAULT_AGENT,
            )
        return DEFAULT_AGENT
    except Exception as exc:  # degrade to default band — never block the chart
        log.warning(
            "Medication lookup failed for patient %s (%s: %s); defaulting to %s",
            patient_id, type(exc).__name__, exc, DEFAULT_AGENT,
        )
        return DEFAULT_AGENT


# ─────────────────────────────────────────────────────────────
# SECTION 2: Processing Layer
# ─────────────────────────────────────────────────────────────
# Pure functions: no DB calls, no side effects. Accept primitives/dicts (and,
# for convenience in tests, raw SDK-like observation objects).


def convert_weight_to_lbs(value: float, unit: str) -> float:
    """Convert any supported weight unit to pounds. Case-insensitive.

    Raises ValueError for an unknown unit (never silently returns a wrong value).
    """
    if unit is None:
        raise ValueError("Missing weight unit")
    key = str(unit).strip().lower()
    if key not in _WEIGHT_TO_LBS:
        raise ValueError(f"Unknown weight unit: {unit!r}")
    return float(value) * _WEIGHT_TO_LBS[key]


def _obs_value(obs) -> float:
    """Read a weight value from a raw dict or an SDK-like object."""
    if isinstance(obs, dict):
        return float(obs.get("value_original"))
    return float(obs.value)


def _obs_unit(obs) -> str:
    """Read a weight unit from a raw dict or an SDK-like object.

    The Canvas SDK Observation model uses 'units' (plural), not 'unit'.
    """
    if isinstance(obs, dict):
        return obs.get("unit_original")
    return getattr(obs, "units", None)  # SDK field is 'units' (plural)


def _obs_date(obs):
    """Read datetime_of_service from a raw dict (post-attach) or an SDK-like object."""
    if isinstance(obs, dict):
        return obs.get("datetime_of_service")
    note = getattr(obs, "note", None)
    return getattr(note, "datetime_of_service", None) if note is not None else None


def _obs_id(obs):
    """Read the observation id from a raw dict or an SDK-like object."""
    if isinstance(obs, dict):
        return obs.get("id")
    return getattr(obs, "id", None)


def _note_id_of(obs) -> str:
    """Read the note dbid from an SDK-like observation object.

    Observation.note_id is a BigIntegerField that stores Note.dbid (the integer
    primary key). We never use Note.id (the UUIDField) here because
    Note.objects.filter(dbid__in=...) is the correct lookup path.
    """
    note_id = getattr(obs, "note_id", None)
    return str(note_id) if note_id is not None else None


def _baseline_record(observations: list) -> dict:
    """Internal: full baseline record used by the pipeline.

    Sorts ascending by datetime_of_service; ties on the earliest date resolve to
    the higher value (conservative baseline → larger denominator).
    Returns {"value_lbs": float, "date": datetime, "source_id": str}.
    Raises ValueError on an empty list.
    """
    if not observations:
        raise ValueError("Cannot compute baseline from zero observations")

    def sort_key(obs):
        date = _strip_tz(_obs_date(obs))
        # Earliest date first; within a date, higher weight (in lbs) first.
        return (date, -convert_weight_to_lbs(_obs_value(obs), _obs_unit(obs)))

    earliest = sorted(observations, key=sort_key)[0]
    return {
        "value_lbs": convert_weight_to_lbs(_obs_value(earliest), _obs_unit(earliest)),
        "date": _obs_date(earliest),
        "source_id": _obs_id(earliest),
    }


def compute_baseline(observations: list) -> float:
    """Select the earliest observation as baseline and return its weight in lbs.

    Baseline = first observation sorted ascending by datetime_of_service.
    Raises ValueError on an empty list.
    """
    return _baseline_record(observations)["value_lbs"]


def calculate_tbwl(baseline_lbs: float, current_lbs: float) -> float:
    """% TBWL = ((baseline - current) / baseline) * 100.

    Positive = weight lost. Raises ValueError if baseline <= 0.
    """
    baseline_lbs = float(baseline_lbs)
    if baseline_lbs <= 0:
        raise ValueError("Baseline weight must be positive")
    return ((baseline_lbs - float(current_lbs)) / baseline_lbs) * 100.0


def calculate_weeks_since_baseline(baseline_date: datetime, current_date: datetime) -> float:
    """Float weeks between two dates. Negative if current precedes baseline.

    Dates are tz-stripped first: subtracting an aware (FHIR) from a naive (UI)
    datetime raises TypeError."""
    delta = _strip_tz(current_date) - _strip_tz(baseline_date)
    return delta.total_seconds() / (7 * 24 * 60 * 60)


def format_date_mmmyyyy(dt: datetime) -> str:
    """Return a 'Jan 2024' style date string (3-letter month)."""
    return dt.strftime("%b %Y")


def build_observation_processed(obs_raw, baseline: dict) -> dict:
    """Convert a single observation to its processed form.

    Raw fields are preserved verbatim in a nested `raw` dict and are NEVER
    overwritten by the derived fields.

    `obs_raw` may be a raw loader dict (with datetime_of_service attached) or an
    SDK-like observation object. `baseline` is the compute_baseline() result.
    """
    value_original = _obs_value(obs_raw)
    unit_original = _obs_unit(obs_raw)
    date_obj = _obs_date(obs_raw)
    value_lbs = convert_weight_to_lbs(value_original, unit_original)

    baseline_lbs = baseline["value_lbs"]
    baseline_date = baseline["date"]

    if isinstance(obs_raw, dict):
        canvas_note_id = obs_raw.get("canvas_note_id")
        raw_loaded_at = obs_raw.get("_loaded_at")
    else:
        canvas_note_id = _note_id_of(obs_raw)
        raw_loaded_at = None

    return {
        # processed / derived
        "id": _obs_id(obs_raw),
        "value_lbs": value_lbs,
        "date_label": format_date_mmmyyyy(date_obj),
        "date_obj": date_obj,
        "weeks_since_baseline": calculate_weeks_since_baseline(baseline_date, date_obj),
        "tbwl_pct": calculate_tbwl(baseline_lbs, value_lbs),
        "processed_at": _now_iso(),
        "processing_version": PROCESSING_VERSION,
        # raw snapshot — immutable, never overwritten above
        "raw": {
            "value_original": value_original,
            "unit_original": unit_original,
            "canvas_note_id": canvas_note_id,
            "_loaded_at": raw_loaded_at,
        },
    }


# ── v0.2 pure functions ──


def dedupe_same_day(observations_with_dates: list) -> list:
    """Collapse same-calendar-day observations into one averaged point (A6).

    Decision: average (not latest-wins) — deterministic regardless of row
    order (Observation ids are UUIDs, so "latest" has no reliable tie-break
    when entries share a datetime_of_service) and damps re-measurement noise.
    Mixed units on the same day are averaged in lbs and emitted as 'lbs'.
    Observations without a date pass through untouched.
    """
    groups: dict = {}
    order: list = []
    passthrough: list = []
    for obs in observations_with_dates:
        dt = _obs_date(obs)
        if dt is None:
            passthrough.append(obs)
            continue
        day = dt.date() if hasattr(dt, "date") else dt
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(obs)

    out: list = []
    for day in order:
        group = groups[day]
        if len(group) == 1:
            out.append(group[0])
            continue
        lbs_values = [convert_weight_to_lbs(_obs_value(o), _obs_unit(o)) for o in group]
        first = group[0]
        merged = {
            "id": _obs_id(first),
            "value_original": sum(lbs_values) / len(lbs_values),
            "unit_original": "lbs",
            "canvas_note_id": (
                first.get("canvas_note_id") if isinstance(first, dict) else _note_id_of(first)
            ),
            "datetime_of_service": min(
                (_obs_date(o) for o in group), key=_strip_tz
            ),
            "_loaded_at": first.get("_loaded_at") if isinstance(first, dict) else None,
            "deduped_from": [_obs_id(o) for o in group],
        }
        out.append(merged)
    return out + passthrough


def _axis_domain(weights_lbs: list) -> tuple | None:
    """The y-domain the chart will use: pad = max(range * AXIS_PAD_FRACTION,
    AXIS_PAD_MIN_LBS). The template reads the same constants from chart_config,
    so the rule is defined exactly once. Conservative vs d3 `.nice()`, which
    may round the rendered domain slightly outward — documented as intentional.
    """
    weights = [float(w) for w in weights_lbs if w is not None]
    if not weights:
        return None
    lo, hi = min(weights), max(weights)
    pad = max((hi - lo) * AXIS_PAD_FRACTION, AXIS_PAD_MIN_LBS)
    return (lo - pad, hi + pad)


def _collect_axis_weights(datapoints: list[dict], baseline_lbs: float, expected_band: dict) -> list:
    """Every weight that drives the y-axis, in one place.

    Any future plotted layer must register its weights here so the milestone
    suppression domain (`_axis_domain`) and the rendered axis stay in lockstep.
    Milestone lines themselves are deliberately excluded (they never widen
    the axis).
    """
    weights = [dp.get("value_lbs") for dp in datapoints]
    weights.append(baseline_lbs)
    for band_point in expected_band.get("points") or []:
        weights.append(band_point.get("lower_lbs"))
        weights.append(band_point.get("upper_lbs"))
    return weights


def compute_milestone_lines(
    baseline_lbs: float,
    axis_weights_lbs: list,
    latest_tbwl_pct: float | None = None,
) -> list[dict]:
    """E1: 5/10/15% TBWL reference lines, suppressed outside the y-domain.

    `axis_weights_lbs` must be everything that drives the axis: datapoints,
    baseline, and expected-band edge weights. Milestones never widen the axis.
    """
    if baseline_lbs is None or float(baseline_lbs) <= 0:
        return []
    domain = _axis_domain(axis_weights_lbs)
    if domain is None:
        return []
    lines: list[dict] = []
    for pct in MILESTONE_PCTS:
        weight = float(baseline_lbs) * (1.0 - pct / 100.0)
        if domain[0] <= weight <= domain[1]:
            lines.append({
                "pct": pct,
                "weight_lbs": weight,
                "label": f"{pct:g}% TBWL",
                "crossed": latest_tbwl_pct is not None and float(latest_tbwl_pct) >= pct,
            })
    return lines


def _interp_band_at_week(table: tuple, week: float) -> tuple:
    """Linear interpolation of (week, lower_pct, upper_pct) rows; clamps outside."""
    if week <= table[0][0]:
        return (table[0][1], table[0][2])
    if week >= table[-1][0]:
        return (table[-1][1], table[-1][2])
    for (w0, lo0, hi0), (w1, lo1, hi1) in zip(table, table[1:]):
        if w0 <= week <= w1:
            f = (week - w0) / (w1 - w0) if w1 > w0 else 0.0
            return (lo0 + f * (lo1 - lo0), hi0 + f * (hi1 - hi0))
    return (table[-1][1], table[-1][2])


def build_expected_band(
    baseline_lbs: float,
    baseline_date,
    max_weeks: float,
    agent: str = DEFAULT_AGENT,
) -> dict:
    """E2: expected-response corridor, clipped to the observed week range.

    Returns {"agent", "label", "points": [...]}; each point carries week, date,
    lower/upper %TBWL and the corresponding weights. Note the inversion:
    upper_pct (more loss) maps to the LOWER weight (upper_lbs < lower_lbs).
    Empty points when max_weeks <= 0 (e.g. a single observation) so the band
    never stretches the axes.
    """
    if agent not in EXPECTED_RESPONSE_BANDS:
        agent = DEFAULT_AGENT
    band_def = EXPECTED_RESPONSE_BANDS[agent]
    result = {
        "agent": agent,
        "label": band_def["label"],
        "band_metadata": dict(band_def["metadata"]),
        "points": [],
    }
    if baseline_lbs is None or float(baseline_lbs) <= 0:
        return result
    if max_weeks is None or float(max_weeks) <= 0:
        return result

    table = band_def["points"]
    max_weeks = float(max_weeks)
    weeks = sorted(
        {0.0, max_weeks} | {float(w) for (w, _lo, _hi) in table if 0 < w < max_weeks}
    )
    baseline_lbs = float(baseline_lbs)
    for week in weeks:
        lower_pct, upper_pct = _interp_band_at_week(table, week)
        result["points"].append({
            "week": week,
            "date": baseline_date + timedelta(weeks=week) if baseline_date is not None else None,
            "lower_pct": lower_pct,
            "upper_pct": upper_pct,
            "lower_lbs": baseline_lbs * (1.0 - lower_pct / 100.0),
            "upper_lbs": baseline_lbs * (1.0 - upper_pct / 100.0),
        })
    return result


def _dp_week(dp) -> float:
    return float(dp.get("weeks_since_baseline"))


def _dp_tbwl(dp) -> float:
    return float(dp.get("tbwl_pct"))


def _tbwl_at_week(datapoints: list[dict], week: float) -> float:
    """Linear interpolation of tbwl_pct at `week`, clamped to the observed range."""
    pts = sorted(datapoints, key=_dp_week)
    if not pts:
        raise ValueError("Cannot interpolate TBWL with zero datapoints")
    if week <= _dp_week(pts[0]):
        return _dp_tbwl(pts[0])
    if week >= _dp_week(pts[-1]):
        return _dp_tbwl(pts[-1])
    for a, b in zip(pts, pts[1:]):
        wa, wb = _dp_week(a), _dp_week(b)
        if wa <= week <= wb:
            if wb == wa:
                return _dp_tbwl(b)
            f = (week - wa) / (wb - wa)
            return _dp_tbwl(a) + f * (_dp_tbwl(b) - _dp_tbwl(a))
    return _dp_tbwl(pts[-1])


def _qualifies_for_velocity(pts: list[dict]) -> bool:
    """≥2 observations spanning ≥14 days (the E3 data-quality rule)."""
    if len(pts) < 2:
        return False
    span_weeks = _dp_week(pts[-1]) - _dp_week(pts[0])
    return span_weeks * 7.0 >= VELOCITY_MIN_SPAN_DAYS


def compute_velocity(
    datapoints: list[dict],
    window_weeks: float = VELOCITY_WINDOW_WEEKS,
) -> float | None:
    """E3: rolling %TBWL/week over the trailing window. Positive = losing.

    TBWL at (last - window) is linearly interpolated between the bracketing
    observations, so irregular visit spacing is handled. Returns None when the
    series has <2 observations or spans <14 days.
    """
    pts = sorted(
        [dp for dp in datapoints if dp.get("weeks_since_baseline") is not None],
        key=_dp_week,
    )
    if not _qualifies_for_velocity(pts):
        return None
    end_week = _dp_week(pts[-1])
    start_week = max(end_week - float(window_weeks), _dp_week(pts[0]))
    if end_week <= start_week:
        return None
    return (_dp_tbwl(pts[-1]) - _tbwl_at_week(pts, start_week)) / (end_week - start_week)


def build_velocity_stats(velocity_pct_per_week: float | None) -> dict:
    """Template-facing velocity summary. Display sign: loss renders negative
    (internal TBWL is positive-for-loss), e.g. velocity +0.6 → '-0.60%/wk'.
    """
    if velocity_pct_per_week is None:
        display = "—"  # em dash
    else:
        display = f"{-float(velocity_pct_per_week):.2f}%/wk"
    return {
        "velocity_pct_per_week": velocity_pct_per_week,
        "display": display,
        "window_weeks": VELOCITY_WINDOW_WEEKS,
        "_component": "velocity_stats",
        "_loaded_at": _now_iso(),
    }


def detect_flags(datapoints: list[dict], velocity_pct_per_week: float | None) -> list[dict]:
    """E3 flags: plateau, regain (A5), rapid loss. Informational only.

    Plateau vs regain over the trailing 8 weeks (evaluated only after week 8):
      |ΔTBWL| < 0.5            → plateau (truly flat)
      ΔTBWL ≤ -0.5             → regain (weight moving UP — not a plateau)
      ΔTBWL ≥ +0.5             → still losing, no flag
    The absolute-value plateau test is what keeps P5-style regain from being
    mislabeled as a plateau. Rapid loss: trailing 4-week velocity > 1.0%/wk;
    the rolling-average window is the "sustained" test.
    """
    pts = sorted(
        [dp for dp in datapoints if dp.get("weeks_since_baseline") is not None],
        key=_dp_week,
    )
    flags: list[dict] = []
    if not _qualifies_for_velocity(pts):
        return flags

    last_week = _dp_week(pts[-1])
    if last_week > PLATEAU_MIN_WEEK:
        window_start = max(last_week - PLATEAU_WINDOW_WEEKS, _dp_week(pts[0]))
        delta8 = _dp_tbwl(pts[-1]) - _tbwl_at_week(pts, window_start)
        if abs(delta8) < PLATEAU_ABS_DELTA_PCT:
            flags.append(dict(FLAG_DEFINITIONS["plateau"]))
        elif delta8 <= REGAIN_DELTA_PCT:
            flags.append(dict(FLAG_DEFINITIONS["regain"]))

    if velocity_pct_per_week is not None and velocity_pct_per_week > RAPID_VELOCITY_PCT_PER_WEEK:
        flags.append(dict(FLAG_DEFINITIONS["rapid_loss"]))
    return flags


def build_chart_data(observations_raw: list, notes_or_baseline=None, agent: str = DEFAULT_AGENT) -> dict:
    """Orchestrate the Processing Layer and return the chart payload.

    Second argument is overloaded (locked Option B):
      - dict  → a pre-fetched {note_id: Note} map; dates are attached from it.
      - numeric / None → observations already carry their own dates (raw dicts
        with datetime_of_service, or SDK-like objects). The numeric value is the
        legacy `baseline` arg and is ignored — baseline is always recomputed from
        the earliest observation.

    `agent` selects the expected-response band table (v0.2 / A3); callers pass
    detect_glp1_agent()'s result so this function stays SDK-free.
    """
    if isinstance(notes_or_baseline, dict):
        observations_with_dates = attach_dates_to_observations(observations_raw, notes_or_baseline)
    else:
        observations_with_dates = list(observations_raw)

    observations_with_dates = dedupe_same_day(observations_with_dates)
    baseline = _baseline_record(observations_with_dates)

    datapoints = [
        build_observation_processed(obs, baseline) for obs in observations_with_dates
    ]
    # Strip timezone for sorting — FHIR dates are tz-aware, UI dates may be naive.
    datapoints.sort(key=lambda dp: _strip_tz(dp["date_obj"]))

    latest_tbwl_pct = datapoints[-1]["tbwl_pct"] if datapoints else 0.0

    # v0.2 derived layers. Band only with ≥2 datapoints (a single observation
    # has zero observed span, so the band would just stretch the axes).
    last_week = datapoints[-1]["weeks_since_baseline"] if len(datapoints) >= 2 else 0.0
    expected_band = build_expected_band(
        baseline["value_lbs"], baseline["date"], last_week, agent
    )
    axis_weights = _collect_axis_weights(datapoints, baseline["value_lbs"], expected_band)
    milestones = compute_milestone_lines(baseline["value_lbs"], axis_weights, latest_tbwl_pct)
    velocity = compute_velocity(datapoints)
    velocity_stats = build_velocity_stats(velocity)
    flags = detect_flags(datapoints, velocity)

    now = _now_iso()
    return {
        "baseline_data": {
            "value": baseline["value_lbs"],
            "value_lbs": baseline["value_lbs"],
            "unit": "lbs",
            "source_observation_id": baseline["source_id"],
            "_component": "baseline_layer",
            "_loaded_at": now,
        },
        "datapoints": datapoints,
        "latest_tbwl_pct": latest_tbwl_pct,
        "milestones": milestones,
        "expected_band": expected_band,
        "velocity_stats": velocity_stats,
        "flags": flags,
        "_pipeline_timestamps": {
            "demographics_loaded": now,
            "observations_loaded": now,
            "observations_raw_loaded": now,
            "notes_batch_loaded": now,
            "processing_complete": now,
        },
    }


# ─────────────────────────────────────────────────────────────
# SECTION 3: Validation Layer
# ─────────────────────────────────────────────────────────────


def validate_chart_payload(payload: dict) -> tuple[bool, list[str]]:
    """Run BEFORE any LaunchModalEffect. Returns (is_valid, [error messages])."""
    errors: list[str] = []

    # 1. baseline present and positive
    baseline_data = payload.get("baseline_data")
    if not baseline_data or float(baseline_data.get("value", 0) or 0) <= 0:
        errors.append("Missing or non-positive baseline value")

    # 2. datapoints non-empty
    datapoints = payload.get("datapoints")
    if not datapoints:
        errors.append("No datapoints to render")
        datapoints = []

    # 3. no future observation dates
    # Use timezone-aware now so we can compare with both aware and naive date_obj values.
    # FHIR-created observations carry tzinfo (+00:00); UI-created ones may be naive.
    now_naive = datetime.now()

    def _is_future(dt) -> bool:
        """Return True if dt is in the future, handling tz-aware and naive datetimes."""
        if dt is None:
            return False
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt.replace(tzinfo=None) > now_naive   # strip tz, compare in local time
        return dt > now_naive

    if any(_is_future(dp.get("date_obj")) for dp in datapoints):
        errors.append("Observation date is in the future")

    # 4. latest TBWL in plausible [-20, 50] range
    latest = payload.get("latest_tbwl_pct")
    if latest is not None and not (-20.0 <= float(latest) <= 50.0):
        errors.append("latest TBWL percentage out of plausible range")

    # 5. no zero/negative weights
    if any(float(dp.get("value_lbs", 0)) <= 0 for dp in datapoints):
        errors.append("Zero or negative weight value present")

    # 6. datapoints sorted ascending by date
    dates = [_strip_tz(dp.get("date_obj")) for dp in datapoints
             if dp.get("date_obj") is not None]
    if dates != sorted(dates):
        errors.append("Datapoints not sorted ascending by date / wrong order")

    # 7. pipeline timestamps present
    if "_pipeline_timestamps" not in payload:
        errors.append("Missing _pipeline_timestamps")

    # 8. all required template keys present
    for key in REQUIRED_TEMPLATE_KEYS:
        if key not in payload:
            errors.append(f"Missing required template key: {key}")

    # 9. v0.2 keys — shape-checked only when present, so legacy payloads
    # (pre-0.2 callers and the byte-untouched v0.1 tests) remain valid.
    # build_chart_data always emits them; tests assert that separately.
    if "milestones" in payload and not isinstance(payload.get("milestones"), list):
        errors.append("milestones must be a list")
    if "flags" in payload and not isinstance(payload.get("flags"), list):
        errors.append("flags must be a list")
    if "expected_band" in payload:
        band = payload.get("expected_band")
        if not isinstance(band, dict) or "points" not in band or "label" not in band:
            errors.append("expected_band malformed (needs label + points)")
    if "velocity_stats" in payload:
        stats = payload.get("velocity_stats")
        if not isinstance(stats, dict) or "display" not in stats:
            errors.append("velocity_stats malformed (needs display)")

    return (len(errors) == 0, errors)


# ─────────────────────────────────────────────────────────────
# SECTION 4: Render Layer (template context assembly)
# ─────────────────────────────────────────────────────────────


def assemble_template_context(
    patient: dict,
    baseline: dict,
    datapoints: list[dict],
    pipeline_timestamps: dict,
    milestones: list[dict] | None = None,
    expected_band: dict | None = None,
    velocity_stats: dict | None = None,
    flags: list[dict] | None = None,
) -> dict:
    """Assemble the final context for render_to_string().

    Each top-level component dict carries `_component` and `_loaded_at`.
    The v0.2 arguments are keyword-optional so v0.1 call sites (and the
    byte-untouched v0.1 tests) keep working; defaults are valid empty states.
    """
    now = _now_iso()

    if milestones is None:
        milestones = []
    if expected_band is None:
        expected_band = {
            "agent": DEFAULT_AGENT,
            "label": EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["label"],
            "band_metadata": dict(EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["metadata"]),
            "points": [],
        }
    if velocity_stats is None:
        velocity_stats = build_velocity_stats(None)
    if flags is None:
        flags = []

    if datapoints:
        latest = datapoints[-1]
        latest_annotation = {
            "tbwl_pct": latest["tbwl_pct"],
            "weight_lbs": latest["value_lbs"],
            "date_label": latest["date_label"],
            "_component": "annotation_layer",
            "_loaded_at": now,
        }
        latest_tbwl_pct = latest["tbwl_pct"]
    else:
        latest_annotation = {
            "tbwl_pct": 0.0,
            "weight_lbs": 0.0,
            "date_label": "",
            "_component": "annotation_layer",
            "_loaded_at": now,
        }
        latest_tbwl_pct = 0.0

    timestamps = dict(pipeline_timestamps)
    timestamps.setdefault("demographics_loaded", now)
    timestamps.setdefault("observations_raw_loaded", now)
    timestamps.setdefault("notes_batch_loaded", now)
    timestamps.setdefault("processing_complete", now)
    timestamps["validation_passed"] = now
    timestamps["template_context_assembled"] = now

    band_label = expected_band.get("label") or EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["label"]
    band_metadata = expected_band.get("band_metadata") or {}
    # Estimated (synthesized) bounds are disclosed in the legend itself (v0.2.3).
    legend_label = f"{band_label}, estimated" if band_metadata.get("estimated_bounds") else band_label
    return {
        "patient": {**patient, "_component": "patient_info", "_loaded_at": now},
        "baseline_data": {**baseline, "_component": "baseline_layer", "_loaded_at": now},
        "datapoints": datapoints,
        "latest_annotation": latest_annotation,
        "latest_tbwl_pct": latest_tbwl_pct,
        "milestones": milestones,
        "expected_band": {**expected_band, "_component": "expected_band_layer", "_loaded_at": now},
        "velocity_stats": velocity_stats,
        "flags": flags,
        "chart_config": {
            "x_axis_type": "calendar_date",
            "y_axis_unit": "lbs",
            "show_benchmark_overlay": bool(expected_band.get("points")),
            "benchmark_source": band_label,
            "legend_text": f"Expected response ({legend_label})",
            # Axis padding rule — JS must use these, not hardcoded values, so
            # the rendered domain can't drift from _axis_domain's suppression.
            "axis_pad_fraction": AXIS_PAD_FRACTION,
            "axis_pad_min_lbs": AXIS_PAD_MIN_LBS,
        },
        "_pipeline_timestamps": timestamps,
    }


# ─────────────────────────────────────────────────────────────
# SECTION 5: ActionButton Handler
# ─────────────────────────────────────────────────────────────


class GenerateVitalsGraphs(ActionButton):
    """Thin orchestration layer. Business logic lives in Sections 1-4."""

    BUTTON_TITLE = "Weight Trajectory"
    BUTTON_KEY = "show_cardiometabolic_tracker"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION

    def _patient_id(self) -> str:
        """Resolve the patient id from the action-button event target."""
        event = getattr(self, "event", None)
        target = getattr(event, "target", None)
        target_id = getattr(target, "id", None)
        if target_id:
            return target_id
        context = getattr(self, "context", {}) or {}
        patient = context.get("patient")
        return patient.get("id") if isinstance(patient, dict) else context.get("patient_id")

    def compute(self) -> list[Effect]:
        """Dispatch (Option B).

        For SHOW_*_BUTTON events, defer to the base class so the button renders
        and clicks route normally. Otherwise (button click, or a direct test
        invocation) run the pipeline via handle(). The regex match is guarded so a
        mocked event in tests falls through to handle().
        """
        try:
            is_show_event = SHOW_BUTTON_REGEX.fullmatch(self.event.name) is not None
        except (AttributeError, TypeError):
            is_show_event = False

        if is_show_event:
            return super().compute()
        return self.handle()

    def handle(self) -> list[Effect]:
        # 1. Load
        patient_id = self._patient_id()
        patient = load_patient_demographics(patient_id)
        obs_raw = load_weight_observations_raw(patient_id)
        note_ids = [o["canvas_note_id"] for o in obs_raw if o.get("canvas_note_id")]
        notes = batch_load_notes(note_ids)
        agent = detect_glp1_agent(patient_id)

        # 2. Process — no usable observations is an expected, recoverable condition
        try:
            payload = build_chart_data(obs_raw, notes, agent=agent)
        except ValueError as exc:
            return self._render_error([str(exc)])

        # 3. Validate — BEFORE any LaunchModalEffect
        is_valid, errors = validate_chart_payload(payload)
        if not is_valid:
            return self._render_error(errors)

        # 4. Assemble context
        context = assemble_template_context(
            patient=patient,
            baseline=payload["baseline_data"],
            datapoints=payload["datapoints"],
            pipeline_timestamps=payload.get("_pipeline_timestamps", {}),
            milestones=payload.get("milestones"),
            expected_band=payload.get("expected_band"),
            velocity_stats=payload.get("velocity_stats"),
            flags=payload.get("flags"),
        )

        # 5. Render — serialize the whole context for the template's JSON.parse()
        chart_data_json = json.dumps(context, default=_json_default)
        html = render_to_string("templates/chart.html", {"chart_data_json": chart_data_json})
        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Weight Trajectory",
            ).apply()
        ]

    def _render_error(self, errors: list[str]) -> list[Effect]:
        """Validation failure → an error modal (locked Option B), never [] or a banner."""
        items = "".join(f"<li>{e}</li>" for e in errors)
        html = (
            "<div style=\"font-family: Lato, Arial, sans-serif; padding: 24px;\">"
            "<h2 style=\"margin-top:0;\">Unable to render weight trajectory</h2>"
            "<p>The chart could not be generated because the data did not pass validation:</p>"
            f"<ul>{items}</ul>"
            "</div>"
        )
        return [
            LaunchModalEffect(
                content=html,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Weight Trajectory",
            ).apply()
        ]
