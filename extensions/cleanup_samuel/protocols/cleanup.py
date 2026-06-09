"""
cleanup_samuel — TEMPORARY one-shot plugin.

Enters the 5 accidentally-created weight observations for Samuel Alta
in error via Canvas SDK Observation.enter_in_error() effect.

Usage:
  1. This plugin is deployed alongside cardiometabolic_tracker.
  2. Navigate to Samuel Alta's patient chart.
  3. Click "Fix Samuel Alta Data" button in the Vitals section.
  4. Verify confirmation modal appears.
  5. Uninstall this plugin after use.

Bad observations created accidentally on 2025-09-01 through 2026-01-01.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.observation import Observation as ObservationEffect
from canvas_sdk.handlers.action_button import ActionButton

# Samuel Alta's patient key — only act on his chart
SAMUEL_ALTA_KEY = "41fb2a51a18d4948afb9d874a7a2adcb"

# The 5 observation UUIDs accidentally created via FHIR API testing
BAD_OBSERVATION_IDS = [
    "03a90aaf-a08b-4eaa-a3bc-fbed8e39b3e4",  # 2025-09-01  262.0 lb
    "8fd11570-eb11-4858-bf53-f8c5ece60932",  # 2025-10-01  261.0 lb
    "c804e99a-f147-4cfe-a913-0bc071403a1b",  # 2025-11-01  259.5 lb
    "fef62121-13e2-4aac-b658-bf9cb1ad1409",  # 2025-12-01  258.0 lb
    "c8556aa2-1835-479b-b228-11227ea1adc7",  # 2026-01-01  257.0 lb
]


class CleanupSamuelAlta(ActionButton):
    """One-shot cleanup — appears in Vitals section, acts only on Samuel Alta."""

    BUTTON_TITLE = "Fix Samuel Alta Data"
    BUTTON_KEY = "cleanup_samuel_alta"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION

    def handle(self) -> list[Effect]:
        """Enter the 5 bad observations in error and show confirmation modal."""
        # Safety guard — confirm we're on Samuel Alta's chart via context
        patient_key = (self.context or {}).get("patient", {}).get("key", "")
        if patient_key and patient_key != SAMUEL_ALTA_KEY:
            return [LaunchModalEffect(content=(
                "<div style='padding:24px;font-family:Lato,sans-serif'>"
                "<h2 style='color:#c0392b'>Wrong patient</h2>"
                "<p>This cleanup button only works on Samuel Alta's chart. "
                f"Current patient key: <code>{patient_key}</code></p>"
                "</div>"
            )).apply()]

        # Enter each bad observation in error
        effects: list[Effect] = []
        for obs_id in BAD_OBSERVATION_IDS:
            obs_effect = ObservationEffect(observation_id=obs_id)
            effects.append(obs_effect.enter_in_error())

        # Confirmation modal
        count = len(BAD_OBSERVATION_IDS)
        effects.append(LaunchModalEffect(content=(
            "<div style='padding:24px;font-family:Lato,sans-serif'>"
            f"<h2 style='color:#1f8a4c'>&#x2705; Cleanup complete</h2>"
            f"<p>Entered <strong>{count} observations</strong> in error for Samuel Alta.</p>"
            "<ul>"
            "<li>2025-09-01 — 262.0 lb &#10060;</li>"
            "<li>2025-10-01 — 261.0 lb &#10060;</li>"
            "<li>2025-11-01 — 259.5 lb &#10060;</li>"
            "<li>2025-12-01 — 258.0 lb &#10060;</li>"
            "<li>2026-01-01 — 257.0 lb &#10060;</li>"
            "</ul>"
            "<p>Original data preserved: 160 lb (Aug 2025) and 162 lb (Sep 2025).</p>"
            "<p><em>Reload the chart to verify. Then uninstall this plugin.</em></p>"
            "</div>"
        )).apply())

        return effects
