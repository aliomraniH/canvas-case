"""
tests/test_phase1_dose.py
=========================
Phase 1b — point-in-time GLP-1 dose lookup.

The resolver ``dose_covering_date`` is pure and carries the spec's four cases:
covers-the-date / before-any-dose / gap-between-doses / multiple-overlapping
(return the most recent). The SDK-touching loader is exercised against a stubbed
``canvas_sdk.v1.data`` so it runs with no live instance — verifying it filters
non-GLP-1 meds and extracts the coverage period via a single query path.

NB: the live Medication coverage-period field path is UNVERIFIED against 0.163.x
(Bundle A decision); CLI confirms it before deploy. These tests pin the resolver
LOGIC, which is independent of the eventual field name.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocols.dose_at_time import dose_covering_date  # noqa: E402

_KEYWORDS = {
    "semaglutide_step1": ("semaglutide", "wegovy", "ozempic"),
    "tirzepatide_surmount1": ("tirzepatide", "zepbound", "mounjaro"),
}


def _period(agent, drug, start, end, dose=None, source_id="med-x"):
    return {
        "agent": agent,
        "drug": drug,
        "dose": dose,
        "start": start,
        "end": end,
        "source_id": source_id,
    }


class TestDoseCoveringDate(unittest.TestCase):
    def setUp(self):
        self.p1 = _period(
            "semaglutide_step1", "Semaglutide (Wegovy)",
            datetime(2024, 1, 1), datetime(2024, 3, 1), dose="1.0 mg weekly",
        )
        self.p2 = _period(
            "tirzepatide_surmount1", "Tirzepatide (Zepbound)",
            datetime(2024, 4, 1), None, dose="5 mg weekly",   # open-ended (current)
        )

    def test_date_covered_by_one_period(self):
        result = dose_covering_date([self.p1, self.p2], datetime(2024, 2, 1))
        self.assertIsNotNone(result)
        self.assertEqual(result["agent"], "semaglutide_step1")
        self.assertEqual(result["drug"], "Semaglutide (Wegovy)")
        self.assertEqual(result["dose"], "1.0 mg weekly")

    def test_date_before_any_dose_returns_none(self):
        self.assertIsNone(dose_covering_date([self.p1, self.p2], datetime(2023, 12, 1)))

    def test_date_in_gap_between_doses_returns_none(self):
        # p1 ends 2024-03-01, p2 starts 2024-04-01 — 2024-03-15 is uncovered.
        self.assertIsNone(dose_covering_date([self.p1, self.p2], datetime(2024, 3, 15)))

    def test_multiple_overlapping_returns_most_recent(self):
        overlap = _period(
            "tirzepatide_surmount1", "Tirzepatide (later switch)",
            datetime(2024, 1, 15), datetime(2024, 5, 1), source_id="med-newer",
        )
        # 2024-02-01 is covered by both p1 (start 01-01) and overlap (start 01-15);
        # the most recent start wins.
        result = dose_covering_date([self.p1, overlap], datetime(2024, 2, 1))
        self.assertEqual(result["source_id"], "med-newer")
        self.assertEqual(result["drug"], "Tirzepatide (later switch)")

    def test_open_ended_period_covers_later_dates(self):
        result = dose_covering_date([self.p1, self.p2], datetime(2024, 6, 1))
        self.assertEqual(result["agent"], "tirzepatide_surmount1")
        self.assertIsNone(result["period_end"])

    def test_returns_iso_period_bounds(self):
        result = dose_covering_date([self.p1], datetime(2024, 2, 1))
        self.assertEqual(result["period_start"], "2024-01-01T00:00:00")
        self.assertEqual(result["period_end"], "2024-03-01T00:00:00")

    def test_none_target_and_empty_periods(self):
        self.assertIsNone(dose_covering_date([self.p1], None))
        self.assertIsNone(dose_covering_date([], datetime(2024, 2, 1)))


# ── Loader (SDK glue) against a stubbed canvas_sdk ──


class _FakeCodings:
    def __init__(self, displays):
        self._displays = displays

    def all(self):
        return [types.SimpleNamespace(display=d) for d in self._displays]


class _FakeMed:
    def __init__(self, displays, **attrs):
        self.codings = _FakeCodings(displays)
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeQuerySet(list):
    def for_patient(self, _patient_id):
        return self

    def prefetch_related(self, *_args):
        return self


class TestLoadGlp1MedicationPeriods(unittest.TestCase):
    def _install_stub(self, meds):
        data_mod = types.ModuleType("canvas_sdk.v1.data")

        class Medication:
            objects = _FakeQuerySet(meds)

        data_mod.Medication = Medication
        v1_mod = types.ModuleType("canvas_sdk.v1")
        v1_mod.data = data_mod
        root_mod = types.ModuleType("canvas_sdk")
        root_mod.v1 = v1_mod
        self._saved = {k: sys.modules.get(k) for k in
                       ("canvas_sdk", "canvas_sdk.v1", "canvas_sdk.v1.data")}
        sys.modules["canvas_sdk"] = root_mod
        sys.modules["canvas_sdk.v1"] = v1_mod
        sys.modules["canvas_sdk.v1.data"] = data_mod

    def tearDown(self):
        for key, value in getattr(self, "_saved", {}).items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    def test_filters_non_glp1_and_extracts_period(self):
        meds = [
            _FakeMed(["Semaglutide 1mg"], start_date=datetime(2024, 1, 1),
                     end_date=datetime(2024, 3, 1), id="med-1", quantity="1 mg"),
            _FakeMed(["Lisinopril 10mg"], id="med-2"),  # not a GLP-1 → excluded
        ]
        self._install_stub(meds)
        from protocols.dose_at_time import load_glp1_medication_periods

        periods = load_glp1_medication_periods("patient-1", _KEYWORDS)
        self.assertEqual(len(periods), 1)
        period = periods[0]
        self.assertEqual(period["agent"], "semaglutide_step1")
        self.assertEqual(period["start"], datetime(2024, 1, 1))
        self.assertEqual(period["end"], datetime(2024, 3, 1))
        self.assertEqual(period["source_id"], "med-1")
        self.assertEqual(period["dose"], "1 mg")

    def test_missing_period_attrs_degrade_to_open_ended(self):
        meds = [_FakeMed(["Tirzepatide 5mg"], id="med-3")]
        self._install_stub(meds)
        from protocols.dose_at_time import load_glp1_medication_periods

        periods = load_glp1_medication_periods("patient-1", _KEYWORDS)
        self.assertEqual(len(periods), 1)
        self.assertIsNone(periods[0]["start"])
        self.assertIsNone(periods[0]["end"])
        # Open-ended period covers any date → resolver still returns it.
        result = dose_covering_date(periods, datetime(2024, 2, 1))
        self.assertEqual(result["agent"], "tirzepatide_surmount1")


if __name__ == "__main__":
    unittest.main()
