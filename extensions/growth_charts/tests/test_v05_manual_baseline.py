"""
v0.5.0 manual-baseline tests — render-gate cutover (3C), schema-2 metadata
parse, provider-baseline chart anchoring incl. backdated baselines (A1),
dropdown→band precedence + discrepancy notice (decision 5), billing-aware
note narrative (A2), correction trail (A3), plausibility bounds + scope
guard (A4), and the ManualBaselineAPI effect batch.

Kept separate so the v0.1–v0.4 suites stay byte-untouched. Mocked at the SDK
boundary; the live Gate (P10/P11 flows + P1/P4/P7 regression) is the second
gate — mock-green alone is never "done".

# Verifies: v0.5.0 (manual baseline) — spec + 4 amendments approved 2026-06-12
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SRC = (REPO_ROOT / "templates" / "chart.html").read_text(encoding="utf-8")
PROTOCOL_SRC = (REPO_ROOT / "protocols" / "growth_charts.py").read_text(encoding="utf-8")

try:
    from protocols.growth_charts import (
        ADULT_WEIGHT_PLAUSIBILITY_LB,
        BASELINE_DIALOG_HTML,
        BOUNDS_CONFIRM_MESSAGE,
        CORRECTION_HEADER_TEMPLATE,
        CPT_REMINDER_BODY,
        CPT_REMINDER_HEADING,
        CPT_REMINDER_REVIEW_ADDENDUM,
        EMPTY_STATE_MESSAGE,
        MANUAL_AGENT_LABELS,
        MANUAL_AGENT_OPTIONS,
        MANUAL_BASELINE_CUTOVER,
        MANUAL_BASELINE_METADATA_KEY,
        MANUAL_NOTE_TITLE,
        PLUGIN_VERSION,
        GenerateVitalsGraphs,
        ManualBaselineAPI,
        build_chart_data,
        build_correction_header,
        build_discrepancy_notice,
        build_manual_baseline_value,
        build_note_narrative,
        parse_manual_baseline,
        resolve_render_mode,
        validate_baseline_form,
        validate_chart_payload,
    )
    PROTOCOL_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - mirrors earlier suites' skip pattern
    PROTOCOL_AVAILABLE = False
    IMPORT_ERROR = str(exc)


PRE_CUTOVER = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
POST_CUTOVER = datetime(2026, 6, 12, 19, 0, 0, tzinfo=timezone.utc)
BASELINE_DATE = datetime(2026, 4, 17, 0, 0, 0)  # backdated clinical anchor


def manual_record(**overrides) -> dict:
    record = {
        "weight_lb": 243.0,
        "baseline_date": BASELINE_DATE,
        "agent": "tirzepatide",
        "set_by_staff_id": "staff-1",
        "set_at_utc": "2026-06-12T19:00:00Z",
        "note_id": "note-uuid-1",
        "revision": 1,
        "superseded_note_id": None,
    }
    record.update(overrides)
    return record


def metadata_json(**overrides) -> str:
    data = {
        "schema": "2",
        "weight_lb": 243.0,
        "baseline_date": "2026-04-17",
        "agent": "tirzepatide",
        "set_by_staff_id": "staff-1",
        "set_at_utc": "2026-06-12T19:00:00Z",
        "note_id": "note-uuid-1",
        "revision": 1,
        "superseded_note_id": None,
    }
    data.update(overrides)
    return json.dumps(data)


def raw_obs(weeks_after_baseline: float, value_lbs: float, created: datetime) -> dict:
    dt = BASELINE_DATE + timedelta(weeks=weeks_after_baseline)
    return {
        "id": f"obs-{weeks_after_baseline}",
        "value_original": value_lbs,
        "unit_original": "lb",
        "canvas_note_id": None,
        "_loaded_at": "2026-06-12T19:00:00Z",
        "created": created,
        "datetime_of_service": dt,
    }


def valid_form(**overrides) -> dict:
    form = {
        "patient_id": "pt-10",
        "weight_lb": "243.0",
        "baseline_date": "2026-04-17",
        "agent": "tirzepatide",
        "minutes": "15",
        "note_text": "Initial weight-management counseling.",
        "reason": "",
        "confirm_bounds": False,
    }
    form.update(overrides)
    return form


class V05TestCase(unittest.TestCase):
    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not importable: {IMPORT_ERROR}")


class TestParseManualBaseline(V05TestCase):
    """Schema-2 parse is fail-closed: anything malformed → None."""

    def test_valid_schema_2_parses(self):
        parsed = parse_manual_baseline(metadata_json())
        self.assertEqual(parsed["weight_lb"], 243.0)
        self.assertEqual(parsed["baseline_date"], datetime(2026, 4, 17))
        self.assertEqual(parsed["agent"], "tirzepatide")
        self.assertEqual(parsed["revision"], 1)

    def test_unknown_schema_versions_fail_closed(self):
        for schema in ("1", "3", None, ""):
            self.assertIsNone(parse_manual_baseline(metadata_json(schema=schema)), schema)

    def test_malformed_values_fail_closed(self):
        self.assertIsNone(parse_manual_baseline("not json"))
        self.assertIsNone(parse_manual_baseline(None))
        self.assertIsNone(parse_manual_baseline(json.dumps(["list"])))
        self.assertIsNone(parse_manual_baseline(metadata_json(weight_lb="zero")))
        self.assertIsNone(parse_manual_baseline(metadata_json(weight_lb=-5)))
        self.assertIsNone(parse_manual_baseline(metadata_json(baseline_date="not-a-date")))
        self.assertIsNone(parse_manual_baseline(metadata_json(agent="ozempic")))


class TestRenderModeResolution(V05TestCase):
    """Decision 3C: manual wins; record-created cutover splits legacy/empty."""

    def test_manual_baseline_always_wins(self):
        obs = [raw_obs(0, 250.0, PRE_CUTOVER)]
        self.assertEqual(resolve_render_mode(manual_record(), obs), "manual")
        self.assertEqual(resolve_render_mode(manual_record(), []), "manual")

    def test_pre_cutover_records_stay_legacy(self):
        obs = [raw_obs(0, 250.0, PRE_CUTOVER), raw_obs(4, 245.0, POST_CUTOVER)]
        self.assertEqual(resolve_render_mode(None, obs), "legacy")

    def test_post_cutover_records_gate_to_empty(self):
        # The P11 shape: follow-up weights exist (service dates backdated)
        # but every RECORD was created after the cutover.
        obs = [raw_obs(0, 250.0, POST_CUTOVER), raw_obs(4, 245.0, POST_CUTOVER)]
        self.assertEqual(resolve_render_mode(None, obs), "empty")

    def test_no_observations_gate_to_empty(self):
        self.assertEqual(resolve_render_mode(None, []), "empty")

    def test_missing_created_field_does_not_grandfather(self):
        obs = [{"id": "x", "value_original": 250.0, "unit_original": "lb",
                "canvas_note_id": None, "_loaded_at": "t"}]
        self.assertEqual(resolve_render_mode(None, obs), "empty")


class TestLoaderRegressionPin(V05TestCase):
    """Disposition-(c) pattern: the 'created' passthrough is strictly
    additive — every pre-existing key/value is unchanged."""

    @patch("protocols.growth_charts.Observation")
    def test_loader_keys_pre_existing_unchanged_created_added(self, MockObs):
        from protocols.growth_charts import load_weight_observations_raw

        obs = Mock()
        obs.id = "obs-1"
        obs.value = 250.0
        obs.units = "lb"
        obs.created = PRE_CUTOVER
        obs.note_id = None
        MockObs.objects.for_patient.return_value.filter.return_value = [obs]

        raw = load_weight_observations_raw("pt-1")
        self.assertEqual(len(raw), 1)
        row = raw[0]
        # Pre-existing v0.1–v0.4 keys, exact values:
        self.assertEqual(row["id"], "obs-1")
        self.assertEqual(row["value_original"], 250.0)
        self.assertEqual(row["unit_original"], "lb")
        self.assertIn("canvas_note_id", row)
        self.assertIn("_loaded_at", row)
        # Strictly additive:
        self.assertEqual(row["created"], PRE_CUTOVER)
        self.assertEqual(
            set(row.keys()),
            {"id", "value_original", "unit_original", "canvas_note_id",
             "_loaded_at", "created"},
        )


class TestManualPayloadAnchoring(V05TestCase):
    """A1: reference line, %TBWL, and band week-0 anchor to baseline_date."""

    def _payload(self, agent_key="tirzepatide", obs=None, weeks=16.0):
        baseline_override = {
            "date": BASELINE_DATE,
            "value_lbs": 243.0,
            "source_id": "provider-entered",
        }
        return build_chart_data(
            obs if obs is not None else [],
            None,
            agent=MANUAL_AGENT_OPTIONS[agent_key],
            baseline_override=baseline_override,
            band_weeks_override=weeks,
        )

    def test_reference_is_provider_baseline_not_visit_1(self):
        obs = [raw_obs(2, 238.0, POST_CUTOVER), raw_obs(8, 224.0, POST_CUTOVER)]
        payload = self._payload(obs=obs)
        self.assertEqual(payload["baseline_data"]["value_lbs"], 243.0)
        self.assertEqual(payload["baseline_data"]["source_observation_id"], "provider-entered")
        # %TBWL derives from 243.0, not from the first observation (238.0).
        self.assertAlmostEqual(
            payload["datapoints"][0]["tbwl_pct"], (243.0 - 238.0) / 243.0 * 100.0, places=6
        )

    def test_backdated_band_week0_anchors_to_baseline_date(self):
        payload = self._payload(obs=[raw_obs(8, 224.0, POST_CUTOVER)])
        points = payload["expected_band"]["points"]
        self.assertTrue(points)
        self.assertEqual(points[0]["week"], 0.0)
        self.assertEqual(points[0]["date"], BASELINE_DATE)  # NOT entry day
        # Weeks-since-baseline of the follow-up reflects the backdating.
        self.assertAlmostEqual(payload["datapoints"][0]["weeks_since_baseline"], 8.0, places=6)

    def test_band_horizon_override_spans_minimum_weeks(self):
        payload = self._payload(obs=[], weeks=16.0)
        self.assertAlmostEqual(payload["expected_band"]["points"][-1]["week"], 16.0)

    def test_dropdown_band_mapping(self):
        for key, expected_agent in (
            ("semaglutide", "semaglutide_step1"),
            ("tirzepatide", "tirzepatide_surmount1"),
            ("liraglutide", "liraglutide_scale"),
        ):
            payload = self._payload(agent_key=key)
            self.assertEqual(payload["expected_band"]["agent"], expected_agent, key)
            self.assertTrue(payload["expected_band"]["points"], key)

    def test_liraglutide_keeps_scale_disclosure_and_qualifier(self):
        payload = self._payload(agent_key="liraglutide")
        metadata = payload["expected_band"]["band_metadata"]
        self.assertTrue(metadata.get("estimated_bounds"))
        self.assertEqual(metadata.get("legend_qualifier"), "±1 SD")
        self.assertTrue(metadata.get("disclosure"))

    def test_other_renders_no_band_ever(self):
        payload = self._payload(agent_key="other", obs=[raw_obs(8, 224.0, POST_CUTOVER)])
        self.assertEqual(payload["expected_band"]["points"], [])
        self.assertEqual(payload["expected_band"]["agent"], "none")
        # Milestones still present (baseline + milestones without projection).
        self.assertIsInstance(payload["milestones"], list)

    def test_empty_datapoints_valid_only_in_manual_mode(self):
        payload = self._payload(obs=[])
        self.assertEqual(payload["datapoints"], [])
        ok_manual, errors_manual = validate_chart_payload(payload, allow_empty_datapoints=True)
        self.assertTrue(ok_manual, errors_manual)
        ok_legacy, errors_legacy = validate_chart_payload(payload)
        self.assertFalse(ok_legacy)
        self.assertIn("No datapoints to render", errors_legacy)


class TestDiscrepancyNotice(V05TestCase):
    """Decision 5: provider choice wins; contradiction → non-blocking notice."""

    def test_agreement_no_notice(self):
        self.assertIsNone(build_discrepancy_notice("semaglutide_step1", "semaglutide"))

    def test_no_detection_no_notice(self):
        self.assertIsNone(build_discrepancy_notice(None, "semaglutide"))
        self.assertIsNone(build_discrepancy_notice(None, "other"))

    def test_contradiction_notice_verbatim(self):
        self.assertEqual(
            build_discrepancy_notice("semaglutide_step1", "tirzepatide"),
            "Active medication list shows Semaglutide — projection shown for "
            "provider-selected Tirzepatide (Zepbound).",
        )

    def test_other_with_active_med_notice_verbatim(self):
        self.assertEqual(
            build_discrepancy_notice("semaglutide_step1", "other"),
            "Active medication list shows Semaglutide — no projection shown "
            "for provider-selected Other / not on GLP-1 therapy.",
        )


class TestNoteNarrative(V05TestCase):
    """A2: billing-supportive structure; minutes never fabricated."""

    def test_structure_and_minutes(self):
        narrative = build_note_narrative(
            weight_lb=243.0, baseline_date_label="2026-04-17",
            agent_label="Tirzepatide (Zepbound)",
            provider_text="Goals discussed.", minutes=15,
        )
        lines = narrative.split("\n")
        self.assertEqual(lines[0], "Weight-management counseling — provider-confirmed baseline.")
        self.assertIn("Baseline weight: 243.0 lb (as of 2026-04-17).", lines)
        self.assertIn("Medication: Tirzepatide (Zepbound).", lines)
        self.assertIn("Counseling: Goals discussed.", lines)
        self.assertEqual(lines[-1], "Time spent: 15 minutes")

    def test_minutes_blank_stays_blank(self):
        narrative = build_note_narrative(
            weight_lb=243.0, baseline_date_label="2026-04-17",
            agent_label="Tirzepatide (Zepbound)",
            provider_text="x", minutes=None,
        )
        self.assertTrue(narrative.endswith("Time spent: ___ minutes"))
        self.assertNotIn("Time spent: 0", narrative)

    def test_correction_header_prepended_first(self):
        narrative = build_note_narrative(
            weight_lb=241.0, baseline_date_label="2026-04-17",
            agent_label="Tirzepatide (Zepbound)",
            provider_text="x", minutes=None,
            correction_header="CORRECTION — test header.",
        )
        self.assertTrue(narrative.startswith("CORRECTION — test header."))


class TestCorrectionTrail(V05TestCase):
    """A3: header verbatim-pinned; revision/supersession in the metadata."""

    def test_header_verbatim(self):
        header = build_correction_header(
            old_weight_lb=243.0, old_date_label="2026-04-17",
            new_weight_lb=241.0, new_date_label="2026-04-17",
            staff_display="Ali Omrani, MD", timestamp="2026-06-12T20:00:00Z",
            reason="Scale recalibrated",
        )
        self.assertEqual(
            header,
            "CORRECTION — Baseline revised from 243.0 lb (as of 2026-04-17) "
            "to 241.0 lb (as of 2026-04-17) by Ali Omrani, MD, "
            "2026-06-12T20:00:00Z. Reason: Scale recalibrated.",
        )

    def test_metadata_value_schema_and_revision_chain(self):
        value = build_manual_baseline_value(
            weight_lb=241.0, baseline_date_iso="2026-04-17", agent="tirzepatide",
            staff_id="staff-1", note_id="note-2", revision=2,
            superseded_note_id="note-1",
        )
        data = json.loads(value)
        self.assertEqual(data["schema"], "2")
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["superseded_note_id"], "note-1")
        self.assertEqual(data["baseline_date"], "2026-04-17")
        self.assertTrue(data["set_at_utc"].endswith("Z"))
        # Round-trips through the fail-closed parser.
        self.assertIsNotNone(parse_manual_baseline(value))

    def test_no_demographics_in_metadata_value(self):
        value = build_manual_baseline_value(
            weight_lb=243.0, baseline_date_iso="2026-04-17", agent="tirzepatide",
            staff_id="staff-1", note_id="n1", revision=1,
        )
        for forbidden in ("first_name", "last_name", "birth_date", "patient_name"):
            self.assertNotIn(forbidden, value)


class TestValidateBaselineForm(V05TestCase):
    """A1 + A4: hard rejects, future dates, soft bounds, correction reason."""

    def test_valid_form_no_friction(self):
        errors, needs_confirm = validate_baseline_form(valid_form(), is_correction=False)
        self.assertEqual(errors, [])
        self.assertFalse(needs_confirm)

    def test_hard_rejects(self):
        cases = {
            "non-numeric weight": valid_form(weight_lb="heavy"),
            "non-positive weight": valid_form(weight_lb="0"),
            "missing date": valid_form(baseline_date=""),
            "bad date": valid_form(baseline_date="17-04-2026"),
            "missing agent": valid_form(agent=""),
            "unknown agent": valid_form(agent="ozempic"),
            "empty note": valid_form(note_text="   "),
            "bad minutes": valid_form(minutes="ninety"),
            "minutes out of range": valid_form(minutes="0"),
        }
        for label, form in cases.items():
            errors, _ = validate_baseline_form(form, is_correction=False)
            self.assertTrue(errors, label)

    def test_future_date_rejected(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        errors, _ = validate_baseline_form(
            valid_form(baseline_date=tomorrow), is_correction=False
        )
        self.assertIn("Baseline date cannot be in the future", errors)

    def test_today_default_path_accepted(self):
        errors, needs_confirm = validate_baseline_form(
            valid_form(baseline_date=date.today().isoformat()), is_correction=False
        )
        self.assertEqual(errors, [])
        self.assertFalse(needs_confirm)

    def test_soft_bounds_confirm_to_override(self):
        for weight in ("45", "1150"):
            errors, needs_confirm = validate_baseline_form(
                valid_form(weight_lb=weight), is_correction=False
            )
            self.assertEqual(errors, [], weight)
            self.assertTrue(needs_confirm, weight)
        # Confirmed override passes.
        errors, needs_confirm = validate_baseline_form(
            valid_form(weight_lb="1150", confirm_bounds=True), is_correction=False
        )
        self.assertEqual(errors, [])
        self.assertFalse(needs_confirm)

    def test_in_range_boundaries_no_friction(self):
        low, high = ADULT_WEIGHT_PLAUSIBILITY_LB
        for weight in (str(low), str(high)):
            errors, needs_confirm = validate_baseline_form(
                valid_form(weight_lb=weight), is_correction=False
            )
            self.assertEqual(errors, [])
            self.assertFalse(needs_confirm, weight)

    def test_reason_required_only_in_correction_mode(self):
        errors, _ = validate_baseline_form(valid_form(reason=""), is_correction=True)
        self.assertIn("A reason is required when revising an existing baseline", errors)
        errors, _ = validate_baseline_form(valid_form(reason=""), is_correction=False)
        self.assertEqual(errors, [])


class TestBoundsScopeGuard(V05TestCase):
    """A4 scope guard: the adult bounds are wired ONLY into the
    manual-baseline path — never reachable from pediatric-lineage code."""

    def test_constant_referenced_only_from_manual_baseline_path(self):
        # Exactly one definition…
        definitions = re.findall(
            r"^ADULT_WEIGHT_PLAUSIBILITY_LB\s*=", PROTOCOL_SRC, re.MULTILINE
        )
        self.assertEqual(len(definitions), 1)
        # …and exactly two value reads, each inside a manual-baseline-only
        # function. Anything else is a scope-guard violation.
        use_lines = [
            number
            for number, line in enumerate(PROTOCOL_SRC.splitlines(), 1)
            if re.search(r"=\s*ADULT_WEIGHT_PLAUSIBILITY_LB\b", line)
            and not re.match(r"^ADULT_WEIGHT_PLAUSIBILITY_LB\s*=", line)
        ]
        self.assertEqual(len(use_lines), 2, f"unexpected use sites: {use_lines}")

        def function_span(name):
            lines = PROTOCOL_SRC.splitlines()
            start = next(i for i, l in enumerate(lines, 1) if f"def {name}(" in l)
            end = next(
                (i for i, l in enumerate(lines[start:], start + 1)
                 if re.match(r"^(def |class )", l)),
                len(lines),
            )
            return range(start, end)

        allowed = set(function_span("validate_baseline_form")) | set(
            function_span("save_baseline")
        )
        for number in use_lines:
            self.assertIn(
                number, allowed,
                f"ADULT_WEIGHT_PLAUSIBILITY_LB read outside the "
                f"manual-baseline path at line {number}",
            )
        self.assertNotIn("ADULT_WEIGHT_PLAUSIBILITY_LB", TEMPLATE_SRC)
        self.assertNotIn("ADULT_WEIGHT_PLAUSIBILITY_LB", BASELINE_DIALOG_HTML)

    def test_bounds_values(self):
        self.assertEqual(ADULT_WEIGHT_PLAUSIBILITY_LB, (50.0, 1100.0))


def make_api_self(body, staff_id="staff-1"):
    api_self = Mock()
    api_self.request.json.return_value = body
    api_self.request.headers = {"canvas-logged-in-user-id": staff_id}
    api_self.request.headers = MagicMock()
    api_self.request.headers.get.return_value = staff_id
    return api_self


class FakeJSONResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code


class TestManualBaselineAPI(V05TestCase):
    """The POST handler: fail-closed validation, zero partial effects,
    correction trail, bounds confirm flow, CPT reminder payload."""

    def _run(self, body, *, existing_value=None, staff_id="staff-1",
             note_type_fallback=False, patient_exists=True):
        save = ManualBaselineAPI.__dict__["save_baseline"]
        api_self = make_api_self(body, staff_id=staff_id)

        note_type = Mock()
        note_type.id = "nt-uuid"
        location = Mock()
        location.id = "loc-uuid"
        staff = Mock()
        staff.first_name = "Ali"
        staff.last_name = "Omrani"
        staff.suffix = "MD"

        metadata_row = None
        if existing_value is not None:
            metadata_row = Mock()
            metadata_row.value = existing_value

        with patch("protocols.growth_charts.Patient") as MockPatient, \
             patch("protocols.growth_charts.PatientMetadata") as MockMeta, \
             patch("protocols.growth_charts.Staff") as MockStaff, \
             patch("protocols.growth_charts.select_counseling_note_type",
                   return_value=(note_type, note_type_fallback)) as mock_select, \
             patch("protocols.growth_charts.PracticeLocation") as MockLoc, \
             patch("protocols.growth_charts.NoteEffect") as MockNote, \
             patch("protocols.growth_charts.PlanCommand") as MockPlan, \
             patch("protocols.growth_charts.PatientMetadataEffect") as MockMetaEffect, \
             patch("protocols.growth_charts.JSONResponse", FakeJSONResponse):
            MockPatient.objects.filter.return_value.exists.return_value = patient_exists
            (MockMeta.objects.filter.return_value.order_by.return_value
             .first.return_value) = metadata_row
            MockStaff.objects.filter.return_value.first.return_value = staff
            MockLoc.objects.order_by.return_value.first.return_value = location
            MockNote.return_value.create.return_value = "NOTE_EFFECT"
            MockPlan.return_value.originate.return_value = "PLAN_EFFECT"
            MockMetaEffect.return_value.upsert.return_value = "META_EFFECT"
            result = save(api_self)
        return result, {"note": MockNote, "plan": MockPlan,
                        "meta_effect": MockMetaEffect, "select": mock_select}

    def _response(self, result):
        responses = [r for r in result if isinstance(r, FakeJSONResponse)]
        self.assertEqual(len(responses), 1)
        return responses[0]

    def test_unknown_patient_400_no_effects(self):
        result, mocks = self._run(valid_form(), patient_exists=False)
        self.assertEqual(self._response(result).status_code, 400)
        self.assertEqual(len(result), 1)
        mocks["note"].assert_not_called()

    def test_validation_errors_400_no_effects(self):
        result, mocks = self._run(valid_form(agent=""))
        response = self._response(result)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(result), 1)
        mocks["note"].assert_not_called()
        mocks["meta_effect"].assert_not_called()

    def test_bounds_confirm_required_no_effects(self):
        result, mocks = self._run(valid_form(weight_lb="1150"))
        response = self._response(result)
        self.assertEqual(response.data["status"], "confirm_required")
        self.assertEqual(response.data["message"], BOUNDS_CONFIRM_MESSAGE)
        self.assertEqual(len(result), 1)
        mocks["note"].assert_not_called()

    def test_first_save_effect_batch_and_chaining(self):
        result, mocks = self._run(valid_form())
        response = self._response(result)
        self.assertEqual(response.data["status"], "saved")
        self.assertEqual(response.data["revision"], 1)
        self.assertFalse(response.data["is_correction"])
        # All three effects + response, note first.
        self.assertEqual(result[:3], ["NOTE_EFFECT", "PLAN_EFFECT", "META_EFFECT"])
        # PlanCommand targets the SAME user-set UUID the Note was created with.
        note_kwargs = mocks["note"].call_args.kwargs
        plan_kwargs = mocks["plan"].call_args.kwargs
        self.assertEqual(str(note_kwargs["instance_id"]), plan_kwargs["note_uuid"])
        self.assertEqual(note_kwargs["title"], MANUAL_NOTE_TITLE)
        self.assertEqual(note_kwargs["patient_id"], "pt-10")
        self.assertEqual(note_kwargs["provider_id"], "staff-1")
        # Narrative has no correction header on first save.
        self.assertNotIn("CORRECTION", plan_kwargs["narrative"])
        self.assertIn("Time spent: 15 minutes", plan_kwargs["narrative"])
        # Metadata value: schema 2, revision 1, note id linked.
        upsert_value = mocks["meta_effect"].return_value.upsert.call_args.args[0]
        data = json.loads(upsert_value)
        self.assertEqual(data["revision"], 1)
        self.assertEqual(data["note_id"], plan_kwargs["note_uuid"])
        self.assertEqual(data["agent"], "tirzepatide")
        # CPT reminder verbatim, no fallback addendum.
        self.assertEqual(response.data["cpt_reminder"]["heading"], CPT_REMINDER_HEADING)
        self.assertEqual(response.data["cpt_reminder"]["body"], CPT_REMINDER_BODY)
        # Events for the v0.4 log, plugin-classifiable names.
        names = [e["name"] for e in response.data["events"]]
        self.assertIn("python.baseline_saved", names)
        self.assertIn("python.note_created", names)
        self.assertNotIn("python.baseline_bounds_override", names)

    def test_correction_requires_reason(self):
        result, mocks = self._run(valid_form(reason=""), existing_value=metadata_json())
        response = self._response(result)
        self.assertEqual(response.status_code, 400)
        self.assertIn("A reason is required when revising an existing baseline",
                      response.data["errors"])
        mocks["note"].assert_not_called()

    def test_correction_header_revision_and_supersession(self):
        result, mocks = self._run(
            valid_form(weight_lb="241.0", reason="Scale recalibrated"),
            existing_value=metadata_json(),
        )
        response = self._response(result)
        self.assertEqual(response.data["status"], "saved")
        self.assertEqual(response.data["revision"], 2)
        self.assertTrue(response.data["is_correction"])
        narrative = mocks["plan"].call_args.kwargs["narrative"]
        self.assertTrue(narrative.startswith("CORRECTION — Baseline revised from 243.0 lb"))
        self.assertIn("by Ali Omrani, MD,", narrative)
        self.assertIn("Reason: Scale recalibrated.", narrative)
        data = json.loads(mocks["meta_effect"].return_value.upsert.call_args.args[0])
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["superseded_note_id"], "note-uuid-1")

    def test_confirmed_bounds_override_logged_as_event(self):
        result, _ = self._run(
            valid_form(weight_lb="1150", confirm_bounds=True,
                       reason="Bariatric outlier confirmed"),
        )
        response = self._response(result)
        self.assertEqual(response.data["status"], "saved")
        names = [e["name"] for e in response.data["events"]]
        self.assertIn("python.baseline_bounds_override", names)

    def test_review_fallback_addendum_surfaces_in_reminder(self):
        result, _ = self._run(valid_form(), note_type_fallback=True)
        response = self._response(result)
        self.assertTrue(response.data["used_review_fallback"])
        self.assertIn(CPT_REMINDER_REVIEW_ADDENDUM, response.data["cpt_reminder"]["body"])


class TestEmptyStateDocument(V05TestCase):
    """L2 both directions: empty state ships the ask + dialog and nothing
    chart-like; the chart document ships the slot + placeholder."""

    def _empty_payload(self):
        handler = GenerateVitalsGraphs(Mock(), Mock())
        effects = handler._render_empty_state("pt-10")
        self.assertEqual(len(effects), 1)
        return str(getattr(effects[0], "payload", effects[0]))

    def test_empty_state_contents(self):
        payload = self._empty_payload()
        self.assertIn("please enter it to begin tracking", payload)
        self.assertIn("cm-baseline-btn-slot", payload)
        self.assertIn("cm-bl-dialog", payload)
        self.assertIn("CM_BASELINE_CTX", payload)

    def test_empty_state_structural_absence(self):
        payload = self._empty_payload()
        for marker in ("cm-chart", "cm-export-btn", "cm-diagnostics-body",
                       "<svg", "cm-statsbar"):
            self.assertNotIn(marker, payload, marker)

    def test_chart_template_carries_slot_and_dialog_placeholder(self):
        self.assertIn("cm-baseline-btn-slot", TEMPLATE_SRC)
        self.assertIn("baseline_dialog_html", TEMPLATE_SRC)
        self.assertIn("cm-discrepancy", TEMPLATE_SRC)
        self.assertIn("CM_BASELINE_CTX", TEMPLATE_SRC)

    def test_error_document_still_has_no_baseline_ui(self):
        handler = GenerateVitalsGraphs(Mock(), Mock())
        effects = handler._render_error(["No datapoints to render"])
        payload = str(getattr(effects[0], "payload", effects[0]))
        for marker in ("cm-baseline-btn-slot", "cm-bl-dialog", "CM_BASELINE_CTX"):
            self.assertNotIn(marker, payload, marker)


class TestCopyPinsAndDialog(V05TestCase):
    """L4 verbatim pins + dialog schema boundary."""

    def test_empty_state_message_verbatim(self):
        self.assertEqual(
            EMPTY_STATE_MESSAGE,
            "We don't have a confirmed baseline for this patient yet — "
            "please enter it to begin tracking.",
        )

    def test_cpt_reminder_verbatim(self):
        self.assertEqual(CPT_REMINDER_HEADING, "Note saved. Should this note also go to billing?")
        self.assertIn("not billing advice or a guarantee of reimbursement", CPT_REMINDER_BODY)
        self.assertIn("obesity counseling or chronic care management codes", CPT_REMINDER_BODY)
        self.assertEqual(
            CPT_REMINDER_REVIEW_ADDENDUM,
            "Documented as chart review — confirm note type with billing.",
        )

    def test_dialog_has_required_dropdown_options_verbatim(self):
        for label in MANUAL_AGENT_LABELS.values():
            self.assertIn(label, BASELINE_DIALOG_HTML)
        self.assertIn("Which medication is the patient starting?", BASELINE_DIALOG_HTML)
        self.assertIn("Baseline as of", BASELINE_DIALOG_HTML)
        self.assertIn("Time spent counseling (minutes, optional)", BASELINE_DIALOG_HTML)

    def test_dialog_constructs_no_metadata_schema_keys(self):
        # The server owns the metadata schema; the dialog only posts form
        # fields. (Same boundary discipline as the v0.4 support report.)
        # Tokens are matched as JS object-key constructions — UI copy like
        # the "Reason for revision" label is fine.
        for forbidden in ('"schema"', "schema:", "set_by_staff_id",
                          "set_at_utc", "superseded_note_id", "revision:"):
            self.assertNotIn(forbidden, BASELINE_DIALOG_HTML, forbidden)

    def test_dialog_renders_dynamic_strings_with_textcontent_only(self):
        script = BASELINE_DIALOG_HTML[BASELINE_DIALOG_HTML.index("<script>"):]
        self.assertNotIn("innerHTML", script)

    def test_no_future_baseline_in_dialog(self):
        self.assertIn("dateEl.max = todayStr", BASELINE_DIALOG_HTML)


class TestVersionPairing050(V05TestCase):
    def test_version_is_0_5_0_everywhere(self):
        manifest = json.loads(
            (REPO_ROOT / "CANVAS_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(PLUGIN_VERSION, "0.5.0")
        self.assertEqual(manifest["plugin_version"], "0.5.0")

    def test_manifest_registers_api_handler(self):
        manifest = json.loads(
            (REPO_ROOT / "CANVAS_MANIFEST.json").read_text(encoding="utf-8")
        )
        classes = [p["class"] for p in manifest["components"]["protocols"]]
        self.assertIn(
            "cardiometabolic_tracker.protocols.growth_charts:ManualBaselineAPI",
            classes,
        )


if __name__ == "__main__":
    unittest.main()
