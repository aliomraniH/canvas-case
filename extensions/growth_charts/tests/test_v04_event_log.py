"""
v0.4.0 event-log panel hardening tests — review fixes (R1 local export date,
R2 error-path escaping), support-report export (build_log_export schema,
origin taxonomy, timestamp normalization), de-clinicalized copy (verbatim
pins + "diagnos" scan), and the read-only weight-data table.

Kept separate so the v0.1–v0.3 suites stay byte-untouched. Mocked at the SDK
boundary, same as the earlier suites. Mocked tests cannot catch Canvas runtime
behavior (Blob downloads inside the srcdoc iframe, focus return, key events) —
the live Gate 5 debug-capture session is the second gate.

# Verifies: v0.4.0 (event-log hardening) — spec approved 2026-06-12
"""

from __future__ import annotations

import json
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SRC = (REPO_ROOT / "templates" / "chart.html").read_text(encoding="utf-8")
PROTOCOL_SRC = (REPO_ROOT / "protocols" / "growth_charts.py").read_text(encoding="utf-8")

try:
    from protocols.growth_charts import (
        LOG_EXPORT_SCHEMA_VERSION,
        LOG_ORIGINS,
        PLUGIN_VERSION,
        SOURCE_METHOD_NOT_RECORDED,
        GenerateVitalsGraphs,
        _now_iso,
        assemble_template_context,
        build_log_export,
        build_table_rows,
        classify_log_origin,
    )
    PROTOCOL_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - mirrors earlier suites' skip pattern
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


def make_context(points=None) -> dict:
    points = points if points is not None else [dp(0, 220.0, 220.0), dp(8, 220.0, 206.0)]
    return assemble_template_context(
        patient=make_patient(),
        baseline={"value_lbs": 220.0, "value": 220.0},
        datapoints=points,
        pipeline_timestamps={},
    )


def strip_tags(html_src: str) -> str:
    """Tag-stripped template text, for pinning user-facing strings verbatim
    regardless of inline markup like <strong>."""
    return re.sub(r"<[^>]+>", "", html_src)


class V04TestCase(unittest.TestCase):
    def setUp(self):
        if not PROTOCOL_AVAILABLE:
            self.skipTest(f"Protocol not importable: {IMPORT_ERROR}")


class TestTimestampNormalization(V04TestCase):
    """D2: every Python pipeline timestamp is UTC ISO-8601 with Z suffix,
    fixed at the source — never guessed offsets at render time."""

    def test_now_iso_is_utc_z(self):
        stamp = _now_iso()
        self.assertTrue(stamp.endswith("Z"), stamp)
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        self.assertEqual(parsed.utcoffset(), timedelta(0))
        self.assertLess(abs((datetime.now(timezone.utc) - parsed).total_seconds()), 60)

    def test_pipeline_timestamps_z_suffixed(self):
        ctx = make_context()
        timestamps = ctx["_pipeline_timestamps"]
        self.assertTrue(timestamps)
        for key, value in timestamps.items():
            self.assertTrue(value.endswith("Z"), f"{key}={value!r} not UTC-Z")


class TestRenderErrorEscaping(V04TestCase):
    """R2: error strings can carry observation-entered content, and
    about:srcdoc inherits the EHR parent origin — markup must render inert."""

    def _error_payload(self, errors):
        handler = GenerateVitalsGraphs(Mock(), Mock())
        effects = handler._render_error(errors)
        self.assertEqual(len(effects), 1)
        return str(getattr(effects[0], "payload", effects[0]))

    def test_markup_in_unit_string_renders_inert(self):
        # The exact shape convert_weight_to_lbs produces for a bad unit.
        payload = self._error_payload(
            ["Unknown weight unit: '<img src=x onerror=alert(1)>'"]
        )
        self.assertNotIn("<img", payload)
        self.assertIn("&lt;img", payload)

    def test_every_item_escaped(self):
        payload = self._error_payload(
            ["<script>alert(1)</script>", 'a "quoted" & ampersand <b>']
        )
        self.assertNotIn("<script>", payload)
        self.assertIn("&lt;script&gt;", payload)
        self.assertNotIn("<b>", payload)
        self.assertIn("&amp; ampersand", payload)

    def test_plain_errors_still_readable(self):
        payload = self._error_payload(["No datapoints to render"])
        self.assertIn("No datapoints to render", payload)
        self.assertIn("Unable to render weight trajectory", payload)


class TestLogExportBuilder(V04TestCase):
    """D2: build_log_export is a pure mapping — entries + metadata in,
    schema-valid dict out. Schema knowledge lives only here."""

    EXPECTED_KEYS = {
        "schema_version",
        "plugin_version",
        "generated_at",
        "launch_target",
        "patient_fhir_id",
        "user_agent",
        "entries",
    }

    def _export(self, entries=None, **kwargs):
        defaults = dict(launch_target="right_chart_pane_large", patient_fhir_id="pt-1")
        defaults.update(kwargs)
        return build_log_export(entries or [], **defaults)

    def test_schema_key_set_exact(self):
        self.assertEqual(set(self._export()), self.EXPECTED_KEYS)

    def test_schema_and_plugin_versions(self):
        # v0.5.0: plugin_version pin made symbolic (== PLUGIN_VERSION == the
        # manifest) — a hard-coded version literal cannot survive any bump;
        # the per-cycle literal pin lives in each cycle's own suite.
        export = self._export()
        self.assertEqual(export["schema_version"], LOG_EXPORT_SCHEMA_VERSION)
        self.assertEqual(export["schema_version"], "1")
        self.assertEqual(export["plugin_version"], PLUGIN_VERSION)

    def test_browser_only_fields_default_none(self):
        export = self._export()
        self.assertIsNone(export["generated_at"])
        self.assertIsNone(export["user_agent"])

    def test_entries_normalized_shape(self):
        export = self._export(
            [{"name": "python.observations_loaded", "timestamp_utc": "2026-06-12T15:36:34Z"}]
        )
        self.assertEqual(
            export["entries"],
            [{
                "name": "python.observations_loaded",
                "timestamp_utc": "2026-06-12T15:36:34Z",
                "origin": "plugin",
            }],
        )
        for entry in export["entries"]:
            self.assertIn(entry["origin"], LOG_ORIGINS)

    def test_invalid_origin_reclassified_valid_origin_respected(self):
        export = self._export([
            {"name": "python.x", "timestamp_utc": "t", "origin": "bogus"},
            {"name": "mystery.event", "timestamp_utc": "t", "origin": "host"},
        ])
        self.assertEqual(export["entries"][0]["origin"], "plugin")
        self.assertEqual(export["entries"][1]["origin"], "host")

    def test_no_demographics_anywhere(self):
        # ID only — never name, DOB, or any other demographic (recursive).
        forbidden = {
            "patient_name", "first_name", "last_name", "name",
            "birth_date", "dob", "patient_dob", "sex_at_birth",
        }

        def keys_of(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from keys_of(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from keys_of(item)

        export = self._export([{"name": "js.domContentLoaded", "timestamp_utc": "t"}])
        # entry "name" is the event name, not a demographic — scan above the
        # entries list separately, then entries for the demographic-only keys.
        top_keys = set(export.keys())
        self.assertNotIn("patient_name", top_keys)
        self.assertIn("patient_fhir_id", top_keys)
        entry_forbidden = forbidden - {"name"}
        for key in keys_of(export):
            self.assertNotIn(key, entry_forbidden)

    def test_classify_origin_taxonomy(self):
        cases = {
            "python.observations_loaded": "plugin",
            "js.domContentLoaded": "plugin",
            "AnnotationLayer.render": "plugin",
            "ExportView.render": "plugin",
            "host.s3_background_image": "host",
            "somethingelse.entirely": "unknown",
            "": "unknown",
            None: "unknown",
        }
        for name, expected in cases.items():
            self.assertEqual(classify_log_origin(name), expected, name)

    def test_context_carries_log_export_base(self):
        ctx = make_context()
        base = ctx["log_export_base"]
        self.assertEqual(set(base), self.EXPECTED_KEYS)
        self.assertEqual(base["launch_target"], "right_chart_pane_large")
        self.assertEqual(base["patient_fhir_id"], "pt-1")
        self.assertIsNone(base["generated_at"])
        self.assertIsNone(base["user_agent"])
        names = [e["name"] for e in base["entries"]]
        self.assertIn("python.template_context_assembled", names)
        self.assertTrue(all(n.startswith("python.") for n in names))
        for entry in base["entries"]:
            self.assertEqual(entry["origin"], "plugin")
            self.assertTrue(entry["timestamp_utc"].endswith("Z"))


class TestJsSchemaBoundary(V04TestCase):
    """Approved deviation (a): JS fills exactly generated_at, user_agent, and
    its own entry appends — it constructs no schema keys."""

    def test_js_constructs_no_schema_keys(self):
        for forbidden in ("schema_version", "patient_fhir_id", "launch_target"):
            self.assertNotIn(forbidden, TEMPLATE_SRC, forbidden)
        for fill in ("generated_at:", "user_agent:", "entries:"):
            self.assertIn(fill, TEMPLATE_SRC, fill)

    def test_filename_pattern_filesystem_safe(self):
        self.assertIn("cardiometabolic_tracker_log_", TEMPLATE_SRC)
        self.assertIn("replace(/:/g, '-')", TEMPLATE_SRC)


class TestExportDateLocal(V04TestCase):
    """R1: the export stamps the clinician's LOCAL calendar date."""

    def test_utc_date_stamp_removed(self):
        self.assertNotIn("toISOString().slice(0, 10)", TEMPLATE_SRC)
        self.assertNotIn("toISOString().slice(0,10)", TEMPLATE_SRC)

    def test_local_date_construction_present(self):
        for token in ("getFullYear()", "getMonth() + 1", "getDate()"):
            self.assertIn(token, TEMPLATE_SRC, token)


class TestDeClinicalizedCopy(V04TestCase):
    """D3: no 'diagnostics' in user-facing strings; replacement copy pinned
    verbatim (L4), like SCALE_BOUNDS_DISCLOSURE."""

    FOOTER_HINT = "Hover a point for details. Press Shift+D for technical log."
    PANEL_HEADER = "Plugin event log — technical support only. Not for clinical use."

    def test_footer_hint_pinned_verbatim(self):
        self.assertIn(self.FOOTER_HINT, strip_tags(TEMPLATE_SRC))

    def test_panel_header_pinned_verbatim(self):
        self.assertIn(self.PANEL_HEADER, strip_tags(TEMPLATE_SRC))

    def test_no_diagnos_outside_internal_identifiers(self):
        # Internal identifiers may keep the name (ids, object names — they are
        # never rendered); everything else, including comments, must not say
        # "diagnos". Same shape as the stray-conversion-literal scan.
        allowlist = ("cm-diagnostics", "DiagnosticsPanel")
        for name, src in {"chart.html": TEMPLATE_SRC, "growth_charts.py": PROTOCOL_SRC}.items():
            scrubbed = src
            for token in allowlist:
                scrubbed = scrubbed.replace(token, "")
            offending = [
                ln.strip() for ln in scrubbed.splitlines() if "diagnos" in ln.lower()
            ]
            self.assertEqual(offending, [], f"'diagnos' in user-facing {name}: {offending}")


class TestWeightDataTable(V04TestCase):
    """D4: rows derive ONLY from the already-loaded payload; method is never
    inferred (Gate 2: SDK 0.163.1 Observation has no method/device field)."""

    def test_rows_derive_from_datapoints(self):
        points = [dp(0, 220.0, 220.0), dp(4, 220.0, 215.0), dp(12, 220.0, 196.0)]
        rows = build_table_rows(points, {"value_lbs": 220.0})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["weight_display"], "220.0 lb")
        self.assertEqual(rows[0]["delta_display"], "+0.0 lb")
        self.assertEqual(rows[0]["tbwl_display"], "↓0.0%")
        self.assertEqual(rows[1]["delta_display"], "-5.0 lb")
        self.assertEqual(rows[1]["tbwl_display"], "↓2.3%")
        self.assertEqual(rows[2]["weight_display"], "196.0 lb")
        self.assertEqual(rows[2]["delta_display"], "-24.0 lb")
        self.assertEqual(rows[2]["tbwl_display"], "↓10.9%")
        # Chronological input order is preserved.
        self.assertEqual(
            [r["capture_iso"] for r in rows],
            [p["date_obj"].isoformat() for p in points],
        )

    def test_weight_gain_shows_up_arrow(self):
        rows = build_table_rows([dp(4, 220.0, 226.0)], {"value_lbs": 220.0})
        self.assertEqual(rows[0]["delta_display"], "+6.0 lb")
        self.assertEqual(rows[0]["tbwl_display"], "↑2.7%")

    def test_source_method_not_recorded_universally(self):
        rows = build_table_rows(
            [dp(0, 220.0, 220.0), dp(8, 220.0, 206.0)], {"value_lbs": 220.0}
        )
        self.assertTrue(all(r["source_method"] == SOURCE_METHOD_NOT_RECORDED for r in rows))
        self.assertEqual(SOURCE_METHOD_NOT_RECORDED, "Not recorded")

    def test_capture_iso_aware_normalized_naive_passthrough(self):
        aware = dp(0, 220.0, 220.0)
        aware["date_obj"] = datetime(2025, 1, 6, 14, 30, 0, tzinfo=timezone.utc)
        naive = dp(4, 220.0, 215.0)
        rows = build_table_rows([aware, naive], {"value_lbs": 220.0})
        self.assertEqual(rows[0]["capture_iso"], "2025-01-06T14:30:00Z")
        self.assertEqual(rows[1]["capture_iso"], naive["date_obj"].isoformat())
        self.assertNotIn("+", rows[0]["capture_iso"])

    def test_empty_datapoints_empty_rows(self):
        self.assertEqual(build_table_rows([], {"value_lbs": 220.0}), [])

    def test_context_carries_table_rows(self):
        ctx = make_context()
        self.assertEqual(len(ctx["table_rows"]), 2)
        self.assertEqual(ctx["table_rows"][0]["weight_display"], "220.0 lb")


class TestStructuralAbsence(V04TestCase):
    """L2: the panel, download button, and data table ship in chart.html and
    NEVER in the validation-failure error document — both directions."""

    PANEL_MARKERS = (
        "cm-diagnostics",
        "cm-log-download-btn",
        "cm-log-close-btn",
        "cm-weight-table",
        "cm-log-view-data",
    )

    def test_chart_template_has_panel_markup(self):
        for marker in self.PANEL_MARKERS:
            self.assertIn(marker, TEMPLATE_SRC, marker)

    def test_error_document_has_none_of_it(self):
        handler = GenerateVitalsGraphs(Mock(), Mock())
        effects = handler._render_error(["No datapoints to render"])
        payload = str(getattr(effects[0], "payload", effects[0]))
        for marker in self.PANEL_MARKERS + ("cm-export-btn", "Shift+D"):
            self.assertNotIn(marker, payload, marker)


class TestVersionPairing(V04TestCase):
    def test_version_pairing_manifest_matches_code(self):
        # v0.5.0: made symbolic (was a hard "0.4.0" pin) — manifest↔code
        # pairing is the invariant; the current literal is pinned by the
        # newest cycle's suite.
        manifest = json.loads(
            (REPO_ROOT / "CANVAS_MANIFEST.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["plugin_version"], PLUGIN_VERSION)


if __name__ == "__main__":
    unittest.main()
