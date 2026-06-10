"""
v0.2 enhancement tests — E1 milestones, E2 expected band + agent detection,
E3 velocity/flags, A6 same-day dedup, payload/validation extensions.

Kept separate from test_cardiometabolic.py so the v0.1 suite stays
byte-untouched (approval A7). Mocked at the SDK boundary, same as v0.1.

Reminder from v0.1: mocked tests cannot catch SDK field-name drift — live
validation (Section 5 of the spec) is the second gate.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

try:
    from protocols.growth_charts import (
        DEFAULT_AGENT,
        EXPECTED_RESPONSE_BANDS,
        FLAG_DEFINITIONS,
        assemble_template_context,
        build_chart_data,
        build_expected_band,
        build_velocity_stats,
        compute_milestone_lines,
        compute_velocity,
        dedupe_same_day,
        detect_flags,
        detect_glp1_agent,
        validate_chart_payload,
    )
    PROTOCOL_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - mirrors v0.1 skip pattern
    PROTOCOL_AVAILABLE = False
    IMPORT_ERROR = str(exc)


# Anchored well in the past: long fixture series (28+ weeks) must never reach
# "today", or validation's future-date check fires.
START = datetime(2025, 1, 6, 9, 0, 0)


def dp(week: float, tbwl: float, value_lbs: float = 200.0) -> dict:
    """Minimal processed-datapoint dict for velocity/flag functions."""
    return {
        "weeks_since_baseline": week,
        "tbwl_pct": tbwl,
        "value_lbs": value_lbs,
        "date_obj": START + timedelta(weeks=week),
    }


def series_from_weights(baseline: float, weights_by_week: list) -> list[dict]:
    """[(week, weight_lbs), ...] → processed-datapoint dicts with real TBWL."""
    return [
        dp(week, ((baseline - w) / baseline) * 100.0, w)
        for week, w in weights_by_week
    ]


def raw_obs(obs_id: str, value: float, unit: str, day: int) -> dict:
    """Raw loader-shaped dict (legacy build_chart_data path: dates attached)."""
    return {
        "id": obs_id,
        "value_original": value,
        "unit_original": unit,
        "canvas_note_id": f"n-{obs_id}",
        "datetime_of_service": START + timedelta(days=day),
        "_loaded_at": START.isoformat(),
    }


class V02TestCase(unittest.TestCase):
    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol module not importable: {IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# E1 — milestone lines
# ---------------------------------------------------------------------------

class TestMilestoneLines(V02TestCase):
    def test_milestone_weights_from_baseline(self):
        # Wide axis so nothing is suppressed.
        lines = compute_milestone_lines(220.0, [180.0, 225.0], latest_tbwl_pct=12.1)
        self.assertEqual([m["pct"] for m in lines], [5.0, 10.0, 15.0])
        self.assertAlmostEqual(lines[0]["weight_lbs"], 209.0)
        self.assertAlmostEqual(lines[1]["weight_lbs"], 198.0)
        self.assertAlmostEqual(lines[2]["weight_lbs"], 187.0)
        self.assertEqual(lines[0]["label"], "5% TBWL")

    def test_crossed_flag_tracks_latest_tbwl(self):
        lines = compute_milestone_lines(220.0, [180.0, 225.0], latest_tbwl_pct=12.1)
        crossed = {m["pct"]: m["crossed"] for m in lines}
        self.assertTrue(crossed[5.0])
        self.assertTrue(crossed[10.0])
        self.assertFalse(crossed[15.0])

    def test_suppressed_outside_axis_range(self):
        # P2 shape without band: weights 239.9-245, pad=2 → domain [237.9, 247].
        # 5% of 245 = 232.75 → below the domain → suppressed.
        lines = compute_milestone_lines(245.0, [239.9, 245.0], latest_tbwl_pct=2.1)
        self.assertEqual(lines, [])

    def test_band_extended_axis_reveals_milestones(self):
        # P2 with the STEP-1 band pulling the axis down to ~215 lbs:
        # 5% (232.75) and 10% (220.5) visible, 15% (208.25) still suppressed.
        lines = compute_milestone_lines(245.0, [239.9, 245.0, 215.0], latest_tbwl_pct=2.1)
        self.assertEqual([m["pct"] for m in lines], [5.0, 10.0])
        self.assertFalse(any(m["crossed"] for m in lines))

    def test_single_observation_suppresses_all(self):
        # P7: single weight 198 → domain [196, 200]; 5% line at 188.1 is out.
        lines = compute_milestone_lines(198.0, [198.0], latest_tbwl_pct=0.0)
        self.assertEqual(lines, [])

    def test_invalid_baseline_returns_empty(self):
        self.assertEqual(compute_milestone_lines(0.0, [100.0, 200.0]), [])
        self.assertEqual(compute_milestone_lines(None, [100.0, 200.0]), [])
        self.assertEqual(compute_milestone_lines(220.0, []), [])


# ---------------------------------------------------------------------------
# E2 — expected-response band
# ---------------------------------------------------------------------------

class TestExpectedBand(V02TestCase):
    def test_step1_values_at_table_weeks(self):
        band = build_expected_band(200.0, START, 68.0, "semaglutide_step1")
        self.assertEqual(band["label"], "STEP-1")
        by_week = {p["week"]: p for p in band["points"]}
        self.assertAlmostEqual(by_week[12.0]["lower_pct"], 2.0)
        self.assertAlmostEqual(by_week[12.0]["upper_pct"], 11.0)
        self.assertAlmostEqual(by_week[12.0]["lower_lbs"], 196.0)
        self.assertAlmostEqual(by_week[12.0]["upper_lbs"], 178.0)

    def test_linear_interpolation_between_rows(self):
        # STEP-1 week 14, halfway between week 12 (2.0-11.0) and 16 (3.0-13.5).
        band = build_expected_band(200.0, START, 14.0, "semaglutide_step1")
        last = band["points"][-1]
        self.assertAlmostEqual(last["week"], 14.0)
        self.assertAlmostEqual(last["lower_pct"], 2.5)
        self.assertAlmostEqual(last["upper_pct"], 12.25)

    def test_band_clipped_to_observed_span(self):
        band = build_expected_band(200.0, START, 10.0, "semaglutide_step1")
        self.assertTrue(all(p["week"] <= 10.0 for p in band["points"]))
        self.assertAlmostEqual(band["points"][-1]["week"], 10.0)

    def test_no_band_for_zero_span(self):
        band = build_expected_band(200.0, START, 0.0, "semaglutide_step1")
        self.assertEqual(band["points"], [])
        self.assertEqual(band["label"], "STEP-1")

    def test_unknown_agent_falls_back_to_default(self):
        band = build_expected_band(200.0, START, 24.0, "not_a_real_agent")
        self.assertEqual(band["agent"], DEFAULT_AGENT)
        self.assertEqual(band["label"], "STEP-1")

    def test_per_agent_table_selection(self):
        tz = build_expected_band(200.0, START, 24.0, "tirzepatide_surmount1")
        self.assertEqual(tz["label"], "SURMOUNT-1")
        by_week = {p["week"]: p for p in tz["points"]}
        self.assertAlmostEqual(by_week[24.0]["lower_pct"], 8.0)
        self.assertAlmostEqual(by_week[24.0]["upper_pct"], 22.0)

        lira = build_expected_band(200.0, START, 24.0, "liraglutide_scale")
        self.assertEqual(lira["label"], "SCALE")
        by_week = {p["week"]: p for p in lira["points"]}
        self.assertAlmostEqual(by_week[24.0]["lower_pct"], 3.2)
        self.assertAlmostEqual(by_week[24.0]["upper_pct"], 9.6)

    def test_band_dates_anchor_to_baseline(self):
        band = build_expected_band(200.0, START, 12.0, "semaglutide_step1")
        by_week = {p["week"]: p for p in band["points"]}
        self.assertEqual(by_week[4.0]["date"], START + timedelta(weeks=4))


# ---------------------------------------------------------------------------
# A3 — GLP-1 agent detection (Medication mocked at the SDK boundary)
# ---------------------------------------------------------------------------

def _mock_medication(*display_texts):
    med = MagicMock()
    codings = []
    for text in display_texts:
        coding = MagicMock()
        coding.display = text
        codings.append(coding)
    med.codings.all.return_value = codings
    return med


class TestAgentDetection(V02TestCase):
    def _detect_with(self, MockMedication, meds):
        MockMedication.objects.for_patient.return_value.active.return_value = meds
        return detect_glp1_agent("patient-1")

    @patch("protocols.growth_charts.Medication")
    def test_semaglutide_brand_detected(self, MockMedication):
        agent = self._detect_with(
            MockMedication, [_mock_medication("Wegovy 2.4 mg/0.75 mL subcutaneous")]
        )
        self.assertEqual(agent, "semaglutide_step1")

    @patch("protocols.growth_charts.Medication")
    def test_tirzepatide_detected(self, MockMedication):
        agent = self._detect_with(
            MockMedication, [_mock_medication("Zepbound 10 MG in 0.5 ML injection")]
        )
        self.assertEqual(agent, "tirzepatide_surmount1")

    @patch("protocols.growth_charts.Medication")
    def test_liraglutide_generic_detected(self, MockMedication):
        agent = self._detect_with(
            MockMedication, [_mock_medication("liraglutide 6 mg/mL (Saxenda)")]
        )
        self.assertEqual(agent, "liraglutide_scale")

    @patch("protocols.growth_charts.Medication")
    def test_no_match_falls_back_to_default(self, MockMedication):
        agent = self._detect_with(
            MockMedication, [_mock_medication("metformin 500 mg tablet")]
        )
        self.assertEqual(agent, DEFAULT_AGENT)

    @patch("protocols.growth_charts.Medication")
    def test_no_medications_falls_back_to_default(self, MockMedication):
        agent = self._detect_with(MockMedication, [])
        self.assertEqual(agent, DEFAULT_AGENT)

    @patch("protocols.growth_charts.Medication")
    def test_multiple_agents_fall_back_to_default(self, MockMedication):
        agent = self._detect_with(
            MockMedication,
            [_mock_medication("Wegovy 2.4 mg"), _mock_medication("Zepbound 10 mg")],
        )
        self.assertEqual(agent, DEFAULT_AGENT)

    @patch("protocols.growth_charts.Medication")
    def test_query_error_degrades_to_default(self, MockMedication):
        MockMedication.objects.for_patient.side_effect = RuntimeError("schema surprise")
        self.assertEqual(detect_glp1_agent("patient-1"), DEFAULT_AGENT)

    @patch("protocols.growth_charts.Medication")
    def test_missing_codings_attribute_degrades_to_default(self, MockMedication):
        med = MagicMock(spec=[])  # no .codings at all
        MockMedication.objects.for_patient.return_value.active.return_value = [med]
        self.assertEqual(detect_glp1_agent("patient-1"), DEFAULT_AGENT)


# ---------------------------------------------------------------------------
# E3 — velocity
# ---------------------------------------------------------------------------

class TestVelocity(V02TestCase):
    def test_regular_weekly_spacing_rapid_shape(self):
        # P4: weekly weights from 260 for 10 weeks.
        weights = [260.0, 256.2, 252.5, 248.9, 245.3, 241.8, 238.4, 235.0, 231.7, 228.5, 225.4]
        pts = series_from_weights(260.0, list(enumerate(weights)))
        v = compute_velocity(pts)
        # trailing 4 weeks: week 6 (238.4) → week 10 (225.4) = 5.0 %TBWL / 4 wk
        self.assertAlmostEqual(v, 1.25, places=2)

    def test_irregular_spacing_interpolates(self):
        pts = [dp(0, 0.0), dp(3, 1.0), dp(9.5, 5.0), dp(10, 6.0)]
        v = compute_velocity(pts)
        # TBWL at week 6 interpolated between (3, 1.0) and (9.5, 5.0) = 2.846
        self.assertAlmostEqual(v, (6.0 - 2.8461538) / 4.0, places=4)

    def test_under_14_day_span_returns_none(self):
        pts = [dp(0, 0.0), dp(1.5, 0.5)]  # 10.5 days
        self.assertIsNone(compute_velocity(pts))

    def test_exactly_14_day_span_qualifies(self):
        pts = [dp(0, 0.0), dp(2, 0.8)]
        self.assertAlmostEqual(compute_velocity(pts), 0.4)

    def test_single_observation_returns_none(self):
        self.assertIsNone(compute_velocity([dp(0, 0.0)]))
        self.assertIsNone(compute_velocity([]))

    def test_sparse_two_point_series(self):
        # P6: 240.0 → 233.5 over 90 days (12.857 weeks) — qualifies per the
        # ≥14-day rule and yields the interpolated linear rate.
        weeks = 90.0 / 7.0
        tbwl = ((240.0 - 233.5) / 240.0) * 100.0
        pts = [dp(0, 0.0, 240.0), dp(weeks, tbwl, 233.5)]
        self.assertAlmostEqual(compute_velocity(pts), tbwl / weeks, places=4)

    def test_display_formatting(self):
        self.assertEqual(build_velocity_stats(None)["display"], "—")
        self.assertEqual(build_velocity_stats(0.19)["display"], "-0.19%/wk")
        # Gaining weight → positive display value.
        self.assertEqual(build_velocity_stats(-0.30)["display"], "0.30%/wk")


# ---------------------------------------------------------------------------
# E3 — plateau / regain / rapid flags
# ---------------------------------------------------------------------------

P1_WEIGHTS = [220.0, 218.1, 216.4, 214.0, 211.8, 209.4, 207.2, 205.1,
              202.9, 200.6, 198.0, 196.4, 195.1, 194.0, 193.4]
P2_WEIGHTS = [245.0, 244.2, 243.5, 243.0, 242.1, 241.4, 240.6, 239.9]
P3_WEIGHTS = [232.0, 229.8, 227.1, 224.6, 222.0, 219.5, 217.4, 215.8,
              215.3, 215.0, 214.8, 214.7, 214.6, 214.6, 214.5]
P4_WEIGHTS = [260.0, 256.2, 252.5, 248.9, 245.3, 241.8, 238.4, 235.0,
              231.7, 228.5, 225.4]
P5_WEIGHTS = [215.0, 212.4, 209.7, 206.9, 204.3, 202.0, 199.5, 197.3,
              195.7, 197.0, 199.2, 201.6, 204.0, 206.5]


def biweekly(weights: list[float]) -> list[tuple]:
    return [(i * 2, w) for i, w in enumerate(weights)]


class TestFlags(V02TestCase):
    def _flags_for(self, baseline, weights_by_week):
        pts = series_from_weights(baseline, weights_by_week)
        return {f["key"] for f in detect_flags(pts, compute_velocity(pts))}

    def test_plateau_fires_on_p3_shape(self):
        self.assertEqual(self._flags_for(232.0, biweekly(P3_WEIGHTS)), {"plateau"})

    def test_no_flag_on_p2_slow_steady_loss(self):
        # Trailing-8-week loss is ~1.27% (> 0.5) — magnitude rule, not the
        # week-8 gate, is what spares P2 at week 14.
        self.assertEqual(self._flags_for(245.0, biweekly(P2_WEIGHTS)), set())

    def test_regain_fires_on_p5_not_plateau(self):
        self.assertEqual(self._flags_for(215.0, biweekly(P5_WEIGHTS)), {"regain"})

    def test_rapid_fires_on_p4_weekly_loss(self):
        self.assertEqual(
            self._flags_for(260.0, list(enumerate(P4_WEIGHTS))), {"rapid_loss"}
        )

    def test_no_flags_on_p1_responder(self):
        self.assertEqual(self._flags_for(220.0, biweekly(P1_WEIGHTS)), set())

    def test_flat_series_before_week_8_does_not_plateau(self):
        flat = [(0, 230.0), (2, 230.0), (4, 229.9), (6, 230.0)]
        self.assertEqual(self._flags_for(230.0, flat), set())

    def test_insufficient_data_yields_no_flags(self):
        pts = [dp(0, 0.0)]
        self.assertEqual(detect_flags(pts, None), [])

    def test_flag_copy_is_descriptive_not_directive(self):
        for flag in FLAG_DEFINITIONS.values():
            msg = flag["message"].lower()
            self.assertNotIn("increase", msg)
            self.assertNotIn("prescribe", msg)
            self.assertIn("consider", msg)


# ---------------------------------------------------------------------------
# A6 — same-day dedup
# ---------------------------------------------------------------------------

class TestSameDayDedup(V02TestCase):
    def test_p9_same_day_duplicates_averaged(self):
        obs = [
            raw_obs("a", 250.0, "lbs", 0),
            raw_obs("b", 247.0, "lbs", 14),
            raw_obs("c", 246.4, "lbs", 14),
            raw_obs("d", 244.0, "lbs", 28),
        ]
        payload = build_chart_data(obs, None)
        self.assertEqual(len(payload["datapoints"]), 3)
        self.assertAlmostEqual(payload["datapoints"][1]["value_lbs"], 246.7)

    def test_mixed_unit_same_day_averaged_in_lbs(self):
        merged = dedupe_same_day([
            raw_obs("a", 100.0, "kg", 0),       # 220.462 lbs
            raw_obs("b", 220.0, "lbs", 0),
        ])
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["value_original"], 220.231, places=3)
        self.assertEqual(merged[0]["unit_original"], "lbs")
        self.assertEqual(merged[0]["deduped_from"], ["a", "b"])

    def test_distinct_days_untouched(self):
        obs = [raw_obs("a", 250.0, "lbs", 0), raw_obs("b", 248.0, "lbs", 7)]
        self.assertEqual(dedupe_same_day(obs), obs)

    def test_velocity_not_distorted_by_duplicates(self):
        obs = [
            raw_obs("a", 250.0, "lbs", 0),
            raw_obs("b", 247.0, "lbs", 14),
            raw_obs("c", 246.4, "lbs", 14),
            raw_obs("d", 244.0, "lbs", 28),
        ]
        payload = build_chart_data(obs, None)
        weeks = [p["weeks_since_baseline"] for p in payload["datapoints"]]
        self.assertEqual(len(weeks), len(set(weeks)), "duplicate week present")
        self.assertIsNotNone(payload["velocity_stats"]["velocity_pct_per_week"])


# ---------------------------------------------------------------------------
# P8 — mixed-unit normalization (the obs.units regression shape)
# ---------------------------------------------------------------------------

class TestMixedUnits(V02TestCase):
    def test_p8_series_normalizes_to_lbs(self):
        series = [
            ("a", 104.3, "kg", 0),
            ("b", 228.0, "lb", 14),
            ("c", 102.1, "kg", 28),
            ("d", 223.0, "lb", 42),
            ("e", 100.2, "kg", 56),
            ("f", 219.0, "lb", 70),
        ]
        payload = build_chart_data([raw_obs(*row) for row in series], None)
        values = [p["value_lbs"] for p in payload["datapoints"]]
        # All within a single plausible lbs range — no ~100 kg-scale values.
        self.assertTrue(all(200.0 < v < 235.0 for v in values))
        # Monotonic-ish downward trend once normalized.
        self.assertTrue(all(values[i] > values[i + 1] for i in range(len(values) - 1)))
        baseline_lbs = 104.3 * 2.20462
        expected_tbwl = ((baseline_lbs - 219.0) / baseline_lbs) * 100.0
        self.assertAlmostEqual(payload["latest_tbwl_pct"], expected_tbwl, places=3)


# ---------------------------------------------------------------------------
# Payload integration + validation + context
# ---------------------------------------------------------------------------

class TestV02Payload(V02TestCase):
    def _p1_payload(self):
        obs = [
            raw_obs(f"p1-{i}", w, "lbs", i * 14)
            for i, w in enumerate(P1_WEIGHTS)
        ]
        return build_chart_data(obs, None, agent="semaglutide_step1")

    def test_payload_carries_all_v02_keys(self):
        payload = self._p1_payload()
        for key in ("milestones", "expected_band", "velocity_stats", "flags"):
            self.assertIn(key, payload)
        is_valid, errors = validate_chart_payload(payload)
        self.assertTrue(is_valid, errors)

    def test_p1_milestones_include_crossed_5_and_10(self):
        payload = self._p1_payload()
        crossed = {m["pct"] for m in payload["milestones"] if m["crossed"]}
        self.assertEqual(crossed, {5.0, 10.0})

    def test_single_observation_degrades_cleanly(self):
        payload = build_chart_data([raw_obs("only", 198.0, "lbs", 0)], None)
        self.assertEqual(payload["expected_band"]["points"], [])
        self.assertEqual(payload["milestones"], [])
        self.assertEqual(payload["flags"], [])
        self.assertEqual(payload["velocity_stats"]["display"], "—")
        is_valid, errors = validate_chart_payload(payload)
        self.assertTrue(is_valid, errors)

    def test_empty_observations_still_raise(self):
        # Unchanged v0.1 behavior: the handler converts this to an error modal.
        with self.assertRaises(ValueError):
            build_chart_data([], None)

    def test_validation_flags_malformed_v02_keys(self):
        payload = self._p1_payload()
        payload["milestones"] = "not-a-list"
        payload["expected_band"] = {"oops": True}
        payload["velocity_stats"] = {"no_display": True}
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)
        joined = " ".join(errors)
        self.assertIn("milestones", joined)
        self.assertIn("expected_band", joined)
        self.assertIn("velocity_stats", joined)

    def test_legacy_payload_without_v02_keys_still_valid(self):
        payload = self._p1_payload()
        for key in ("milestones", "expected_band", "velocity_stats", "flags"):
            del payload[key]
        is_valid, errors = validate_chart_payload(payload)
        self.assertTrue(is_valid, errors)

    def test_context_defaults_for_legacy_callers(self):
        payload = self._p1_payload()
        context = assemble_template_context(
            patient={"patient_id": "x"},
            baseline=payload["baseline_data"],
            datapoints=payload["datapoints"],
            pipeline_timestamps=payload["_pipeline_timestamps"],
        )
        self.assertEqual(context["milestones"], [])
        self.assertEqual(context["velocity_stats"]["display"], "—")
        self.assertFalse(context["chart_config"]["show_benchmark_overlay"])
        self.assertEqual(
            context["chart_config"]["legend_text"], "Expected response (STEP-1)"
        )

    def test_context_legend_follows_detected_agent(self):
        obs = [raw_obs(f"p3-{i}", w, "lbs", i * 14) for i, w in enumerate(P3_WEIGHTS)]
        payload = build_chart_data(obs, None, agent="tirzepatide_surmount1")
        context = assemble_template_context(
            patient={"patient_id": "x"},
            baseline=payload["baseline_data"],
            datapoints=payload["datapoints"],
            pipeline_timestamps=payload["_pipeline_timestamps"],
            milestones=payload["milestones"],
            expected_band=payload["expected_band"],
            velocity_stats=payload["velocity_stats"],
            flags=payload["flags"],
        )
        self.assertEqual(
            context["chart_config"]["legend_text"], "Expected response (SURMOUNT-1)"
        )
        self.assertTrue(context["chart_config"]["show_benchmark_overlay"])
        self.assertEqual({f["key"] for f in context["flags"]}, {"plateau"})


if __name__ == "__main__":
    unittest.main()
