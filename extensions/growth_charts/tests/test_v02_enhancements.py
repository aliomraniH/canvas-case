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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

REFERENCE_PATH = Path(__file__).resolve().parent.parent / "glp1_science_reference.md"

try:
    from protocols.growth_charts import (
        AXIS_PAD_FRACTION,
        AXIS_PAD_MIN_LBS,
        DEFAULT_AGENT,
        EXPECTED_RESPONSE_BANDS,
        FLAG_DEFINITIONS,
        GLP1_AGENT_KEYWORDS,
        KG_PER_LB,
        LB_PER_KG,
        SCALE_BOUNDS_DISCLOSURE,
        _collect_axis_weights,
        build_headline,
        lbs_to_display,
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
        # v0.2.5: labels now carry the patient-unit weight (B3).
        self.assertEqual(lines[0]["label"], "5% — 209 lb")

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

        # Re-synced for v0.2.4: SCALE interpolates linearly from week 0 to the
        # published ±1 SD endpoint (1.3-14.7 at wk 56) → wk 24 = 24/56 of each.
        lira = build_expected_band(200.0, START, 24.0, "liraglutide_scale")
        self.assertEqual(lira["label"], "SCALE")
        by_week = {p["week"]: p for p in lira["points"]}
        self.assertAlmostEqual(by_week[24.0]["lower_pct"], 24.0 / 56.0 * 1.3)
        self.assertAlmostEqual(by_week[24.0]["upper_pct"], 24.0 / 56.0 * 14.7)

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
        # v0.2.2: the queryset chain ends in .prefetch_related("codings").
        chain = MockMedication.objects.for_patient.return_value.active.return_value
        chain.prefetch_related.return_value = meds
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
        chain = MockMedication.objects.for_patient.return_value.active.return_value
        chain.prefetch_related.return_value = [med]
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
        baseline_lbs = 104.3 * LB_PER_KG  # v0.2.5: single conversion constant
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


# ---------------------------------------------------------------------------
# v0.2.1 — timezone-mix regression (aware FHIR dates + naive UI dates)
# ---------------------------------------------------------------------------

class TestTimezoneMixRegression(V02TestCase):
    """Same-source seeded data is all tz-aware, but production charts can mix
    FHIR-created (aware) and UI-created (naive) observations. Raw comparisons
    between the two raise TypeError; every date sort/min must go through
    _strip_tz. Found by the v0.2 acceptance code review."""

    def _mixed_pair_same_day(self):
        aware = raw_obs("tz-a", 250.0, "lbs", 0)
        aware["datetime_of_service"] = aware["datetime_of_service"].replace(
            tzinfo=timezone.utc
        )
        naive = raw_obs("tz-n", 248.0, "lbs", 0)
        naive["datetime_of_service"] += timedelta(hours=2)
        return [aware, naive]

    def test_dedupe_same_day_mixed_tz_does_not_crash(self):
        merged = dedupe_same_day(self._mixed_pair_same_day())
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["value_original"], 249.0, places=3)

    def test_dedupe_mixed_tz_keeps_earliest_timestamp(self):
        merged = dedupe_same_day(self._mixed_pair_same_day())
        # aware obs at 09:00 UTC precedes naive obs at 11:00 once tz-stripped
        self.assertEqual(merged[0]["datetime_of_service"].hour, 9)

    def test_full_pipeline_mixed_tz_across_days(self):
        series = [
            raw_obs("d0", 250.0, "lbs", 0),
            raw_obs("d7", 247.0, "lbs", 7),
            raw_obs("d14", 244.0, "lbs", 14),
        ]
        series[1]["datetime_of_service"] = series[1]["datetime_of_service"].replace(
            tzinfo=timezone.utc
        )
        payload = build_chart_data(series, None)
        ok, errors = validate_chart_payload(payload)
        self.assertTrue(ok, errors)
        self.assertEqual(len(payload["datapoints"]), 3)


# ---------------------------------------------------------------------------
# v0.2.2 hygiene patch (acceptance-review findings 3-8) — structural guards,
# no behavior changes.
# ---------------------------------------------------------------------------

class TestV022Hygiene(V02TestCase):
    def test_agent_keyword_keys_match_band_tables(self):
        # Finding 7: the two dicts are coupled by string keys with a silent
        # STEP-1 fallback on mismatch — pin the key sets to each other.
        self.assertEqual(set(GLP1_AGENT_KEYWORDS), set(EXPECTED_RESPONSE_BANDS))

    @patch("protocols.growth_charts.Medication")
    def test_detection_prefetches_codings(self, MockMedication):
        # Finding 3: codings must be prefetched (one query, not one per med).
        chain = MockMedication.objects.for_patient.return_value.active.return_value
        chain.prefetch_related.return_value = []
        detect_glp1_agent("patient-1")
        chain.prefetch_related.assert_called_once_with("codings")

    def test_chart_config_ships_axis_pad_constants(self):
        # Finding 6: JS reads the pad rule from chart_config; Python
        # _axis_domain stays the source of truth.
        context = assemble_template_context(
            patient={"patient_id": "x"},
            baseline={"value": 200.0, "value_lbs": 200.0},
            datapoints=[],
            pipeline_timestamps={},
        )
        cfg = context["chart_config"]
        self.assertEqual(cfg["axis_pad_fraction"], AXIS_PAD_FRACTION)
        self.assertEqual(cfg["axis_pad_min_lbs"], AXIS_PAD_MIN_LBS)
        self.assertEqual(AXIS_PAD_FRACTION, 0.1)
        self.assertEqual(AXIS_PAD_MIN_LBS, 2.0)

    def test_collect_axis_weights_gathers_all_plotted_layers(self):
        # Finding 8: datapoints + baseline + both band edges, one collector.
        datapoints = [dp(0, 0.0, 220.0), dp(4, 2.0, 215.6)]
        band = {"points": [{"lower_lbs": 219.0, "upper_lbs": 210.0}]}
        weights = _collect_axis_weights(datapoints, 220.0, band)
        self.assertEqual(weights, [220.0, 215.6, 220.0, 219.0, 210.0])

    def test_collect_axis_weights_handles_empty_band(self):
        weights = _collect_axis_weights([dp(0, 0.0, 198.0)], 198.0, {"points": []})
        self.assertEqual(weights, [198.0, 198.0])


# ---------------------------------------------------------------------------
# Verifies: v0.2.3 @ 83f4004 (SCALE disclosure + trial citations patch;
# planned as "v0.2.1" in the revised prompt — that number was already taken
# by the tz/statsbar fix, deviation reported per build-discipline Gate 3)
# ---------------------------------------------------------------------------

class TestBandMetadata(V02TestCase):
    def test_citation_per_agent(self):
        # Volume/page strings verified against glp1_science_reference.md
        # (Gate 1): the file's hyphenated forms win over the prompt's en dashes.
        expected = {
            "semaglutide_step1": ("STEP 1", "2021;384:989-1002"),
            "tirzepatide_surmount1": ("SURMOUNT-1", "2022;387:205-216"),
            "liraglutide_scale": ("SCALE", "2015;373:11-22"),
        }
        for agent, (trial, volpage) in expected.items():
            band = build_expected_band(200.0, START, 24.0, agent)
            meta = band["band_metadata"]
            self.assertEqual(meta["trial"], trial)
            self.assertIn(volpage, meta["citation"])
            self.assertIn("N Engl J Med", meta["citation"])
            self.assertTrue(meta["summary"])

    def test_estimated_bounds_true_only_for_scale(self):
        flags = {
            agent: build_expected_band(200.0, START, 24.0, agent)["band_metadata"]["estimated_bounds"]
            for agent in EXPECTED_RESPONSE_BANDS
        }
        self.assertEqual(flags, {
            "semaglutide_step1": False,
            "tirzepatide_surmount1": False,
            "liraglutide_scale": True,
        })

    def test_disclosure_present_only_when_estimated(self):
        scale = build_expected_band(200.0, START, 24.0, "liraglutide_scale")
        self.assertEqual(scale["band_metadata"]["disclosure"], SCALE_BOUNDS_DISCLOSURE)
        # Re-synced for v0.2.4: the disclosure is now about imputation/skew.
        self.assertIn("approximation", SCALE_BOUNDS_DISCLOSURE)
        for agent in ("semaglutide_step1", "tirzepatide_surmount1"):
            meta = build_expected_band(200.0, START, 24.0, agent)["band_metadata"]
            self.assertNotIn("disclosure", meta)

    def test_legend_marks_estimated_bounds(self):
        def legend_for(agent):
            band = build_expected_band(215.0, START, 24.0, agent)
            context = assemble_template_context(
                patient={"patient_id": "x"},
                baseline={"value": 215.0, "value_lbs": 215.0},
                datapoints=[],
                pipeline_timestamps={},
                expected_band=band,
            )
            return context["chart_config"]["legend_text"]

        # Re-synced for v0.2.4: the qualifier is now the band basis, not
        # "estimated" — SCALE reads "±1 SD"; trial-percentile bands unmarked.
        self.assertEqual(legend_for("liraglutide_scale"), "Expected response (SCALE, ±1 SD)")
        self.assertEqual(legend_for("semaglutide_step1"), "Expected response (STEP-1)")
        self.assertEqual(legend_for("tirzepatide_surmount1"), "Expected response (SURMOUNT-1)")


# ---------------------------------------------------------------------------
# Verifies: v0.2.4 @ 59db2da (SCALE band replacement: published mean ±1 SD
# replaces the synthesized 0.5x/1.5x bounds; CDF anchors data-only)
# ---------------------------------------------------------------------------

class TestScaleBandReplacement(V02TestCase):
    def _scale_meta(self):
        return build_expected_band(200.0, START, 56.0, "liraglutide_scale")["band_metadata"]

    def test_published_center_and_bounds(self):
        meta = self._scale_meta()
        self.assertEqual(meta["center"], -8.0)
        self.assertEqual(meta["sd"], 6.7)
        self.assertEqual(meta["lower_bound"], -1.3)
        self.assertEqual(meta["upper_bound"], -14.7)

    def test_band_endpoint_matches_published_bounds(self):
        # The drawn corridor at week 56 is the ±1 SD pair, not a multiplier
        # of the mean (8.4 x 0.5/1.5 would be 4.2/12.6 — the old synthesis).
        band = build_expected_band(200.0, START, 56.0, "liraglutide_scale")
        last = band["points"][-1]
        self.assertAlmostEqual(last["week"], 56.0)
        self.assertAlmostEqual(last["lower_pct"], 1.3)
        self.assertAlmostEqual(last["upper_pct"], 14.7)

    def test_cdf_anchors_present(self):
        self.assertEqual(self._scale_meta()["scale_cdf_anchors"], [
            {"threshold_pct": 5, "responders_pct": 63.2},
            {"threshold_pct": 10, "responders_pct": 33.1},
            {"threshold_pct": 15, "responders_pct": 14.4},
        ])

    def test_step1_and_surmount1_untouched(self):
        # Regression guard: this patch must not move the trial-derived bands.
        self.assertEqual(EXPECTED_RESPONSE_BANDS["semaglutide_step1"]["points"], (
            (0, 0.0, 0.0), (4, 0.5, 4.5), (8, 1.0, 7.0), (12, 2.0, 11.0),
            (16, 3.0, 13.5), (20, 4.0, 15.0), (24, 5.0, 16.5), (36, 6.0, 19.0),
            (52, 7.0, 21.0), (68, 7.5, 22.0),
        ))
        self.assertEqual(EXPECTED_RESPONSE_BANDS["tirzepatide_surmount1"]["points"], (
            (0, 0.0, 0.0), (4, 0.8, 5.5), (8, 2.0, 10.0), (12, 3.5, 14.5),
            (16, 5.0, 18.0), (24, 8.0, 22.0), (36, 10.0, 26.0),
            (52, 12.0, 28.5), (72, 13.0, 31.0),
        ))
        for agent in ("semaglutide_step1", "tirzepatide_surmount1"):
            meta = EXPECTED_RESPONSE_BANDS[agent]["metadata"]
            self.assertFalse(meta["estimated_bounds"])
            self.assertNotIn("legend_qualifier", meta)

    def test_disclosure_copy_replaced(self):
        self.assertIn("±1 SD", SCALE_BOUNDS_DISCLOSURE)
        self.assertIn("Pi-Sunyer", SCALE_BOUNDS_DISCLOSURE)
        for stale in ("0.5", "1.5", "illustrative"):
            self.assertNotIn(stale, SCALE_BOUNDS_DISCLOSURE)


# ---------------------------------------------------------------------------
# Verifies: reference concordance @ ab105be
#
# Tripwire defending the CORRECTED Gate-1 reference. (The plan called this an
# "inversion" of a prior TestGate1ReferenceDisagreement tripwire, but that test
# never existed in the repo — the v0.2.4 kg-vs-% issue was recorded only as a
# commit note + rationale + code comment, never a test. Contradiction reported;
# this is created fresh rather than inverted.) The authority is the paper, not
# the code and not the reference — both are caches of Pi-Sunyer 2015. This test
# pins that the reference reproduces the paper AND that the code's shipped SCALE
# numbers match the reference, so it trips if either regresses.
# ---------------------------------------------------------------------------

class TestGate1ReferenceConcordance(V02TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = REFERENCE_PATH.read_text(encoding="utf-8")
        cls.meta = EXPECTED_RESPONSE_BANDS["liraglutide_scale"]["metadata"]

    def test_reference_carries_corrected_percent_and_kg(self):
        # 56-week row: −8.0 under % TBWL, 8.4 preserved under a kg label.
        self.assertRegex(self.ref, r"\|\s*56\s*\|\s*8\.0\s*\|\s*8\.4\s*\|")
        self.assertIn("Mean change (kg)", self.ref)
        # The old mislabel (8.4 as the 56-wk % value) must be gone.
        self.assertNotRegex(self.ref, r"\|\s*56\s*\|\s*8\.4\s*\|\s*$")

    def test_code_percent_matches_reference_percent(self):
        # center is signed in code (−8.0); the reference prints the magnitude.
        self.assertEqual(self.meta["center"], -8.0)
        self.assertIn("−8.0", self.ref)  # U+2212 minus, as written in the ref
        self.assertIn("| Mean % body-weight change | −8.0 |", self.ref)

    def test_sd_present_and_concordant(self):
        self.assertEqual(self.meta["sd"], 6.7)
        self.assertIn("| SD (percentage points)    | 6.7  |", self.ref)

    def test_cdf_anchors_present_and_concordant(self):
        anchors = {a["threshold_pct"]: a["responders_pct"] for a in self.meta["scale_cdf_anchors"]}
        self.assertEqual(anchors, {5: 63.2, 10: 33.1, 15: 14.4})
        # Each shipped responder rate must appear in the reference's CDF table.
        for pct in (63.2, 33.1, 14.4):
            self.assertIn(f"{pct}%", self.ref)

    def test_scale_rows_cite_primary_source(self):
        # The corrected SCALE rows must be auditable to the paper.
        self.assertIn("Pi-Sunyer", self.ref)
        self.assertIn("2015;373:11", self.ref)


# ---------------------------------------------------------------------------
# Verifies: v0.2.5 @ e5cbfc2 (patient-unit context: one conversion constant,
# dual-metric headline, milestone unit labels, dual-unit trial disclosure)
# ---------------------------------------------------------------------------

PROTOCOL_SRC = (
    Path(__file__).resolve().parent.parent / "protocols" / "growth_charts.py"
).read_text(encoding="utf-8")


class TestV025PatientUnitContext(V02TestCase):
    def test_conversion_round_trip(self):
        # kg → lb → kg within 1e-9, and the two constants are reciprocal.
        for kg in (0.0, 8.4, 104.3, 250.0):
            lb = kg * LB_PER_KG
            self.assertAlmostEqual(lb * KG_PER_LB, kg, delta=1e-9)
        self.assertAlmostEqual(LB_PER_KG * KG_PER_LB, 1.0, delta=1e-12)
        self.assertEqual(KG_PER_LB, 0.45359237)  # exact by definition

    def test_no_stray_conversion_literals(self):
        # Every conversion factor must come from the one constant. The only
        # places the kg magnitude may appear as a literal are the KG_PER_LB /
        # LB_PER_KG definition lines themselves.
        for token in ("2.2046", "0.4535", "2.20462", "0.00220462"):
            offending = []
            for ln in PROTOCOL_SRC.splitlines():
                code = ln.split("#", 1)[0]  # strip comments — prose may cite the value
                if token in code and "KG_PER_LB" not in code and "LB_PER_KG" not in code:
                    offending.append(ln.strip())
            self.assertEqual(offending, [], f"stray literal {token!r}: {offending}")

    def test_headline_absolute_from_patient_data(self):
        # 220 lb baseline → 201.3 lb latest = −8.5% TBWL, −18.7 lb absolute.
        tbwl = (220.0 - 201.3) / 220.0 * 100.0
        h = build_headline(220.0, 201.3, tbwl, "lb")
        self.assertAlmostEqual(h["abs_change"], -18.7, places=1)
        self.assertEqual(h["abs_change_display"], "-18.7 lb")
        self.assertEqual(h["baseline_display"], "220 lb")
        self.assertIn("-8.5% TBWL", h["text"])
        self.assertIn("from 220 lb baseline", h["text"])

    def test_headline_same_in_lb_whether_entered_lb_or_kg(self):
        # P8-shape: a kg+lb mixed series normalizes to one lb headline.
        kg_series = [
            ("a", 104.3, "kg", 0), ("b", 228.0, "lb", 14), ("c", 102.1, "kg", 28),
            ("d", 223.0, "lb", 42), ("e", 100.2, "kg", 56), ("f", 219.0, "lb", 70),
        ]
        payload = build_chart_data([raw_obs(*r) for r in kg_series], None)
        ctx = assemble_template_context(
            patient={"patient_id": "x"},
            baseline=payload["baseline_data"],
            datapoints=payload["datapoints"],
            pipeline_timestamps=payload["_pipeline_timestamps"],
        )
        h = ctx["headline"]
        self.assertEqual(h["display_unit"], "lb")
        # Coherent single-unit readout — no kg-scale (~100) numbers leaking in.
        self.assertTrue(h["abs_change_display"].endswith(" lb"))
        self.assertIn("lb baseline", h["text"])
        self.assertNotIn("kg", h["text"])

    def test_milestone_labels_carry_patient_unit_weight(self):
        # 5/10/15% of a 220 lb baseline → 209 / 198 / 187 lb labels.
        lines = compute_milestone_lines(220.0, [180.0, 225.0], latest_tbwl_pct=12.1)
        labels = {m["pct"]: m["label"] for m in lines}
        self.assertEqual(labels[5.0], "5% — 209 lb")
        self.assertEqual(labels[10.0], "10% — 198 lb")
        self.assertEqual(labels[15.0], "15% — 187 lb")
        # Suppressed milestones carry no label (none emitted at all).
        suppressed = compute_milestone_lines(245.0, [239.9, 245.0], latest_tbwl_pct=2.1)
        self.assertEqual(suppressed, [])

    def test_trial_disclosure_dual_unit(self):
        # SCALE reports an absolute mean → population line shows kg + computed lb.
        scale = build_expected_band(200.0, START, 56.0, "liraglutide_scale")
        line = scale["band_metadata"]["population_line"]
        self.assertIn("8.4 kg", line)
        self.assertIn(f"{8.4 * LB_PER_KG:.1f} lb", line)  # 18.5 lb, computed
        self.assertIn("106.2 kg mean baseline", line)
        self.assertIn("applied to their own baseline", line)

    def test_percent_only_trials_invent_no_kg(self):
        # STEP-1 / SURMOUNT-1 carry percent only → no population line, no kg.
        for agent in ("semaglutide_step1", "tirzepatide_surmount1"):
            meta = build_expected_band(200.0, START, 24.0, agent)["band_metadata"]
            self.assertNotIn("population_line", meta)
            self.assertNotIn("absolute_mean_kg", meta)

    def test_basis_wording_corrected(self):
        # Task A: "completers" gone from the shipped disclosure.
        self.assertNotIn("completer", SCALE_BOUNDS_DISCLOSURE.lower())
        self.assertIn("full analysis set", SCALE_BOUNDS_DISCLOSURE)


if __name__ == "__main__":
    unittest.main()
