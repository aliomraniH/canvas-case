"""
tests/test_phase1_provenance.py
===============================
Phase 1a — read-time provenance derivation.

Pure-logic tests (no Canvas SDK): they run without a live instance. Each of the
four provenance branches is exercised, including the ambiguous "Unknown source"
fallback the spec explicitly calls for.

Mocks use SimpleNamespace (NOT unittest.mock.Mock): Mock auto-creates a truthy
value for every attribute access, which would make `getattr(obj, attr, None)`
match every candidate field and defeat the branch logic. SimpleNamespace raises
AttributeError for unset attrs, so `getattr(..., None)` returns None as real
SDK objects would for absent fields.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocols.provenance import (  # noqa: E402
    PROVENANCE_AUTOMATIC,
    PROVENANCE_CARE_TEAM,
    PROVENANCE_SELF_ENTERED,
    PROVENANCE_UNKNOWN,
    derive_provenance,
)


class TestProvenanceBranches(unittest.TestCase):
    def test_automatic_scale_when_observation_has_device(self):
        obs = SimpleNamespace(device="scale-serial-123")
        self.assertEqual(derive_provenance(obs=obs), PROVENANCE_AUTOMATIC)

    def test_care_team_when_note_has_practitioner_author(self):
        note = SimpleNamespace(provider="Dr. Reyes")
        self.assertEqual(derive_provenance(note=note), PROVENANCE_CARE_TEAM)

    def test_care_team_when_manual_baseline_metadata_has_enrolled_by(self):
        # Provider-entered manual baseline (v0.5.0) — metadata as a dict.
        meta = {"enrolled_by": "staff-7"}
        self.assertEqual(derive_provenance(metadata=meta), PROVENANCE_CARE_TEAM)

    def test_care_team_when_metadata_object_has_enrolled_by(self):
        meta = SimpleNamespace(enrolled_by="staff-7")
        self.assertEqual(derive_provenance(metadata=meta), PROVENANCE_CARE_TEAM)

    def test_self_entered_when_note_origin_is_patient_portal(self):
        note = SimpleNamespace(origin="patient-portal questionnaire")
        self.assertEqual(derive_provenance(note=note), PROVENANCE_SELF_ENTERED)

    def test_self_entered_when_note_flag_entered_by_patient(self):
        note = SimpleNamespace(entered_by_patient=True)
        self.assertEqual(derive_provenance(note=note), PROVENANCE_SELF_ENTERED)

    def test_unknown_source_is_the_ambiguous_fallback(self):
        # No device, no author, no patient-report signal anywhere.
        note = SimpleNamespace(datetime_of_service="2024-01-01")
        self.assertEqual(
            derive_provenance(obs=SimpleNamespace(), note=note, metadata=None),
            PROVENANCE_UNKNOWN,
        )

    def test_unknown_when_everything_is_none(self):
        self.assertEqual(derive_provenance(), PROVENANCE_UNKNOWN)


class TestProvenancePrecedence(unittest.TestCase):
    def test_device_beats_care_team_and_self(self):
        obs = SimpleNamespace(device="scale-x")
        note = SimpleNamespace(provider="Dr. Reyes", origin="patient-portal")
        self.assertEqual(derive_provenance(obs=obs, note=note), PROVENANCE_AUTOMATIC)

    def test_care_team_beats_self_entered(self):
        # A note authored by a practitioner that also carries a portal origin
        # classifies as care-team (author signal wins over origin).
        note = SimpleNamespace(provider="Dr. Reyes", origin="patient-portal")
        self.assertEqual(derive_provenance(note=note), PROVENANCE_CARE_TEAM)

    def test_empty_metadata_dict_does_not_force_care_team(self):
        note = SimpleNamespace(origin="patient self-report")
        self.assertEqual(
            derive_provenance(note=note, metadata={"enrolled_by": ""}),
            PROVENANCE_SELF_ENTERED,
        )


if __name__ == "__main__":
    unittest.main()
