"""
v0.3.0 export tests — print-summary stats block, milestone-status derivation,
disclosure survival, button visibility, version pairing.

Kept separate so the v0.1 and v0.2 suites stay byte-untouched. Mocked at the
SDK boundary, same as the earlier suites. Mocked tests cannot catch Canvas
runtime behavior (window.print availability, print CSS) — live Tier 0 on the
sandbox is the second gate.

# Verifies: v0.3.0 (export) — spec approved 2026-06-11
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SRC = (REPO_ROOT / "templates" / "chart.html").read_text(encoding="utf-8")
PROTOCOL_SRC = (REPO_ROOT / "protocols" / "growth_charts.py").read_text(encoding="utf-8")

try:
    from protocols.growth_charts import (
        EM_DASH,
        PLUGIN_VERSION,
        SCALE_BOUNDS_DISCLOSURE,
        GenerateVitalsGraphs,
        assemble_template_context,
        build_expected_band,
        build_export_summary,
        build_milestone_status,
        build_velocity_stats,
        compute_velocity,
        export_citations,
    )
    PROTOCOL_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - mirrors v0.1/v0.2 skip pattern
    PROTOCOL_AVAILABLE = False
    IMPORT_ERROR = str(exc)


# Anchored well in the past so long series never trip the future-date check.
START = datetime(2025, 1, 6, 9, 0, 0)


def dp(week: float, baseline: float, value_lbs: float) -> dict:
    """Processed-datapoint dict with real TBWL and a date_label."""
    date_obj = START + timedelta(weeks=week)
    return {
        "weeks_since_baseline": week,
        "tbwl_pct": ((baseline - value_lbs) / baseline) * 100.0,
        "value_lbs": value_lbs,
        "date_obj": date_obj,
        "date_label": date_obj.strftime("%b %Y"),
    }


def make_patient() -> dict:
    return {
        "patient_id": "pt-1",
        "first_name": "ZZTEST-GLP1-Margaret",
        "last_name": "Okafor",
        "birth_date": date(1980, 1, 1),
    }


class V03TestCase(unittest.TestCase):
    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not importable: {IMPORT_ERROR}")


class TestExportSummaryMapping(V03TestCase):
    """DoD: payload → stats-block mapping reuses the exact computed payload."""

    def _summary(self, agent="semaglutide_step1", flags=None):
        baseline = {"value_lbs": 220.0, "value": 220.0}
        points = [dp(0, 220.0, 220.0), dp(4, 220.0, 215.0),
                  dp(8, 220.0, 206.0), dp(12, 220.0, 196.0)]
        band = build_expected_band(220.0, START, 12.0, agent)
        velocity_stats = build_velocity_stats(compute_velocity(points))
        return build_export_summary(
            patient=make_patient(),
            baseline=baseline,
            datapoints=points,
            latest_tbwl_pct=points[-1]["tbwl_pct"],
            expected_band=band,
            velocity_stats=velocity_stats,
            flags=flags or [],
        ), points, velocity_stats

    def test_full_series_mapping(self):
        summary, points, velocity_stats = self._summary()
        self.assertEqual(summary["patient_name"], "ZZTEST-GLP1-Margaret Okafor")
        self.assertEqual(summary["patient_dob"], "1980-01-01")
        self.assertEqual(summary["plugin_version"], PLUGIN_VERSION)
        self.assertEqual(summary["baseline_display"], "220.0 lb")
        self.assertEqual(summary["baseline_date_label"], points[0]["date_label"])
        self.assertEqual(summary["latest_display"], "196.0 lb")
        self.assertEqual(summary["latest_date_label"], points[-1]["date_label"])
        # (220-196)/220 = 10.909…% lost, displayed loss-negative.
        self.assertEqual(summary["total_tbwl_display"], "-10.9% TBWL")
        self.assertEqual(summary["velocity_display"], velocity_stats["display"])
        self.assertNotEqual(summary["velocity_display"], EM_DASH)
        self.assertEqual(summary["agent"], "semaglutide_step1")
        self.assertEqual(summary["band_display"], "STEP-1")
        self.assertIsNone(summary["band_disclosure"])
        self.assertFalse(summary["estimated_bounds"])

    def test_flags_pass_through(self):
        summary, _, _ = self._summary(
            flags=[{"key": "rapid_loss", "label": "Rapid loss", "severity": "red"}]
        )
        self.assertEqual(summary["flags"], [{"label": "Rapid loss", "severity": "red"}])

    def test_context_carries_export_summary(self):
        # assemble_template_context exposes the block to the template.
        baseline = {"value_lbs": 220.0, "value": 220.0}
        points = [dp(0, 220.0, 220.0), dp(8, 220.0, 206.0)]
        ctx = assemble_template_context(
            patient=make_patient(), baseline=baseline, datapoints=points,
            pipeline_timestamps={},
        )
        self.assertIn("export_summary", ctx)
        self.assertEqual(ctx["export_summary"]["_component"], "export_summary")
        self.assertEqual(len(ctx["export_summary"]["citations"]), 3)


class TestMilestoneStatusDerivation(V03TestCase):
    """DoD: milestone status = first existing datapoint at/over the threshold."""

    def test_crossings_and_dates(self):
        points = [dp(0, 220.0, 220.0), dp(4, 220.0, 215.0),
                  dp(8, 220.0, 206.0), dp(12, 220.0, 196.0)]
        status = build_milestone_status(points)
        by_pct = {s["pct"]: s for s in status}
        self.assertEqual(sorted(by_pct), [5.0, 10.0, 15.0])
        # 5% first crossed at week 8 (6.36%), 10% at week 12 (10.9%), 15% never.
        self.assertTrue(by_pct[5.0]["reached"])
        self.assertEqual(by_pct[5.0]["date_label"], points[2]["date_label"])
        self.assertTrue(by_pct[10.0]["reached"])
        self.assertEqual(by_pct[10.0]["date_label"], points[3]["date_label"])
        self.assertFalse(by_pct[15.0]["reached"])
        self.assertEqual(by_pct[15.0]["date_label"], EM_DASH)

    def test_independent_of_axis_suppression(self):
        # All three thresholds always report, even when the chart's axis
        # domain would suppress the milestone *lines*.
        status = build_milestone_status([dp(0, 220.0, 220.0)])
        self.assertEqual(len(status), 3)
        self.assertTrue(all(not s["reached"] for s in status))


class TestSingleObservationDegrade(V03TestCase):
    """DoD: single-observation stats degrade to em-dashes, never blanks."""

    def test_single_observation(self):
        baseline = {"value_lbs": 220.0, "value": 220.0}
        points = [dp(0, 220.0, 220.0)]
        band = build_expected_band(220.0, START, 0.0)  # empty points by rule
        summary = build_export_summary(
            patient=make_patient(), baseline=baseline, datapoints=points,
            latest_tbwl_pct=0.0, expected_band=band,
            velocity_stats=build_velocity_stats(compute_velocity(points)),
            flags=[],
        )
        self.assertEqual(summary["velocity_display"], EM_DASH)
        for s in summary["milestone_status"]:
            self.assertFalse(s["reached"])
            self.assertEqual(s["date_label"], EM_DASH)
        # No blank fields anywhere in the block.
        for key, value in summary.items():
            if isinstance(value, str):
                self.assertNotEqual(value.strip(), "", f"blank field: {key}")

    def test_missing_name_and_dob_render_em_dash(self):
        summary = build_export_summary(
            patient={"patient_id": "pt-x"},
            baseline={"value_lbs": 220.0, "value": 220.0},
            datapoints=[dp(0, 220.0, 220.0)],
            latest_tbwl_pct=0.0,
            expected_band=build_expected_band(220.0, START, 0.0),
            velocity_stats=build_velocity_stats(None),
            flags=[],
        )
        self.assertEqual(summary["patient_name"], EM_DASH)
        self.assertEqual(summary["patient_dob"], EM_DASH)


class TestDisclosureSurvival(V03TestCase):
    """DoD: liraglutide's uncertainty disclosure survives into the export
    VERBATIM (shipped v0.2.5 strings — legend qualifier + full disclosure)."""

    def test_liraglutide_disclosure_verbatim(self):
        band = build_expected_band(220.0, START, 56.0, "liraglutide_scale")
        summary = build_export_summary(
            patient=make_patient(),
            baseline={"value_lbs": 220.0, "value": 220.0},
            datapoints=[dp(0, 220.0, 220.0), dp(56, 220.0, 202.0)],
            latest_tbwl_pct=8.18,
            expected_band=band,
            velocity_stats=build_velocity_stats(None),
            flags=[],
        )
        self.assertTrue(summary["estimated_bounds"])
        self.assertEqual(summary["band_disclosure"], SCALE_BOUNDS_DISCLOSURE)
        self.assertEqual(summary["band_display"], "SCALE, ±1 SD")
        # Template wires the disclosure into the print stats block.
        self.assertIn("band_disclosure", TEMPLATE_SRC)
        self.assertIn("cm-print-disclosure", TEMPLATE_SRC)

    def test_citations_shipped_order(self):
        citations = export_citations()
        self.assertEqual(len(citations), 3)
        for citation, author in zip(citations, ("Wilding", "Jastreboff", "Pi-Sunyer")):
            self.assertIn(author, citation)


class TestExportButtonVisibility(V03TestCase):
    """DoD: button present on the chart view, absent on the error view."""

    def test_button_absent_on_validation_blocked_error_view(self):
        handler = GenerateVitalsGraphs(Mock(), Mock())
        effects = handler._render_error(["No datapoints to render"])
        self.assertEqual(len(effects), 1)
        payload = str(getattr(effects[0], "payload", effects[0]))
        self.assertNotIn("cm-export-btn", payload)
        self.assertIn("Unable to render weight trajectory", payload)

    def test_button_present_in_chart_template(self):
        self.assertIn("cm-export-btn", TEMPLATE_SRC)
        self.assertIn("@media print", TEMPLATE_SRC)
        self.assertIn("window.print()", TEMPLATE_SRC)
        self.assertIn("export_summary", TEMPLATE_SRC)


class TestVersionAndHygiene(V03TestCase):
    def test_plugin_version_matches_manifest(self):
        manifest = json.loads(
            (REPO_ROOT / "CANVAS_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["plugin_version"], PLUGIN_VERSION)

    def test_no_stray_conversion_literals_incl_template(self):
        # v0.2.5 acceptance review finding 3: extend the stray-literal scan to
        # the template/JS and add the bare "2.2 " token. Conversion factors may
        # exist ONLY as KG_PER_LB / LB_PER_KG in the protocol module.
        sources = {"growth_charts.py": PROTOCOL_SRC, "chart.html": TEMPLATE_SRC}
        for token in ("2.2046", "0.4535", "2.20462", "0.00220462", "2.2 "):
            for name, src in sources.items():
                offending = []
                for ln in src.splitlines():
                    code = ln.split("#", 1)[0] if name.endswith(".py") else ln
                    if token in code and "KG_PER_LB" not in code and "LB_PER_KG" not in code:
                        offending.append(ln.strip())
                self.assertEqual(
                    offending, [], f"stray literal {token!r} in {name}: {offending}"
                )


if __name__ == "__main__":
    unittest.main()
