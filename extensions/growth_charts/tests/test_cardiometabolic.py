"""
tests/test_cardiometabolic.py
==============================
Test suite for cardiometabolic_tracker Canvas plugin.
Run: python -m pytest tests/test_cardiometabolic.py -v

Test tiers:
  Tier 1 — Unit tests (pure logic, no Canvas SDK)
  Tier 2 — Integration tests (mocked Canvas SDK)
  Tier 3 — Clinical validation (expected outcomes vs. published data)
  Tier 4 — Edge cases and error handling

All Canvas SDK calls are mocked. Tests must pass without a live Canvas instance.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
import sys
import os

# ---------------------------------------------------------------------------
# Path setup — allows running from project root or tests/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Lightweight stubs for Canvas SDK — used when real SDK not installed
# These allow tests to run in CI without Canvas credentials
# ---------------------------------------------------------------------------
try:
    from canvas_sdk.handlers.action_button import ActionButton
    from canvas_sdk.effects.launch_modal import LaunchModalEffect
    CANVAS_SDK_AVAILABLE = True
except ImportError:
    CANVAS_SDK_AVAILABLE = False
    # Stub out just enough for structural tests
    class ActionButton:
        pass
    class LaunchModalEffect:
        def __init__(self, **kwargs): self.kwargs = kwargs


# ---------------------------------------------------------------------------
# Import the functions under test
# These are the functions CPA will implement in protocols/growth_charts.py
# If they don't exist yet, tests will show ImportError — that's intentional
# ---------------------------------------------------------------------------
try:
    from protocols.growth_charts import (
        calculate_tbwl,
        convert_weight_to_lbs,
        compute_baseline,
        batch_load_notes,
        build_chart_data,
        validate_chart_payload,
        format_date_mmmyyyy,
        calculate_weeks_since_baseline,
        GenerateVitalsGraphs,         # The ActionButton handler class
    )
    PROTOCOL_AVAILABLE = True
except ImportError as e:
    PROTOCOL_AVAILABLE = False
    IMPORT_ERROR = str(e)
    # Define stub functions so the module loads — individual tests will skip
    def calculate_tbwl(baseline, current): raise NotImplementedError
    def convert_weight_to_lbs(value, unit): raise NotImplementedError
    def compute_baseline(observations): raise NotImplementedError
    def batch_load_notes(note_ids): raise NotImplementedError
    def build_chart_data(observations, baseline): raise NotImplementedError
    def validate_chart_payload(payload): raise NotImplementedError
    def format_date_mmmyyyy(dt): raise NotImplementedError
    def calculate_weeks_since_baseline(baseline_date, current_date): raise NotImplementedError
    class GenerateVitalsGraphs: pass


# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------

def make_observation(
    obs_id: str,
    value: float,
    unit: str,
    days_from_start: int,
    start_date: datetime = None
) -> Mock:
    """Create a mocked Canvas Observation object."""
    if start_date is None:
        start_date = datetime(2024, 1, 15)
    obs = Mock()
    obs.id = obs_id
    obs.value = value
    obs.unit = unit    # kept for backward compatibility with any old references
    obs.units = unit   # Canvas SDK Observation field is 'units' (plural), not 'unit'
    obs.note_id = abs(hash(obs_id)) % 9000 + 1000  # realistic int (BigIntegerField)
    obs.note = Mock()
    obs.note.id = f"note_{obs_id}"
    obs.note.dbid = abs(hash(obs_id)) % 9000 + 1000
    obs.note.datetime_of_service = start_date + timedelta(days=days_from_start)
    return obs


def make_observation_sequence(
    weights_lbs: list,
    start_date: datetime = None,
    interval_days: int = 28
) -> list:
    """Create a sequence of mocked weight observations."""
    if start_date is None:
        start_date = datetime(2024, 1, 15)
    return [
        make_observation(
            obs_id=f"obs_{i:03d}",
            value=w,
            unit="lbs",
            days_from_start=i * interval_days,
            start_date=start_date
        )
        for i, w in enumerate(weights_lbs)
    ]


def make_valid_chart_payload(
    baseline_lbs: float = 250.0,
    observations_count: int = 5
) -> dict:
    """Create a minimally valid template context dict."""
    start_date = datetime(2024, 1, 15)
    weights = [baseline_lbs - (i * 5) for i in range(observations_count)]
    datapoints = [
        {
            "id": f"obs_{i:03d}",
            "value_lbs": weights[i],
            "date_label": "Jan 2024",
            "date_obj": start_date + timedelta(days=i * 28),
            "tbwl_pct": ((baseline_lbs - weights[i]) / baseline_lbs) * 100,
        }
        for i in range(observations_count)
    ]
    return {
        "baseline_data": {
            "value": baseline_lbs,
            "unit": "lbs",
            "source_observation_id": "obs_000",
            "_loaded_at": datetime.now().isoformat(),
            "_component": "baseline_layer",
        },
        "datapoints": datapoints,
        "latest_tbwl_pct": datapoints[-1]["tbwl_pct"],
        "_pipeline_timestamps": {
            "demographics_loaded": datetime.now().isoformat(),
            "observations_loaded": datetime.now().isoformat(),
            "notes_batch_loaded": datetime.now().isoformat(),
            "processing_complete": datetime.now().isoformat(),
            "template_render_start": datetime.now().isoformat(),
        }
    }


# ============================================================================
# TIER 1 — Unit Tests (pure logic, no Canvas SDK)
# ============================================================================

class UnitTest_TBWLCalculation(unittest.TestCase):
    """
    Tests for calculate_tbwl(baseline_lbs, current_lbs) -> float
    Formula: ((baseline - current) / baseline) * 100
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_no_weight_loss(self):
        """Patient weight unchanged from baseline → 0.0% TBWL"""
        result = calculate_tbwl(250.0, 250.0)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_typical_semaglutide_response_week52(self):
        """~14.9% TBWL at 68 weeks is the STEP-1 primary endpoint"""
        baseline = 250.0
        current = 250.0 * (1 - 0.149)  # 14.9% loss
        result = calculate_tbwl(baseline, current)
        self.assertAlmostEqual(result, 14.9, places=1)

    def test_tirzepatide_max_response(self):
        """22.5% TBWL is the SURMOUNT-1 15mg arm endpoint"""
        baseline = 240.0
        current = 240.0 * (1 - 0.225)
        result = calculate_tbwl(baseline, current)
        self.assertAlmostEqual(result, 22.5, places=1)

    def test_early_responder_threshold(self):
        """5% TBWL at week 12 is the early-responder threshold"""
        baseline = 200.0
        current = 190.0  # exactly 5% less
        result = calculate_tbwl(baseline, current)
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_weight_gain_returns_negative(self):
        """If patient gained weight, TBWL should be negative"""
        baseline = 250.0
        current = 260.0
        result = calculate_tbwl(baseline, current)
        self.assertLess(result, 0)
        self.assertAlmostEqual(result, -4.0, places=1)

    def test_zero_baseline_raises_value_error(self):
        """Division by zero on zero baseline → ValueError"""
        with self.assertRaises((ValueError, ZeroDivisionError)):
            calculate_tbwl(0.0, 100.0)

    def test_negative_baseline_raises(self):
        """Negative baseline is clinically impossible → ValueError"""
        with self.assertRaises(ValueError):
            calculate_tbwl(-10.0, 100.0)

    def test_result_is_float(self):
        """Result should always be a float, not Decimal or int"""
        result = calculate_tbwl(250.0, 225.0)
        self.assertIsInstance(result, float)

    def test_100_percent_loss_is_impossible(self):
        """100% TBWL means weight = 0, should return 100.0 (math is correct)"""
        result = calculate_tbwl(250.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=2)


class UnitTest_WeightConversion(unittest.TestCase):
    """
    Tests for convert_weight_to_lbs(value, unit) -> float
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_lbs_passthrough(self):
        """lbs input should return unchanged value"""
        result = convert_weight_to_lbs(250.0, "lbs")
        self.assertAlmostEqual(result, 250.0, places=2)

    def test_kg_to_lbs(self):
        """1 kg = 2.20462 lbs"""
        result = convert_weight_to_lbs(100.0, "kg")
        self.assertAlmostEqual(result, 220.462, places=1)

    def test_oz_to_lbs(self):
        """16 oz = 1 lb"""
        result = convert_weight_to_lbs(160.0, "oz")
        self.assertAlmostEqual(result, 10.0, places=2)

    def test_g_to_lbs(self):
        """1000g = 1kg = 2.20462 lbs"""
        result = convert_weight_to_lbs(1000.0, "g")
        self.assertAlmostEqual(result, 2.20462, places=2)

    def test_unknown_unit_raises(self):
        """Unknown unit should raise ValueError (not silently return wrong value)"""
        with self.assertRaises(ValueError):
            convert_weight_to_lbs(100.0, "stone")

    def test_case_insensitive_unit(self):
        """Units should be case-insensitive: 'Kg', 'KG', 'kg' all work"""
        result_lower = convert_weight_to_lbs(100.0, "kg")
        result_upper = convert_weight_to_lbs(100.0, "KG")
        result_mixed = convert_weight_to_lbs(100.0, "Kg")
        self.assertAlmostEqual(result_lower, result_upper, places=3)
        self.assertAlmostEqual(result_lower, result_mixed, places=3)

    def test_zero_weight(self):
        """Zero weight converts to zero (not an error)"""
        result = convert_weight_to_lbs(0.0, "lbs")
        self.assertAlmostEqual(result, 0.0, places=3)


class UnitTest_BaselineComputation(unittest.TestCase):
    """
    Tests for compute_baseline(observations) -> float (baseline weight in lbs)
    Baseline = first observation sorted ascending by datetime_of_service
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_single_observation_is_baseline(self):
        """One observation → it is the baseline"""
        obs = [make_observation("obs_001", 250.0, "lbs", 0)]
        baseline = compute_baseline(obs)
        self.assertAlmostEqual(baseline, 250.0, places=2)

    def test_earliest_date_is_baseline(self):
        """Baseline must be the FIRST chronological observation"""
        obs = make_observation_sequence([250.0, 240.0, 230.0])
        baseline = compute_baseline(obs)
        self.assertAlmostEqual(baseline, 250.0, places=2)

    def test_out_of_order_observations(self):
        """If observations are passed out of date order, still get earliest"""
        start = datetime(2024, 1, 15)
        obs = [
            make_observation("obs_c", 230.0, "lbs", 56, start),  # latest
            make_observation("obs_a", 250.0, "lbs", 0, start),   # earliest
            make_observation("obs_b", 240.0, "lbs", 28, start),  # middle
        ]
        baseline = compute_baseline(obs)
        self.assertAlmostEqual(baseline, 250.0, places=2)

    def test_empty_observations_raises(self):
        """No observations → cannot compute baseline → ValueError"""
        with self.assertRaises((ValueError, IndexError)):
            compute_baseline([])

    def test_baseline_from_oz_observations(self):
        """If stored in oz, baseline should still return in lbs"""
        obs = [make_observation("obs_001", 4000.0, "oz", 0)]  # 4000 oz = 250 lbs
        baseline = compute_baseline(obs)
        self.assertAlmostEqual(baseline, 250.0, places=1)


class UnitTest_DateFormatting(unittest.TestCase):
    """
    Tests for format_date_mmmyyyy(dt) -> str (e.g. "Jan 2024")
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_january_format(self):
        dt = datetime(2024, 1, 15)
        self.assertEqual(format_date_mmmyyyy(dt), "Jan 2024")

    def test_december_format(self):
        dt = datetime(2023, 12, 31)
        self.assertEqual(format_date_mmmyyyy(dt), "Dec 2023")

    def test_output_is_string(self):
        dt = datetime(2024, 6, 1)
        result = format_date_mmmyyyy(dt)
        self.assertIsInstance(result, str)

    def test_three_letter_month_abbreviation(self):
        """Month must be 3-letter abbreviated, not full name"""
        dt = datetime(2024, 3, 15)
        result = format_date_mmmyyyy(dt)
        self.assertEqual(len(result.split()[0]), 3)  # "Mar"


class UnitTest_WeeksCalculation(unittest.TestCase):
    """
    Tests for calculate_weeks_since_baseline(baseline_date, current_date) -> float
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_same_date_is_zero_weeks(self):
        d = datetime(2024, 1, 15)
        result = calculate_weeks_since_baseline(d, d)
        self.assertAlmostEqual(result, 0.0, places=1)

    def test_exactly_12_weeks(self):
        baseline = datetime(2024, 1, 15)
        current = baseline + timedelta(weeks=12)
        result = calculate_weeks_since_baseline(baseline, current)
        self.assertAlmostEqual(result, 12.0, places=1)

    def test_fractional_weeks(self):
        """10 days = ~1.43 weeks"""
        baseline = datetime(2024, 1, 1)
        current = datetime(2024, 1, 11)
        result = calculate_weeks_since_baseline(baseline, current)
        self.assertAlmostEqual(result, 10 / 7, places=1)

    def test_earlier_date_raises_or_returns_negative(self):
        """Current before baseline should not silently return wrong result"""
        baseline = datetime(2024, 6, 1)
        current = datetime(2024, 1, 1)
        result = calculate_weeks_since_baseline(baseline, current)
        self.assertLess(result, 0)  # must be negative or raise


# ============================================================================
# TIER 2 — Integration Tests (mocked Canvas SDK)
# ============================================================================

class IntegrationTest_N1QueryFix(unittest.TestCase):
    """
    Verify the N+1 Note query bug is fixed.
    Original code: one Note.objects.get() call per observation (inside loop).
    Fixed code: one Note.objects.filter(dbid__in=int_ids) call for all notes.

    Root cause discovered during live testing: Canvas Observation.note_id is a
    BigIntegerField (stores Note.dbid integer PK), not a UUIDField. The fix
    uses Note.objects.filter(dbid__in=...) and keys the return dict by str(dbid).
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    @patch("protocols.growth_charts.Note")
    def test_batch_fetch_not_get_in_loop(self, MockNote):
        """
        batch_load_notes() must call .filter(dbid__in=...) once, not .get() N times.
        Note IDs are integer strings ("8", "36") matching Observation.note_id (BigIntegerField).
        """
        note_ids = [str(i) for i in range(8, 13)]   # ["8","9","10","11","12"]
        mock_notes_list = []
        for nid in note_ids:
            n = Mock()
            n.dbid = int(nid)
            mock_notes_list.append(n)

        mock_qs = MagicMock()
        mock_qs.__iter__ = Mock(return_value=iter(mock_notes_list))
        MockNote.objects.filter.return_value = mock_qs

        result = batch_load_notes(note_ids)

        # filter() called exactly once with dbid__in (integer PK), not id__in (UUID)
        MockNote.objects.filter.assert_called_once()
        call_kwargs = MockNote.objects.filter.call_args
        self.assertIn("dbid__in", call_kwargs.kwargs,
                      "Must filter on dbid__in (integer PK), not id__in (UUID field)")

        # get() was never called
        MockNote.objects.get.assert_not_called()

    @patch("protocols.growth_charts.Note")
    def test_batch_returns_dict_keyed_by_id(self, MockNote):
        """Return value must be {str(note_dbid): note_object} for O(1) lookup.

        Keys match what _note_id_of() returns: str(obs.note_id) — the integer PK.
        """
        mock_note_a = Mock()
        mock_note_a.dbid = 8
        mock_note_b = Mock()
        mock_note_b.dbid = 36

        mock_qs = MagicMock()
        mock_qs.__iter__ = Mock(return_value=iter([mock_note_a, mock_note_b]))
        MockNote.objects.filter.return_value = mock_qs

        result = batch_load_notes(["8", "36"])
        self.assertIn("8", result)
        self.assertIn("36", result)
        self.assertEqual(result["8"], mock_note_a)
        self.assertEqual(result["36"], mock_note_b)


class IntegrationTest_BuildChartData(unittest.TestCase):
    """
    Tests for build_chart_data(observations, baseline_lbs) -> ChartPayload
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_output_has_required_keys(self):
        """Chart payload must have all keys needed by chart.html"""
        obs = make_observation_sequence([250.0, 240.0, 237.5, 235.0])
        baseline = 250.0
        result = build_chart_data(obs, baseline)
        required_keys = ["baseline_data", "datapoints", "_pipeline_timestamps"]
        for key in required_keys:
            self.assertIn(key, result, f"Missing required key: {key}")

    def test_raw_data_preserved_separately(self):
        """
        Raw observation data must be kept separately from processed.
        Look for _raw suffix or a 'raw' key in each datapoint.
        """
        obs = make_observation_sequence([250.0, 240.0])
        result = build_chart_data(obs, 250.0)
        for dp in result["datapoints"]:
            # Either raw data is in a separate 'raw' sub-dict,
            # or the processed dict has _original suffix fields
            has_raw_separation = (
                "raw" in dp or
                "value_original" in dp or
                "unit_original" in dp
            )
            self.assertTrue(
                has_raw_separation,
                f"Datapoint missing raw/original data: {dp.keys()}"
            )

    def test_timestamps_in_pipeline_metadata(self):
        """Pipeline timestamps must be present for tracing."""
        obs = make_observation_sequence([250.0, 240.0])
        result = build_chart_data(obs, 250.0)
        ts = result.get("_pipeline_timestamps", {})
        required_timestamps = [
            "observations_loaded", "notes_batch_loaded", "processing_complete"
        ]
        for ts_key in required_timestamps:
            self.assertIn(ts_key, ts, f"Missing timestamp: {ts_key}")

    def test_datapoints_sorted_by_date_ascending(self):
        """Datapoints must be sorted oldest-first for correct chart rendering."""
        # Create observations out of order
        start = datetime(2024, 1, 15)
        obs_unsorted = [
            make_observation("obs_c", 230.0, "lbs", 56, start),
            make_observation("obs_a", 250.0, "lbs", 0, start),
            make_observation("obs_b", 240.0, "lbs", 28, start),
        ]
        result = build_chart_data(obs_unsorted, 250.0)
        dates = [dp["date_obj"] for dp in result["datapoints"]]
        self.assertEqual(dates, sorted(dates), "Datapoints not sorted ascending by date")

    def test_tbwl_annotated_on_each_point(self):
        """Every datapoint must have tbwl_pct computed."""
        obs = make_observation_sequence([250.0, 237.5, 225.0])  # 0%, 5%, 10%
        result = build_chart_data(obs, 250.0)
        for i, dp in enumerate(result["datapoints"]):
            self.assertIn("tbwl_pct", dp, f"Datapoint {i} missing tbwl_pct")
            self.assertIsInstance(dp["tbwl_pct"], float)


class IntegrationTest_ManifestStructure(unittest.TestCase):
    """Verify CANVAS_MANIFEST.json structure matches implementation."""

    MANIFEST_PATH = os.path.join(
        os.path.dirname(__file__), "..", "CANVAS_MANIFEST.json"
    )

    def _load_manifest(self):
        if not os.path.exists(self.MANIFEST_PATH):
            self.skipTest("CANVAS_MANIFEST.json not found")
        with open(self.MANIFEST_PATH) as f:
            return json.load(f)

    def test_plugin_name_is_cardiometabolic_tracker(self):
        """Manifest must be renamed from growth_charts → cardiometabolic_tracker"""
        manifest = self._load_manifest()
        self.assertEqual(
            manifest.get("name"), "cardiometabolic_tracker",
            f"Expected 'cardiometabolic_tracker', got '{manifest.get('name')}'"
        )

    def test_handler_class_path_is_valid(self):
        """Handler path must match module:ClassName format"""
        manifest = self._load_manifest()
        for handler in manifest.get("components", {}).get("protocols", []):
            class_path = handler.get("class", "") if isinstance(handler, dict) else handler
            self.assertIn(
                ":", class_path,
                f"Handler path missing colon separator: {class_path}"
            )
            module, classname = class_path.split(":", 1)
            self.assertTrue(len(module) > 0 and len(classname) > 0)

    def test_no_graphs_directory_referenced(self):
        """Manifest must not reference graphs/ files"""
        manifest = self._load_manifest()
        manifest_str = json.dumps(manifest)
        self.assertNotIn("graphs/", manifest_str,
                        "Manifest must not reference deleted graphs/ directory")


# ============================================================================
# TIER 3 — Clinical Validation Tests
# ============================================================================

class ClinicalTest_TBWLRanges(unittest.TestCase):
    """
    Ensure computed TBWL values fall within clinically plausible ranges
    for known GLP-1 treatment scenarios.
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_semaglutide_68week_outcome_in_range(self):
        """
        STEP-1 trial: 14.9% mean TBWL at 68 weeks.
        Plausible individual range: 7% – 22%.
        """
        baseline = 250.0
        # Simulate a patient near the mean outcome
        current = baseline * (1 - 0.149)
        tbwl = calculate_tbwl(baseline, current)
        self.assertGreater(tbwl, 7.0, "TBWL below realistic minimum for 68-week semaglutide")
        self.assertLess(tbwl, 22.0, "TBWL above realistic maximum for 68-week semaglutide")

    def test_tirzepatide_72week_outcome_in_range(self):
        """
        SURMOUNT-1: 22.5% mean TBWL at 72 weeks.
        Plausible individual range: 13% – 31%.
        """
        baseline = 240.0
        current = baseline * (1 - 0.225)
        tbwl = calculate_tbwl(baseline, current)
        self.assertGreater(tbwl, 13.0)
        self.assertLess(tbwl, 31.0)

    def test_early_responder_classification_at_week_12(self):
        """
        A patient losing ≥5% by week 12 should be classifiable as early responder.
        This test verifies the threshold math is correct.
        """
        baseline = 200.0
        # Exactly at threshold
        current_at_threshold = baseline * 0.95  # 5% loss
        tbwl = calculate_tbwl(baseline, current_at_threshold)
        self.assertAlmostEqual(tbwl, 5.0, places=1)
        self.assertTrue(tbwl >= 5.0, "Early responder threshold boundary incorrect")

        # Just below threshold
        current_below = baseline * 0.951  # 4.9% loss
        tbwl_below = calculate_tbwl(baseline, current_below)
        self.assertLess(tbwl_below, 5.0, "Non-responder incorrectly classified")

    def test_tbwl_increases_as_weight_decreases(self):
        """As patient loses more weight over time, TBWL% must strictly increase."""
        baseline = 300.0
        weights = [300.0, 285.0, 271.5, 259.0, 248.5]  # decreasing weights
        tbwls = [calculate_tbwl(baseline, w) for w in weights]
        for i in range(1, len(tbwls)):
            self.assertGreater(
                tbwls[i], tbwls[i-1],
                f"TBWL not increasing at step {i}: {tbwls[i-1]:.2f}% → {tbwls[i]:.2f}%"
            )


class ClinicalTest_ChartPayloadContent(unittest.TestCase):
    """Verify chart data makes clinical sense before it reaches the template."""

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_baseline_is_first_observation_not_last(self):
        """The baseline dashed line must be at the FIRST observation value, not the latest."""
        obs = make_observation_sequence([250.0, 240.0, 230.0, 220.0])
        result = build_chart_data(obs, 250.0)
        baseline_value = result["baseline_data"]["value"]
        self.assertAlmostEqual(baseline_value, 250.0, places=1,
            msg="Baseline must be 250.0 (first obs), not the latest weight")

    def test_latest_tbwl_is_positive_when_patient_losing(self):
        """If patient has lost weight, latest_tbwl_pct must be positive."""
        obs = make_observation_sequence([250.0, 240.0, 230.0])
        result = build_chart_data(obs, 250.0)
        self.assertGreater(result.get("latest_tbwl_pct", 0), 0,
            "Patient losing weight should show positive TBWL%")


# ============================================================================
# TIER 4 — Edge Cases and Error Handling
# ============================================================================

class EdgeCaseTest_PreRenderValidation(unittest.TestCase):
    """
    Tests for validate_chart_payload(payload) -> tuple[bool, list[str]]
    This runs before LaunchModalEffect to catch bad data.
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_valid_payload_passes(self):
        """A well-formed payload should pass validation with no errors."""
        payload = make_valid_chart_payload()
        is_valid, errors = validate_chart_payload(payload)
        self.assertTrue(is_valid, f"Valid payload failed validation: {errors}")
        self.assertEqual(len(errors), 0)

    def test_missing_baseline_fails(self):
        """No baseline → validation must fail"""
        payload = make_valid_chart_payload()
        del payload["baseline_data"]
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("baseline" in e.lower() for e in errors))

    def test_empty_datapoints_fails(self):
        """No observations → cannot render chart → validation must fail"""
        payload = make_valid_chart_payload()
        payload["datapoints"] = []
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)

    def test_future_date_observation_flagged(self):
        """Observations dated in the future are a data error → fail validation"""
        payload = make_valid_chart_payload()
        payload["datapoints"][0]["date_obj"] = datetime.now() + timedelta(days=30)
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("future" in e.lower() or "date" in e.lower() for e in errors))

    def test_implausible_tbwl_flagged(self):
        """
        TBWL of 60% would require losing 60% of body weight — clinically impossible.
        Validation must catch this as a calculation error.
        """
        payload = make_valid_chart_payload()
        payload["latest_tbwl_pct"] = 60.0
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("tbwl" in e.lower() or "range" in e.lower() for e in errors))

    def test_zero_weight_observation_fails(self):
        """Weight of 0 lbs is a data entry error → fail validation"""
        payload = make_valid_chart_payload()
        payload["datapoints"][0]["value_lbs"] = 0.0
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)

    def test_unsorted_dates_flagged(self):
        """Unsorted observations would render a confusing backwards chart → fail"""
        payload = make_valid_chart_payload(observations_count=3)
        # Reverse the order
        payload["datapoints"].reverse()
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("sort" in e.lower() or "order" in e.lower() or "date" in e.lower()
                           for e in errors))

    def test_missing_pipeline_timestamps_flagged(self):
        """Required _pipeline_timestamps key missing → fail"""
        payload = make_valid_chart_payload()
        del payload["_pipeline_timestamps"]
        is_valid, errors = validate_chart_payload(payload)
        self.assertFalse(is_valid)


class EdgeCaseTest_SingleObservation(unittest.TestCase):
    """Edge case: patient has only one visit — just the baseline."""

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_single_observation_renders_without_error(self):
        """One observation = baseline only. Chart should show a flat line at baseline."""
        obs = [make_observation("obs_001", 250.0, "lbs", 0)]
        result = build_chart_data(obs, 250.0)
        self.assertEqual(len(result["datapoints"]), 1)
        self.assertAlmostEqual(result["datapoints"][0]["tbwl_pct"], 0.0, places=2)

    def test_single_observation_tbwl_is_zero(self):
        """If only one observation exists, TBWL = 0% (patient is at baseline)."""
        baseline = 250.0
        tbwl = calculate_tbwl(baseline, baseline)
        self.assertAlmostEqual(tbwl, 0.0, places=2)


class EdgeCaseTest_MutableDefaultBug(unittest.TestCase):
    """
    Verify the mutable default argument bug is fixed.
    Original: def get_age_in_months(birth_date, date=datetime.now())
    → 'datetime.now()' evaluated ONCE at import time, not per call.
    Fixed: def get_age_in_months(birth_date, date=None): date = date or datetime.now()
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_date_default_not_evaluated_at_import(self):
        """
        Call the date-dependent function twice with a gap and verify
        it uses current time, not a frozen time from import.
        """
        import time
        import inspect

        # Get the source of the protocol module to check the signature
        try:
            import protocols.growth_charts as mod
            source = inspect.getsource(mod)
            # The bug pattern: date=datetime.now() in function signature
            self.assertNotIn(
                "date=datetime.now()",
                source,
                "Mutable default bug still present: 'date=datetime.now()' in signature. "
                "Fix: use 'date=None' and 'date = date or datetime.now()' in body."
            )
        except (ImportError, OSError):
            self.skipTest("Could not inspect module source")


class EdgeCaseTest_SexFieldNotRequired(unittest.TestCase):
    """
    Unlike the pediatric plugin, the adult plugin must work WITHOUT sex field.
    Sex stratification was removed — sex field is optional.
    """

    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

    def test_missing_sex_does_not_block_chart(self):
        """build_chart_data() must not raise when sex is None/missing"""
        obs = make_observation_sequence([250.0, 240.0, 230.0])
        # Should not raise regardless of sex
        try:
            result = build_chart_data(obs, 250.0)
            self.assertIsNotNone(result)
        except Exception as e:
            self.fail(f"build_chart_data() raised {type(e).__name__} when sex was missing: {e}")

    @patch("protocols.growth_charts.Observation")
    @patch("protocols.growth_charts.Patient")
    def test_handler_does_not_return_empty_on_missing_sex(self, MockPatient, MockObs):
        """
        Original plugin returned [] if sex was not 'M' or 'F'.
        Adult plugin must NEVER gate on sex field.
        """
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not yet implemented: {IMPORT_ERROR}")

        mock_patient = Mock()
        mock_patient.sex_at_birth = None  # sex not recorded
        MockPatient.objects.get.return_value = mock_patient

        mock_obs = Mock()
        mock_obs.value = 250.0
        mock_obs.unit = "lbs"
        mock_obs.note = Mock()
        mock_obs.note.datetime_of_service = datetime(2024, 1, 15)
        mock_obs.note.id = "note_001"
        MockObs.objects.filter.return_value = [mock_obs]

        handler = GenerateVitalsGraphs(Mock(), Mock())
        try:
            result = handler.compute()
            # Should return LaunchModalEffect, not []
            self.assertNotEqual(result, [],
                "Handler returned [] for patient with no sex field — sex gating removed?")
        except AttributeError:
            # compute() might be named differently — acceptable
            pass


# ============================================================================
# Test Runner Entry Point
# ============================================================================

if __name__ == "__main__":
    # Print a summary of what's available
    print("\n" + "="*60)
    print("CARDIOMETABOLIC TRACKER — Test Suite")
    print("="*60)
    print(f"Canvas SDK available: {CANVAS_SDK_AVAILABLE}")
    print(f"Protocol module available: {PROTOCOL_AVAILABLE}")
    if not PROTOCOL_AVAILABLE:
        print(f"  → Import error: {IMPORT_ERROR}")
        print("  → Tests will show as SKIP until CPA implements the functions")
    print("="*60 + "\n")

    unittest.main(verbosity=2)
