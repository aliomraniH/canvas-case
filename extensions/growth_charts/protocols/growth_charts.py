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
from datetime import date, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton, SHOW_BUTTON_REGEX
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient, Observation, Note

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


def _now_iso() -> str:
    """Current time as an ISO-8601 string (helper, no mutable default anywhere)."""
    return datetime.now().isoformat()


def _json_default(value):
    """JSON serializer for datetimes — emits ISO-8601 so JS `new Date()` parses cleanly."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


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

    def _strip_tz(dt):
        """Strip timezone info for consistent sorting (mix of FHIR-aware and naive dates)."""
        if dt is not None and hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

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
    """Float weeks between two dates. Negative if current precedes baseline."""
    delta = current_date - baseline_date
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


def build_chart_data(observations_raw: list, notes_or_baseline=None) -> dict:
    """Orchestrate the Processing Layer and return the chart payload.

    Second argument is overloaded (locked Option B):
      - dict  → a pre-fetched {note_id: Note} map; dates are attached from it.
      - numeric / None → observations already carry their own dates (raw dicts
        with datetime_of_service, or SDK-like objects). The numeric value is the
        legacy `baseline` arg and is ignored — baseline is always recomputed from
        the earliest observation.
    """
    if isinstance(notes_or_baseline, dict):
        observations_with_dates = attach_dates_to_observations(observations_raw, notes_or_baseline)
    else:
        observations_with_dates = list(observations_raw)

    baseline = _baseline_record(observations_with_dates)

    datapoints = [
        build_observation_processed(obs, baseline) for obs in observations_with_dates
    ]
    # Strip timezone for sorting — FHIR dates are tz-aware, UI dates may be naive.
    datapoints.sort(key=lambda dp: (
        dp["date_obj"].replace(tzinfo=None)
        if dp["date_obj"] is not None and getattr(dp["date_obj"], "tzinfo", None) is not None
        else dp["date_obj"]
    ))

    latest_tbwl_pct = datapoints[-1]["tbwl_pct"] if datapoints else 0.0

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
    dates = [dp.get("date_obj") for dp in datapoints if dp.get("date_obj") is not None]
    if dates != sorted(dates):
        errors.append("Datapoints not sorted ascending by date / wrong order")

    # 7. pipeline timestamps present
    if "_pipeline_timestamps" not in payload:
        errors.append("Missing _pipeline_timestamps")

    # 8. all required template keys present
    for key in REQUIRED_TEMPLATE_KEYS:
        if key not in payload:
            errors.append(f"Missing required template key: {key}")

    return (len(errors) == 0, errors)


# ─────────────────────────────────────────────────────────────
# SECTION 4: Render Layer (template context assembly)
# ─────────────────────────────────────────────────────────────


def assemble_template_context(
    patient: dict,
    baseline: dict,
    datapoints: list[dict],
    pipeline_timestamps: dict,
) -> dict:
    """Assemble the final context for render_to_string().

    Each top-level component dict carries `_component` and `_loaded_at`.
    """
    now = _now_iso()

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

    return {
        "patient": {**patient, "_component": "patient_info", "_loaded_at": now},
        "baseline_data": {**baseline, "_component": "baseline_layer", "_loaded_at": now},
        "datapoints": datapoints,
        "latest_annotation": latest_annotation,
        "latest_tbwl_pct": latest_tbwl_pct,
        "chart_config": {
            "x_axis_type": "calendar_date",
            "y_axis_unit": "lbs",
            "show_benchmark_overlay": False,
            "benchmark_source": None,
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
        patient = load_patient_demographics(self._patient_id())
        obs_raw = load_weight_observations_raw(self._patient_id())
        note_ids = [o["canvas_note_id"] for o in obs_raw if o.get("canvas_note_id")]
        notes = batch_load_notes(note_ids)

        # 2. Process — no usable observations is an expected, recoverable condition
        try:
            payload = build_chart_data(obs_raw, notes)
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
        )

        # 5. Render — serialize the whole context for the template's JSON.parse()
        chart_data_json = json.dumps(context, default=_json_default)
        html = render_to_string("templates/chart.html", {"chart_data_json": chart_data_json})
        return [LaunchModalEffect(content=html).apply()]

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
        return [LaunchModalEffect(content=html).apply()]
