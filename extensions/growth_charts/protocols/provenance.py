"""Phase 1a — read-time provenance derivation for a weight Observation.

Classifies how a weight measurement entered the record. Derived at READ time
from the fields Canvas SDK 0.163.x actually exposes — NEVER persisted as a
separate source flag (the spec forbids a stored flag, and Observations are
immutable anyway).

IMPORTANT — re-scoped from the original spec (Bundle A decision, this session):
The spec's 1a wanted to read ``Observation.device`` / ``Observation.performer``.
Neither field exists on the SDK Observation model in 0.163.x (confirmed by
``canvas-sdk-tools:capability`` and the build-discipline Gate-1 known-facts list:
Observation has only ``patient, is_member_of, category, units, value, note_id,
name, effective_datetime`` + audit/id fields). So provenance is derived from the
signals that DO exist:

  * the linked Note's author/origin (care-team vs patient-reported), and
  * the v0.5.0 provider-entered manual-baseline metadata (``enrolled_by``).

CLI-VERIFIED (v0.6.0 deploy, 2026-06-24) against live SDK 0.163.1
(canvas_sdk/v1/data/note.py): the ``Note`` model exposes ``provider`` (FK) — it
leads ``_NOTE_AUTHOR_ATTRS`` and drives the "Care-team entry" branch. NONE of
``origin`` / ``source`` / ``entered_by_patient`` / ``patient_reported`` exist,
and ``note_type`` (a ``NoteTypes`` choice) carries no patient-portal/self-report
value — so "Patient self-entered" has no reliable live signal in 0.163.x, and a
point with no care-team author classifies "Unknown source" (the honest,
non-fabricated fallback rather than a guessed label). The trailing tuple names
are kept as forward-compat fallbacks; the constants stay centralized so any
future correction is a one-line edit.
"""

from __future__ import annotations

# Stable label set (also the public contract the panel renders).
PROVENANCE_AUTOMATIC = "Automatic scale"
PROVENANCE_SELF_ENTERED = "Patient self-entered"
PROVENANCE_CARE_TEAM = "Care-team entry"
PROVENANCE_UNKNOWN = "Unknown source"

# SDK attribute names. CLI-verified against live SDK 0.163.1 (v0.6.0): Note
# exposes `provider` (leads _NOTE_AUTHOR_ATTRS); none of the _NOTE_ORIGIN_ATTRS
# exist live, so they are forward-compat only. Centralized so any future
# correction is a single edit, not a code hunt.
_DEVICE_HINT_ATTRS = ("device", "device_id")  # absent in 0.163.x; forward-compat
_NOTE_AUTHOR_ATTRS = ("provider", "author", "practitioner", "created_by")
_NOTE_ORIGIN_ATTRS = ("origin", "source", "entered_by_patient", "patient_reported")

# Substrings (lowercased) on a note's origin/type that indicate a patient
# self-report channel (portal questionnaires, patient-reported flows).
_SELF_ENTRY_MARKERS = ("portal", "patient", "self", "questionnaire", "patient-reported")


def _has_device_hint(obs: object | None) -> bool:
    """True if the observation carries any device hint.

    In 0.163.x these attrs do not exist, so this is always False for live data;
    it keeps the "Automatic scale" branch reachable for forward-compat and tests.
    """
    if obs is None:
        return False
    for attr in _DEVICE_HINT_ATTRS:
        if getattr(obs, attr, None):
            return True
    return False


def _note_author_is_care_team(note: object | None) -> bool:
    """True if the linked Note names a staff/practitioner author."""
    if note is None:
        return False
    for attr in _NOTE_AUTHOR_ATTRS:
        if getattr(note, attr, None):
            return True
    return False


def _note_is_patient_reported(note: object | None) -> bool:
    """True if the linked Note's origin/type marks a patient self-report channel."""
    if note is None:
        return False
    for attr in _NOTE_ORIGIN_ATTRS:
        value = getattr(note, attr, None)
        if value is None:
            continue
        if value is True:
            return True
        text = str(value).strip().lower()
        if any(marker in text for marker in _SELF_ENTRY_MARKERS):
            return True
    return False


def _metadata_has_enrolled_by(metadata: object | None) -> bool:
    """True if the v0.5.0 manual-baseline metadata records a provider (enrolled_by).

    Accepts either a dict (``.get``) or an attribute-bearing object. Underscore
    and plain keys both read via ``.get()`` per the RestrictedPython rule.
    """
    if metadata is None:
        return False
    if isinstance(metadata, dict):
        return bool(metadata.get("enrolled_by"))
    return bool(getattr(metadata, "enrolled_by", None))


def derive_provenance(
    obs: object | None = None,
    note: object | None = None,
    metadata: object | None = None,
) -> str:
    """Classify a weight Observation's data provenance at read time.

    Resolution order (first match wins):
      1. Device hint on the observation        -> "Automatic scale"
      2. Care-team-authored Note, or a provider-entered manual baseline
                                                -> "Care-team entry"
      3. Patient self-report Note origin/type   -> "Patient self-entered"
      4. No discernible signal                  -> "Unknown source"

    All four branches are reachable via mocked Observation/Note/metadata shapes
    (see tests/test_phase1_provenance.py).
    """
    if _has_device_hint(obs):
        return PROVENANCE_AUTOMATIC
    if _note_author_is_care_team(note) or _metadata_has_enrolled_by(metadata):
        return PROVENANCE_CARE_TEAM
    if _note_is_patient_reported(note):
        return PROVENANCE_SELF_ENTERED
    return PROVENANCE_UNKNOWN
