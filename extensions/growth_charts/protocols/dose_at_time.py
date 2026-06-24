"""Phase 1b — point-in-time GLP-1 dose lookup for a weight measurement.

Given a weight Observation's effective date, find the GLP-1 medication whose
coverage period COVERS that date — NOT ``.active()``, which is current-only and
would mislabel a historical point with today's drug.

Design:
  * ``load_glp1_medication_periods(...)`` loads the patient's GLP-1 medication
    statements ONCE (not ``.active()``) with their coverage period — an
    SDK-touching read. ``Medication`` is imported lazily inside the function so
    this module (and the pure resolver below) import cleanly with no SDK present,
    keeping the mock test gate runnable off a live Canvas instance.
  * ``dose_covering_date(periods, target_date)`` is PURE — it operates on the
    already-loaded period list and carries the spec's four cases (covers / before
    any dose / gap between doses / multiple overlapping -> most recent).

UNVERIFIED (Bundle A decision, this session): the Medication coverage-period
field path is NOT confirmed against live SDK 0.163.x. The deployed code only
ever used ``.active()`` and deliberately avoided effective dates (unreliable on
seeded data). The candidate period attribute names below are centralized for a
one-line CLI correction; the Phase 1 deploy checklist hands CLI the live-verify.
A medication whose period attrs are all absent is treated as open-ended (covers
any date) so the feature degrades to "current dose" rather than crashing.
"""

from __future__ import annotations

# No module-level logging: the RestrictedPython sandbox rejects `import logging`
# and `__name__`. This module is pure/data-returning; the handler owns logging
# (it wraps the loader call and logs degraded states).

# Candidate Medication coverage-period attribute names — pending CLI live-verify.
_PERIOD_START_ATTRS = ("period_start", "start_date", "effective_start", "onset_date")
_PERIOD_END_ATTRS = ("period_end", "end_date", "effective_end", "stop_date")


def _strip_tz(dt: object) -> object:
    """Drop tzinfo for naive comparison (FHIR dates are tz-aware, UI may be naive)."""
    replace = getattr(dt, "replace", None)
    if replace is not None and getattr(dt, "tzinfo", None) is not None:
        return replace(tzinfo=None)
    return dt


def _first_attr(obj: object, attrs: tuple[str, ...]) -> object | None:
    for attr in attrs:
        value = getattr(obj, attr, None)
        if value is not None:
            return value
    return None


def _coding_display_texts(med: object) -> list[str]:
    """Display strings from a medication's codings (prefetched by the caller)."""
    texts: list[str] = []
    codings = getattr(med, "codings", None)
    if codings is None:
        return texts
    for coding in codings.all():
        display = getattr(coding, "display", None)
        if display:
            texts.append(str(display))
    return texts


def _matched_agent(display_texts: list[str], agent_keywords: dict) -> str | None:
    """First GLP-1 agent key whose keyword appears in any display text, else None."""
    lowered = [text.lower() for text in display_texts]
    for agent, keywords in agent_keywords.items():
        if any(keyword in text for text in lowered for keyword in keywords):
            return agent
    return None


def load_glp1_medication_periods(patient_id: str, agent_keywords: dict) -> list[dict]:
    """Load ALL GLP-1 medication statements for a patient with their periods.

    ONE query (+ a single prefetch of codings) — never per-row queries. Returns a
    list of period dicts; the caller resolves each datapoint against it in Python,
    so there is no N+1 across datapoints.

    ``agent_keywords`` is injected (the plugin's GLP1_AGENT_KEYWORDS) so this
    module stays decoupled from the handler module and free of import cycles.
    """
    # Lazy import: keeps this module importable with no SDK installed (mock gate).
    from canvas_sdk.v1.data import Medication  # noqa: PLC0415 (intentional, see module docstring)

    periods: list[dict] = []
    medications = Medication.objects.for_patient(patient_id).prefetch_related("codings")
    for med in medications:
        display_texts = _coding_display_texts(med)
        agent = _matched_agent(display_texts, agent_keywords)
        if agent is None:
            continue  # not a GLP-1 agent
        periods.append(
            {
                "agent": agent,
                "drug": display_texts[0] if display_texts else agent,
                "dose": getattr(med, "quantity", None) or getattr(med, "dose", None),
                "start": _first_attr(med, _PERIOD_START_ATTRS),
                "end": _first_attr(med, _PERIOD_END_ATTRS),
                "source_id": getattr(med, "id", None),
            }
        )
    return periods


def _covers(period: dict, target: object) -> bool:
    """True if ``period`` covers ``target`` (inclusive; open-ended bounds count)."""
    target = _strip_tz(target)
    start = period.get("start")
    end = period.get("end")
    if start is not None and _strip_tz(start) > target:
        return False
    if end is not None and _strip_tz(end) < target:
        return False
    return True


def _start_key(period: dict, target: object) -> object:
    """Sort key for "most recent" — later start wins; a missing start is oldest."""
    start = period.get("start")
    if start is None:
        # Open-start period is the least-recent; tie-break below any real start.
        return _strip_tz(target).min if hasattr(_strip_tz(target), "min") else target
    return _strip_tz(start)


def dose_covering_date(periods: list[dict], target_date: object) -> dict | None:
    """The GLP-1 dose in effect on ``target_date``, or None ("no dose on record").

    Cases handled (see tests/test_phase1_dose.py):
      * date covered by exactly one period      -> that period
      * date before any period starts           -> None
      * date in a gap between periods            -> None
      * date covered by multiple periods         -> the most recent (latest start)
    """
    if target_date is None or not periods:
        return None
    covering = [period for period in periods if _covers(period, target_date)]
    if not covering:
        return None
    chosen = max(covering, key=lambda period: _start_key(period, target_date))
    return {
        "agent": chosen.get("agent"),
        "drug": chosen.get("drug"),
        "dose": chosen.get("dose"),
        "period_start": _iso_or_none(chosen.get("start")),
        "period_end": _iso_or_none(chosen.get("end")),
        "source_id": chosen.get("source_id"),
    }


def _iso_or_none(dt: object) -> str | None:
    """ISO-8601 string for a date/datetime, else None — JSON-safe for the panel."""
    isoformat = getattr(dt, "isoformat", None)
    return isoformat() if callable(isoformat) else None
