"""
cardiometabolic_tracker — adult GLP-1 weight-trajectory plugin.

Adapted from the pediatric growth_charts plugin. Plots each patient's weight
against their OWN baseline (first weight observation) on a calendar-date X-axis,
annotated with % total body weight loss (TBWL). No population percentile curves,
no sex stratification, no age-in-months math.

Organized into five layers (see component_architecture.md):
  Section 1 — Data Loading Layer   (SDK calls, returns plain dicts/lists)
  Section 2 — Processing Layer      (pure functions, no SDK calls)
  Section 3 — Validation Layer      (payload checks, run before any modal)
  Section 4 — Render Layer          (template-context assembly)
  Section 5 — ActionButton Handler  (thin orchestration)
"""

# Defer annotation evaluation (PEP 563): the Canvas RestrictedPython sandbox does
# not expose every builtin (e.g. `object`), and without this, annotations like
# `dict[str, object]` are evaluated at definition time and raise NameError.
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from canvas_sdk.commands import PlanCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.patient_metadata import PatientMetadata as PatientMetadataEffect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.action_button import ActionButton, SHOW_BUTTON_REGEX
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import (
    Medication,
    Note,
    NoteType,
    Observation,
    Patient,
    PatientMetadata,
    PracticeLocation,
    Staff,
)
from canvas_sdk.v1.data.note import NoteTypeCategories

try:
    # Canvas sandbox provides the runtime logger.
    from logger import log
except ImportError:  # running outside the sandbox (e.g. local pytest)
    class _NoopLog:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    log = _NoopLog()

PROCESSING_VERSION = "1.0"

# Shown in the export header (v0.3.0) and the support-report payload (v0.4.0).
# Must match CANVAS_MANIFEST.json's plugin_version — the version-pairing tests
# (TestV03Export.test_plugin_version_matches_manifest and the v0.4/v0.5 suites)
# enforce the pairing so the two cannot drift.
PLUGIN_VERSION = "0.5.0"

# The one modal surface this plugin launches into. Single source for the
# handler's LaunchModalEffect calls AND the support report's launch_target
# field (v0.4.0), so the recorded value cannot drift from the real target.
LAUNCH_TARGET = LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE

# ── v0.5.0 provider-entered manual baseline ──

MANUAL_BASELINE_METADATA_KEY = "cardiometabolic_tracker:manual_baseline"

# Metadata value schema. "2" carries baseline_date (the CLINICAL anchor,
# Amendment 1) distinct from set_at_utc (the entry timestamp). Unknown schema
# versions parse fail-closed to None — never a guess.
MANUAL_BASELINE_SCHEMA_VERSION = "2"

# Render-gate cutover (decision 3C): patients whose earliest weight
# observation RECORD was created before this instant keep the legacy
# visit-1-baseline rendering, byte-identical (covers the nine ZZTEST fixtures
# and all pre-existing demo patients with zero writes to any of them).
# Record-creation time is used, NOT effective/service dates, because seeded
# and imported observations are routinely backdated.
MANUAL_BASELINE_CUTOVER = datetime(2026, 6, 12, 18, 0, 0, tzinfo=timezone.utc)

# Adult weight plausibility bounds, lb — soft bounds for the manual-baseline
# dialog (confirm-to-override outside, hard-reject only non-positive).
# SCOPE GUARD (Amendment 4): this constant and validate_baseline_form are
# wired ONLY into the manual-baseline POST path of THIS adult tracker. This
# plugin's ancestry is a pediatric growth chart — these bounds must never be
# imported by or shared with any pediatric-reachable code path; the v0.5
# suite asserts the constant is referenced nowhere else.
ADULT_WEIGHT_PLAUSIBILITY_LB = (50.0, 1100.0)

# Dialog dropdown → expected-response band agent key. None = no projection
# band, ever (bands are trial-specific; an unconfirmed agent never earns one).
MANUAL_AGENT_OPTIONS = {
    "semaglutide": "semaglutide_step1",
    "tirzepatide": "tirzepatide_surmount1",
    "liraglutide": "liraglutide_scale",
    "other": None,
}
MANUAL_AGENT_LABELS = {
    "semaglutide": "Semaglutide (Wegovy)",
    "tirzepatide": "Tirzepatide (Zepbound)",
    "liraglutide": "Liraglutide (Saxenda)",
    "other": "Other / not on GLP-1 therapy",
}

# Note-type preference for the counseling note (Amendment 2). Tier-1
# read-only inventory of pxbuilder-aomrani (2026-06-12, /admin notetype
# list): "Chronic care management" (chronic_care_management_note, Encounter)
# and "Office visit" (SNOMED 308335008, Encounter) both exist and are active.
# Runtime lookup stays defensive anyway: preferred codes first, then any
# active Encounter type, then Chart Review as the recorded-and-surfaced
# fallback, else fail closed.
PREFERRED_NOTE_TYPE_CODES = ("chronic_care_management_note", "308335008")

MANUAL_NOTE_TITLE = "Weight management — provider-confirmed baseline"

EMPTY_STATE_MESSAGE = (
    "We don't have a confirmed baseline for this patient yet — "
    "please enter it to begin tracking."
)

BOUNDS_CONFIRM_MESSAGE = (
    "This weight is outside the typical adult range — confirm to save."
)

CPT_REMINDER_HEADING = "Note saved. Should this note also go to billing?"
CPT_REMINDER_BODY = (
    "Weight-management counseling documented in this note may be eligible for "
    "CPT reimbursement (for example, obesity counseling or chronic care "
    "management codes). Eligibility depends on payer, plan, and visit context "
    "— please confirm with your billing team. This is a documentation "
    "reminder, not billing advice or a guarantee of reimbursement."
)
# Appended to the reminder only when the note had to fall back to a
# chart-review type (Amendment 2) — also recorded in the deploy report.
CPT_REMINDER_REVIEW_ADDENDUM = (
    "Documented as chart review — confirm note type with billing."
)

# Insurance-grade correction header (Amendment 3) — pinned verbatim by test.
CORRECTION_HEADER_TEMPLATE = (
    "CORRECTION — Baseline revised from {old_weight} lb (as of {old_date}) "
    "to {new_weight} lb (as of {new_date}) by {staff}, {timestamp}. "
    "Reason: {reason}."
)

# The manual-baseline dialog: one shared markup+JS block, kept as a Python
# constant (not a template include) so the empty-state document can be
# assembled without render_to_string and both documents ship the exact same
# dialog. It self-initializes from window.CM_BASELINE_CTX, which each host
# document sets first. Every provider-entered string is rendered back via
# textContent only (R2 discipline); the JS constructs no metadata-schema
# keys — the server owns that schema entirely.
BASELINE_DIALOG_HTML = """
<style>
  #cm-bl-overlay { position: fixed; inset: 0; background: rgba(17,24,33,0.45);
    display: none; align-items: flex-start; justify-content: center;
    z-index: 10000; font-family: Lato, Arial, sans-serif; }
  #cm-bl-dialog { background: #fff; border-radius: 8px; margin-top: 40px;
    width: 440px; max-width: 92vw; max-height: 86vh; overflow: auto;
    padding: 18px 20px; box-shadow: 0 10px 32px rgba(0,0,0,0.35); }
  #cm-bl-dialog h2 { margin: 0 0 4px; font-size: 16px; color: #1f2933; }
  #cm-bl-dialog label { display: block; font-size: 12px; font-weight: 700;
    color: #44505c; margin: 10px 0 3px; }
  #cm-bl-dialog input, #cm-bl-dialog select, #cm-bl-dialog textarea {
    width: 100%; box-sizing: border-box; padding: 6px 8px; font-size: 13px;
    border: 1px solid #c3ccd5; border-radius: 4px; font-family: inherit; }
  #cm-bl-dialog textarea { min-height: 70px; resize: vertical; }
  .cm-bl-required::after { content: " *"; color: #c0392b; }
  .cm-bl-actions { margin-top: 14px; display: flex; gap: 8px; justify-content: flex-end; }
  .cm-bl-actions button { padding: 6px 14px; border-radius: 4px; font-size: 13px;
    cursor: pointer; border: 1px solid #5b86ad; background: #fff; color: #0f619f; }
  .cm-bl-actions button.cm-bl-primary { background: #0f619f; color: #fff; }
  #cm-bl-errors { color: #c0392b; font-size: 12.5px; margin-top: 10px; white-space: pre-line; }
  #cm-bl-confirm { display: none; margin-top: 10px; padding: 8px 10px; font-size: 12.5px;
    background: #fdf1d7; border-left: 3px solid #ecc55f; color: #8a5a00; }
  #cm-bl-success { display: none; }
  #cm-bl-reminder { margin-top: 10px; padding: 10px 12px; background: #eef4f9;
    border-left: 3px solid #0f619f; font-size: 12.5px; color: #1f2933; }
  #cm-bl-reminder-heading { font-weight: 700; margin-bottom: 4px; }
  #cm-bl-reason-wrap { display: none; }
  #cm-baseline-open { padding: 4px 12px; border: 1px solid #5b86ad; border-radius: 4px;
    background: #fff; color: #0f619f; font-size: 12px; font-weight: 700; cursor: pointer; }
</style>
<div id="cm-bl-overlay" role="dialog" aria-modal="true" aria-label="Set baseline">
  <div id="cm-bl-dialog">
    <div id="cm-bl-form-wrap">
      <h2 id="cm-bl-title">Set baseline</h2>
      <label class="cm-bl-required" for="cm-bl-weight">Baseline weight (lb)</label>
      <input id="cm-bl-weight" type="number" step="0.1" min="0">
      <label class="cm-bl-required" for="cm-bl-date">Baseline as of</label>
      <input id="cm-bl-date" type="date">
      <label class="cm-bl-required" for="cm-bl-agent">Which medication is the patient starting?</label>
      <select id="cm-bl-agent">
        <option value="">Select…</option>
        <option value="semaglutide">Semaglutide (Wegovy)</option>
        <option value="tirzepatide">Tirzepatide (Zepbound)</option>
        <option value="liraglutide">Liraglutide (Saxenda)</option>
        <option value="other">Other / not on GLP-1 therapy</option>
      </select>
      <label for="cm-bl-minutes">Time spent counseling (minutes, optional)</label>
      <input id="cm-bl-minutes" type="number" step="1" min="1" max="600">
      <label class="cm-bl-required" for="cm-bl-note">Accompanying note</label>
      <textarea id="cm-bl-note" placeholder="Counseling summary for the patient's Note section"></textarea>
      <div id="cm-bl-reason-wrap">
        <label class="cm-bl-required" for="cm-bl-reason">Reason for revision</label>
        <textarea id="cm-bl-reason" placeholder="Required when revising an existing baseline"></textarea>
      </div>
      <div id="cm-bl-confirm"></div>
      <div id="cm-bl-errors"></div>
      <div class="cm-bl-actions">
        <button type="button" id="cm-bl-cancel">Cancel</button>
        <button type="button" id="cm-bl-save" class="cm-bl-primary">Save</button>
      </div>
    </div>
    <div id="cm-bl-success">
      <h2>Baseline saved</h2>
      <div id="cm-bl-reminder">
        <div id="cm-bl-reminder-heading"></div>
        <div id="cm-bl-reminder-body"></div>
      </div>
      <p id="cm-bl-reopen" style="font-size:12.5px;color:#44505c;"></p>
      <div class="cm-bl-actions">
        <button type="button" id="cm-bl-dismiss" class="cm-bl-primary">Dismiss</button>
      </div>
    </div>
  </div>
</div>
<script>
document.addEventListener('DOMContentLoaded', () => {
  const ctx = window.CM_BASELINE_CTX || null;
  if (!ctx || !ctx.patient_id) return;
  const $ = (id) => document.getElementById(id);
  const slot = $('cm-baseline-btn-slot');
  if (!slot) return;

  const isCorrection = !!ctx.current;
  const openBtn = document.createElement('button');
  openBtn.id = 'cm-baseline-open';
  openBtn.type = 'button';
  openBtn.textContent = isCorrection ? 'Adjust baseline' : 'Set baseline';
  slot.appendChild(openBtn);

  const overlay = $('cm-bl-overlay');
  let confirmBounds = false;

  function openDialog() {
    $('cm-bl-title').textContent = isCorrection ? 'Adjust baseline' : 'Set baseline';
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
    const dateEl = $('cm-bl-date');
    dateEl.max = todayStr;                    // no future baselines
    if (!dateEl.value) dateEl.value = todayStr;  // defaults to today
    if (isCorrection) {
      $('cm-bl-reason-wrap').style.display = 'block';
      if (!$('cm-bl-weight').value && ctx.current.weight_lb) {
        $('cm-bl-weight').value = ctx.current.weight_lb;
      }
      if (ctx.current.agent && !$('cm-bl-agent').value) {
        $('cm-bl-agent').value = ctx.current.agent;
      }
      if (ctx.current.baseline_date_label) dateEl.value = ctx.current.baseline_date_label;
    }
    confirmBounds = false;
    $('cm-bl-confirm').style.display = 'none';
    $('cm-bl-errors').textContent = '';
    overlay.style.display = 'flex';
    $('cm-bl-weight').focus();
  }

  function closeDialog() { overlay.style.display = 'none'; }

  function showSaved(resp) {
    $('cm-bl-form-wrap').style.display = 'none';
    $('cm-bl-success').style.display = 'block';
    const reminder = (resp && resp.cpt_reminder) || {};
    $('cm-bl-reminder-heading').textContent = reminder.heading || '';
    $('cm-bl-reminder-body').textContent = reminder.body || '';
    $('cm-bl-reopen').textContent =
      'Close and reopen Weight Trajectory to see the updated tracking.';
    if (window.DiagnosticsPanel && resp && resp.events) {
      resp.events.forEach((e) => window.DiagnosticsPanel.recordTimestamp(e.name, e.timestamp_utc));
    }
  }

  function save() {
    const payload = {
      patient_id: ctx.patient_id,
      weight_lb: $('cm-bl-weight').value,
      baseline_date: $('cm-bl-date').value,
      agent: $('cm-bl-agent').value,
      minutes: $('cm-bl-minutes').value,
      note_text: $('cm-bl-note').value,
      reason: $('cm-bl-reason') ? $('cm-bl-reason').value : '',
      confirm_bounds: confirmBounds,
    };
    $('cm-bl-errors').textContent = '';
    fetch('/plugin-io/api/cardiometabolic_tracker/baseline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    }).then((r) => r.json().then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (data && data.status === 'saved') { showSaved(data); return; }
        if (data && data.status === 'confirm_required') {
          const c = $('cm-bl-confirm');
          c.textContent = (data.message || 'Confirm to save.') + ' Press Save again to confirm.';
          c.style.display = 'block';
          confirmBounds = true;
          return;
        }
        const errs = (data && data.errors) || ['Save failed' + (ok ? '' : ' (' + 'HTTP error' + ')')];
        $('cm-bl-errors').textContent = errs.join('\\n');
      })
      .catch(() => { $('cm-bl-errors').textContent = 'Network error — baseline was not saved.'; });
  }

  openBtn.addEventListener('click', openDialog);
  $('cm-bl-cancel').addEventListener('click', closeDialog);
  $('cm-bl-save').addEventListener('click', save);
  $('cm-bl-dismiss').addEventListener('click', closeDialog);
});
</script>
"""

# Required keys the template context must always carry.
REQUIRED_TEMPLATE_KEYS = (
    "baseline_data",
    "datapoints",
    "latest_tbwl_pct",
    "_pipeline_timestamps",
)

# Exact pound/kilogram conversion — the ONE source of truth (v0.2.5). The
# international pound is 0.45359237 kg by definition, so both directions are
# exact. No other literal conversion factor may appear in the plugin source;
# TestNoStrayConversionLiterals enforces this. This is the structural fix for
# the kg-vs-% / unit bug class: one constant, used everywhere, round-trip tested.
KG_PER_LB = 0.45359237          # exact by definition
LB_PER_KG = 1.0 / KG_PER_LB     # 2.2046226218...

# Per-patient readout unit. The pipeline normalizes every weight to pounds, so
# `lb` is the coherent display unit for this sandbox (no kg/lb mixing possible);
# selecting a patient's predominant recorded unit is a v-next refinement.
DISPLAY_UNIT = "lb"

# Weight-unit conversion factors to pounds. Every kg-derived factor comes from
# LB_PER_KG so there is exactly one conversion constant in the module.
_WEIGHT_TO_LBS = {
    "lbs": 1.0,
    "lb": 1.0,
    "kg": LB_PER_KG,
    "oz": 1.0 / 16.0,
    "g": LB_PER_KG / 1000.0,
}


def lbs_to_display(value_lbs: float, unit: str = DISPLAY_UNIT) -> float:
    """Convert an internal pounds value to a patient display unit (lb or kg).

    Uses the single conversion constant; raises on an unsupported display unit
    rather than silently returning a wrong number.
    """
    key = str(unit).strip().lower()
    if key in ("lb", "lbs"):
        return float(value_lbs)
    if key == "kg":
        return float(value_lbs) * KG_PER_LB
    raise ValueError(f"Unsupported display unit: {unit!r}")

# ─── v0.2 constants (E1 milestones, E2 expected band, E3 velocity/flags) ───

MILESTONE_PCTS = (5.0, 10.0, 15.0)

# Y-axis padding rule, shared with the template: Python `_axis_domain` is the
# source of truth for milestone suppression; the JS scaffold reads these same
# values from chart_config instead of hardcoding them (drift guard).
AXIS_PAD_FRACTION = 0.1
AXIS_PAD_MIN_LBS = 2.0

DEFAULT_AGENT = "semaglutide_step1"

# Agent detection (A3): lower-case substring match against active-medication
# coding display text. Generic + US brand names per agent.
GLP1_AGENT_KEYWORDS = {
    "semaglutide_step1": ("semaglutide", "wegovy", "ozempic"),
    "tirzepatide_surmount1": ("tirzepatide", "zepbound", "mounjaro"),
    "liraglutide_scale": ("liraglutide", "saxenda", "victoza"),
}

# Expected %TBWL corridors, (week, lower_pct, upper_pct) per agent.
# lower_pct = least expected loss (5th pct), upper_pct = most (95th pct).
# Sources (see glp1_science_reference.md / assumptions_tests_rationale.md):
#   STEP-1     Wilding et al., NEJM 2021;384:989-1002
#   SURMOUNT-1 Jastreboff et al., NEJM 2022;387:205-216 (15 mg arm)
#   SCALE      Pi-Sunyer et al., NEJM 2015;373:11-22 — band is the published
#              mean ±1 SD at 56 wk (v0.2.4; synthesis removed). NB the
#              reference file's 56-wk "8.4" is the published kg figure
#              (-8.0% = 8.4 kg), a known transcription error — see
#              assumptions_tests_rationale.md.
# SCALE band basis (v0.2.4): published mean ±1 SD, 56-week LOCF (Pi-Sunyer
# 2015). estimated_bounds now flags the IMPUTATION/NORMALITY basis (a Gaussian
# ±1 SD approximation of a right-skewed distribution), not synthesis. Shown
# only when estimated_bounds is True.
SCALE_BOUNDS_DISCLOSURE = (
    "Band is the published mean ±1 SD (−8.0 ± 6.7%) at 56 weeks, full analysis "
    "set with LOCF imputation (Pi-Sunyer 2015). Weight-loss response is right-skewed, so "
    "the symmetric band is an approximation; ≥5% / >10% / >15% of patients "
    "reached those losses in 63% / 33% / 14% of cases respectively."
)

# Citation volume/page strings verified against glp1_science_reference.md
# (Gate 1, 2026-06-10): 2021;384:989-1002 / 2022;387:205-216 / 2015;373:11-22.
EXPECTED_RESPONSE_BANDS = {
    "semaglutide_step1": {
        "label": "STEP-1",
        "metadata": {
            "trial": "STEP 1",
            "citation": (
                "Wilding JPH, et al. Once-Weekly Semaglutide in Adults with "
                "Overweight or Obesity. N Engl J Med 2021;384:989-1002."
            ),
            "summary": "Mean −14.9% body weight at 68 weeks vs −2.4% placebo (n=1,961).",
            "estimated_bounds": False,
        },
        "points": (
            (0, 0.0, 0.0), (4, 0.5, 4.5), (8, 1.0, 7.0), (12, 2.0, 11.0),
            (16, 3.0, 13.5), (20, 4.0, 15.0), (24, 5.0, 16.5), (36, 6.0, 19.0),
            (52, 7.0, 21.0), (68, 7.5, 22.0),
        ),
    },
    "tirzepatide_surmount1": {
        "label": "SURMOUNT-1",
        "metadata": {
            "trial": "SURMOUNT-1",
            "citation": (
                "Jastreboff AM, et al. Tirzepatide Once Weekly for the "
                "Treatment of Obesity. N Engl J Med 2022;387:205-216."
            ),
            "summary": "Mean −15.0% to −20.9% at 72 weeks by dose vs −3.1% placebo (n=2,539).",
            "estimated_bounds": False,
        },
        "points": (
            (0, 0.0, 0.0), (4, 0.8, 5.5), (8, 2.0, 10.0), (12, 3.5, 14.5),
            (16, 5.0, 18.0), (24, 8.0, 22.0), (36, 10.0, 26.0),
            (52, 12.0, 28.5), (72, 13.0, 31.0),
        ),
    },
    "liraglutide_scale": {
        "label": "SCALE",
        "metadata": {
            "trial": "SCALE",
            "citation": (
                "Pi-Sunyer X, et al. A Randomized, Controlled Trial of 3.0 mg "
                "of Liraglutide in Weight Management. N Engl J Med 2015;373:11-22."
            ),
            "summary": "Mean −8.0% (8.4 kg) at 56 weeks vs −2.6% placebo (n=3,731).",
            # v0.2.4: True now flags the imputation/normality basis (Gaussian
            # ±1 SD over a right-skewed outcome), NOT synthesized bounds.
            "estimated_bounds": True,
            "legend_qualifier": "±1 SD",
            "disclosure": SCALE_BOUNDS_DISCLOSURE,
            # Published 56-week LOCF distribution (signed: negative = loss).
            "center": -8.0,
            "sd": 6.7,
            "lower_bound": -1.3,   # mean + 1 SD, toward zero
            "upper_bound": -14.7,  # mean - 1 SD, toward greater loss
            # Published absolute population mean + trial mean baseline
            # (Pi-Sunyer 2015, liraglutide arm). The lb equivalent is computed
            # from LB_PER_KG (not hardcoded) for the dual-unit population line;
            # this is a POPULATION figure, never an individual patient target.
            "absolute_mean_kg": 8.4,
            "mean_baseline_kg": 106.2,
            # Published categorical responder rates — DATA ONLY in v0.2.4
            # (no marker rendering; Gate 5 deferred that to v-next).
            "scale_cdf_anchors": [
                {"threshold_pct": 5, "responders_pct": 63.2},
                {"threshold_pct": 10, "responders_pct": 33.1},
                {"threshold_pct": 15, "responders_pct": 14.4},
            ],
        },
        # v0.2.4: drawn from the published mean ±1 SD at the 56-week endpoint
        # (1.3-14.7 %TBWL in the internal positive-loss convention), linearly
        # interpolated from baseline — no per-week SDs were published. The
        # 0.5x/1.5x synthesized rows are gone.
        "points": (
            (0, 0.0, 0.0), (56, 1.3, 14.7),
        ),
    },
}

VELOCITY_WINDOW_WEEKS = 4.0
VELOCITY_MIN_SPAN_DAYS = 14.0
PLATEAU_WINDOW_WEEKS = 8.0
PLATEAU_MIN_WEEK = 8.0          # plateau/regain evaluated only after week 8
PLATEAU_ABS_DELTA_PCT = 0.5     # |ΔTBWL| over trailing 8 wk below this = plateau
REGAIN_DELTA_PCT = -0.5         # ΔTBWL at or below this over trailing 8 wk = regain
RAPID_VELOCITY_PCT_PER_WEEK = 1.0

# Informational decision support only — copy is descriptive, never directive.
FLAG_DEFINITIONS = {
    "plateau": {
        "key": "plateau",
        "label": "Plateau",
        "severity": "amber",
        "message": "Weight loss has slowed — consider reviewing dose/adherence.",
    },
    "regain": {
        "key": "regain",
        "label": "Regain",
        "severity": "amber",
        "message": "Weight is trending upward over the last 8 weeks — consider reviewing adherence and follow-up.",
    },
    "rapid_loss": {
        "key": "rapid_loss",
        "label": "Rapid loss",
        "severity": "red",
        "message": "Weight loss has exceeded 1.0% per week over the last 4 weeks — consider reviewing nutrition and tolerability.",
    },
}


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string with Z suffix (v0.4.0; was naive
    local, which made Python pipeline entries disagree with the JS entries'
    toISOString() in the event log and export). UTC-Z is the storage/transport
    format only — nothing clinician-facing renders these values (audited
    v0.4.0); any future display must convert to local at the display point."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_default(value):
    """JSON serializer for datetimes — emits ISO-8601 so JS `new Date()` parses cleanly."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _strip_tz(dt):
    """Strip timezone info so aware (FHIR-created) and naive (UI-created)
    datetimes compare without TypeError. Use as the key for every
    sort/min/max over observation dates — never compare them raw."""
    if dt is not None and hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# ─────────────────────────────────────────────────────────────
# SECTION 1: Data Loading Layer
# ─────────────────────────────────────────────────────────────
# All functions here perform SDK calls and return plain dicts/lists with no
# side effects, so they can be exercised in isolation with a mocked SDK.


def load_patient_demographics(patient_id: str) -> dict:
    """Load patient demographics.

    `sex_at_birth` is captured for future use but NEVER gates rendering.
    Returns a plain dict tagged with `_component` and `_loaded_at`.
    """
    sex_at_birth = None
    birth_date = None
    first_name = None
    last_name = None
    try:
        patient = Patient.objects.get(id=patient_id)
        sex_at_birth = getattr(patient, "sex_at_birth", None)
        birth_date = getattr(patient, "birth_date", None)
        # v0.3.0 export header. SDK fields verified: Patient.first_name /
        # Patient.last_name (canvas_sdk/v1/data/patient.py).
        first_name = getattr(patient, "first_name", None)
        last_name = getattr(patient, "last_name", None)
    except Patient.DoesNotExist:
        log.warning("Patient %s not found while loading demographics", patient_id)

    return {
        "patient_id": patient_id,
        "sex_at_birth": sex_at_birth,
        "birth_date": birth_date,
        "first_name": first_name,
        "last_name": last_name,
        "_component": "patient_info",
        "_loaded_at": _now_iso(),
    }


def load_weight_observations_raw(patient_id: str) -> list[dict]:
    """Query weight observations only. Does NOT fetch notes (that's batch_load_notes).

    Each returned dict carries raw values plus the originating note id.
    """
    observations = Observation.objects.for_patient(patient_id).filter(name="weight")

    raw: list[dict] = []
    for obs in observations:
        if obs.value is None:
            continue
        raw.append(
            {
                "id": getattr(obs, "id", None),
                "value_original": obs.value,
                "unit_original": getattr(obs, "units", None),  # SDK field is 'units' (plural)
                "canvas_note_id": _note_id_of(obs),
                "_loaded_at": _now_iso(),
                # v0.5.0 STRICTLY ADDITIVE: record-creation time for the
                # manual-baseline render-gate cutover. All pre-existing keys
                # above are regression-pinned unchanged by the v0.5 suite.
                "created": getattr(obs, "created", None),
            }
        )
    return raw


def load_manual_baseline(patient_id: str) -> dict | None:
    """Read the provider-entered baseline (v0.5.0) for the render gate.
    Fail-closed: missing row or malformed value → None."""
    try:
        row = (
            PatientMetadata.objects.filter(
                patient__id=patient_id, key=MANUAL_BASELINE_METADATA_KEY
            )
            .order_by("-modified")
            .first()
        )
    except Exception as exc:  # metadata read must never block the chart
        log.warning(
            "Manual-baseline metadata lookup failed for patient %s (%s: %s)",
            patient_id, type(exc).__name__, exc,
        )
        return None
    if row is None:
        return None
    return parse_manual_baseline(getattr(row, "value", None))


def select_counseling_note_type() -> tuple[object | None, bool]:
    """(note type, used_review_fallback) for the manual-baseline counseling
    note (Amendment 2). Preference: Tier-1-verified encounter codes →
    any active Encounter type → Chart Review (recorded fallback) → None
    (caller fails closed)."""
    encounter = NoteType.objects.filter(
        category=NoteTypeCategories.ENCOUNTER, is_active=True
    )
    for code in PREFERRED_NOTE_TYPE_CODES:
        note_type = encounter.filter(code=code).order_by("-dbid").first()
        if note_type is not None:
            return note_type, False
    note_type = encounter.order_by("-dbid").first()
    if note_type is not None:
        return note_type, False
    note_type = (
        NoteType.objects.filter(category=NoteTypeCategories.REVIEW, is_active=True)
        .order_by("-dbid")
        .first()
    )
    if note_type is not None:
        return note_type, True
    return None, False


def staff_display_name(staff_id) -> str:
    """'First Last, Suffix' for the correction header; falls back to the id
    (a real identifier — never a fabricated placeholder)."""
    try:
        staff = Staff.objects.filter(id=staff_id).first()
    except Exception:
        staff = None
    if staff is None:
        return str(staff_id)
    parts = " ".join(
        p for p in (getattr(staff, "first_name", ""), getattr(staff, "last_name", "")) if p
    )
    suffix = getattr(staff, "suffix", "") or ""
    if parts and suffix:
        return f"{parts}, {suffix}"
    return parts or str(staff_id)


def batch_load_notes(note_ids: list[str]) -> dict[str, object]:
    """SINGLE query for all notes — the N+1 fix.

    Observation.note_id is a BigIntegerField storing Note.dbid (the integer PK),
    NOT the Note.id UUID field. Filter on dbid, key the result by str(dbid) so
    that attach_dates_to_observations can do O(1) lookups by the same value.

    Returns {str(note_dbid): Note} for O(1) lookup during processing.
    """
    if not note_ids:
        return {}
    # Convert to integers (Observation.note_id is BigIntegerField)
    int_ids: list[int] = []
    for nid in note_ids:
        try:
            int_ids.append(int(nid))
        except (ValueError, TypeError):
            log.warning("Skipping non-integer note_id: %r", nid)
    if not int_ids:
        return {}
    notes = Note.objects.filter(dbid__in=int_ids)
    return {str(getattr(note, "dbid", "")): note for note in notes}


def attach_dates_to_observations(
    observations_raw: list[dict],
    notes_by_id: dict,
) -> list[dict]:
    """Join observations with their note dates using the pre-fetched notes dict.

    Pure dict manipulation — no DB calls. Observations whose note is missing are
    skipped with a logged warning rather than silently guessing a date.
    """
    joined: list[dict] = []
    for obs in observations_raw:
        note = notes_by_id.get(str(obs.get("canvas_note_id")))
        if note is None:
            log.warning(
                "No note for observation %s (note_id=%s); skipping",
                obs.get("id"),
                obs.get("canvas_note_id"),
            )
            continue
        dos = getattr(note, "datetime_of_service", None)
        if dos is None:
            log.warning("Note %s has no datetime_of_service; skipping", obs.get("canvas_note_id"))
            continue
        enriched = dict(obs)
        enriched["datetime_of_service"] = dos
        joined.append(enriched)
    return joined


def _match_glp1_agents(patient_id: str) -> tuple:
    """(matched agent-key set, error string|None) from the active-med list.

    Matches active-medication coding display text against GLP1_AGENT_KEYWORDS.
    The broad except is a deliberate addendum requirement: a medication-model
    schema surprise must degrade gracefully, never crash the chart.
    Field access verified against canvas_sdk 0.163.1 source + docs:
    Medication.objects.for_patient(id).active(); med.codings.all() → .display.
    """
    try:
        medications = (
            Medication.objects.for_patient(patient_id)
            .active()
            .prefetch_related("codings")  # one query for all codings, not one per med
        )
        matched: set[str] = set()
        for med in medications:
            texts: list[str] = []
            codings = getattr(med, "codings", None)
            if codings is not None:
                for coding in codings.all():
                    display = getattr(coding, "display", None)
                    if display:
                        texts.append(str(display).lower())
            for agent, keywords in GLP1_AGENT_KEYWORDS.items():
                if any(kw in text for text in texts for kw in keywords):
                    matched.add(agent)
        return matched, None
    except Exception as exc:  # degrade, never block the chart
        return set(), f"{type(exc).__name__}: {exc}"


def detect_glp1_agent(patient_id: str) -> str:
    """Detect which GLP-1 agent the patient is on, for expected-band selection.

    Exactly one agent matched → that agent. No match, multiple matches, or ANY
    query/schema error → DEFAULT_AGENT with the fallback reason logged.
    (v0.5.0: matching core extracted to _match_glp1_agents so the manual-
    baseline discrepancy check can see "no active GLP-1" distinctly; this
    function's legacy semantics are unchanged and regression-pinned.)
    """
    matched, error = _match_glp1_agents(patient_id)
    if error is not None:
        log.warning(
            "Medication lookup failed for patient %s (%s); defaulting to %s",
            patient_id, error, DEFAULT_AGENT,
        )
        return DEFAULT_AGENT
    if len(matched) == 1:
        return next(iter(matched))
    if matched:
        log.warning(
            "Multiple GLP-1 agents matched for patient %s (%s); defaulting to %s",
            patient_id, sorted(matched), DEFAULT_AGENT,
        )
    else:
        log.info(
            "No GLP-1 medication matched for patient %s; defaulting to %s",
            patient_id, DEFAULT_AGENT,
        )
    return DEFAULT_AGENT


def detect_glp1_agent_raw(patient_id: str) -> str | None:
    """Strict detection for the v0.5.0 discrepancy check: exactly one active
    GLP-1 match → that agent key; no match / ambiguous / lookup error → None
    (meaning "no contradiction evidence" — never a guessed default)."""
    matched, error = _match_glp1_agents(patient_id)
    if error is None and len(matched) == 1:
        return next(iter(matched))
    return None


# ─────────────────────────────────────────────────────────────
# SECTION 2: Processing Layer
# ─────────────────────────────────────────────────────────────
# Pure functions: no DB calls, no side effects. Accept primitives/dicts (and,
# for convenience in tests, raw SDK-like observation objects).


def convert_weight_to_lbs(value: float, unit: str) -> float:
    """Convert any supported weight unit to pounds. Case-insensitive.

    Raises ValueError for an unknown unit (never silently returns a wrong value).
    """
    if unit is None:
        raise ValueError("Missing weight unit")
    key = str(unit).strip().lower()
    if key not in _WEIGHT_TO_LBS:
        raise ValueError(f"Unknown weight unit: {unit!r}")
    return float(value) * _WEIGHT_TO_LBS[key]


def _obs_value(obs) -> float:
    """Read a weight value from a raw dict or an SDK-like object."""
    if isinstance(obs, dict):
        return float(obs.get("value_original"))
    return float(obs.value)


def _obs_unit(obs) -> str:
    """Read a weight unit from a raw dict or an SDK-like object.

    The Canvas SDK Observation model uses 'units' (plural), not 'unit'.
    """
    if isinstance(obs, dict):
        return obs.get("unit_original")
    return getattr(obs, "units", None)  # SDK field is 'units' (plural)


def _obs_date(obs):
    """Read datetime_of_service from a raw dict (post-attach) or an SDK-like object."""
    if isinstance(obs, dict):
        return obs.get("datetime_of_service")
    note = getattr(obs, "note", None)
    return getattr(note, "datetime_of_service", None) if note is not None else None


def _obs_id(obs):
    """Read the observation id from a raw dict or an SDK-like object."""
    if isinstance(obs, dict):
        return obs.get("id")
    return getattr(obs, "id", None)


def _note_id_of(obs) -> str:
    """Read the note dbid from an SDK-like observation object.

    Observation.note_id is a BigIntegerField that stores Note.dbid (the integer
    primary key). We never use Note.id (the UUIDField) here because
    Note.objects.filter(dbid__in=...) is the correct lookup path.
    """
    note_id = getattr(obs, "note_id", None)
    return str(note_id) if note_id is not None else None


def _baseline_record(observations: list) -> dict:
    """Internal: full baseline record used by the pipeline.

    Sorts ascending by datetime_of_service; ties on the earliest date resolve to
    the higher value (conservative baseline → larger denominator).
    Returns {"value_lbs": float, "date": datetime, "source_id": str}.
    Raises ValueError on an empty list.
    """
    if not observations:
        raise ValueError("Cannot compute baseline from zero observations")

    def sort_key(obs):
        date = _strip_tz(_obs_date(obs))
        # Earliest date first; within a date, higher weight (in lbs) first.
        return (date, -convert_weight_to_lbs(_obs_value(obs), _obs_unit(obs)))

    earliest = sorted(observations, key=sort_key)[0]
    return {
        "value_lbs": convert_weight_to_lbs(_obs_value(earliest), _obs_unit(earliest)),
        "date": _obs_date(earliest),
        "source_id": _obs_id(earliest),
    }


def compute_baseline(observations: list) -> float:
    """Select the earliest observation as baseline and return its weight in lbs.

    Baseline = first observation sorted ascending by datetime_of_service.
    Raises ValueError on an empty list.
    """
    return _baseline_record(observations)["value_lbs"]


def calculate_tbwl(baseline_lbs: float, current_lbs: float) -> float:
    """% TBWL = ((baseline - current) / baseline) * 100.

    Positive = weight lost. Raises ValueError if baseline <= 0.
    """
    baseline_lbs = float(baseline_lbs)
    if baseline_lbs <= 0:
        raise ValueError("Baseline weight must be positive")
    return ((baseline_lbs - float(current_lbs)) / baseline_lbs) * 100.0


def calculate_weeks_since_baseline(baseline_date: datetime, current_date: datetime) -> float:
    """Float weeks between two dates. Negative if current precedes baseline.

    Dates are tz-stripped first: subtracting an aware (FHIR) from a naive (UI)
    datetime raises TypeError."""
    delta = _strip_tz(current_date) - _strip_tz(baseline_date)
    return delta.total_seconds() / (7 * 24 * 60 * 60)


def format_date_mmmyyyy(dt: datetime) -> str:
    """Return a 'Jan 2024' style date string (3-letter month)."""
    return dt.strftime("%b %Y")


def build_observation_processed(obs_raw, baseline: dict) -> dict:
    """Convert a single observation to its processed form.

    Raw fields are preserved verbatim in a nested `raw` dict and are NEVER
    overwritten by the derived fields.

    `obs_raw` may be a raw loader dict (with datetime_of_service attached) or an
    SDK-like observation object. `baseline` is the compute_baseline() result.
    """
    value_original = _obs_value(obs_raw)
    unit_original = _obs_unit(obs_raw)
    date_obj = _obs_date(obs_raw)
    value_lbs = convert_weight_to_lbs(value_original, unit_original)

    baseline_lbs = baseline["value_lbs"]
    baseline_date = baseline["date"]

    if isinstance(obs_raw, dict):
        canvas_note_id = obs_raw.get("canvas_note_id")
        raw_loaded_at = obs_raw.get("_loaded_at")
    else:
        canvas_note_id = _note_id_of(obs_raw)
        raw_loaded_at = None

    return {
        # processed / derived
        "id": _obs_id(obs_raw),
        "value_lbs": value_lbs,
        "date_label": format_date_mmmyyyy(date_obj),
        "date_obj": date_obj,
        "weeks_since_baseline": calculate_weeks_since_baseline(baseline_date, date_obj),
        "tbwl_pct": calculate_tbwl(baseline_lbs, value_lbs),
        "processed_at": _now_iso(),
        "processing_version": PROCESSING_VERSION,
        # raw snapshot — immutable, never overwritten above
        "raw": {
            "value_original": value_original,
            "unit_original": unit_original,
            "canvas_note_id": canvas_note_id,
            "_loaded_at": raw_loaded_at,
        },
    }


# ── v0.2 pure functions ──


def dedupe_same_day(observations_with_dates: list) -> list:
    """Collapse same-calendar-day observations into one averaged point (A6).

    Decision: average (not latest-wins) — deterministic regardless of row
    order (Observation ids are UUIDs, so "latest" has no reliable tie-break
    when entries share a datetime_of_service) and damps re-measurement noise.
    Mixed units on the same day are averaged in lbs and emitted as 'lbs'.
    Observations without a date pass through untouched.
    """
    groups: dict = {}
    order: list = []
    passthrough: list = []
    for obs in observations_with_dates:
        dt = _obs_date(obs)
        if dt is None:
            passthrough.append(obs)
            continue
        day = dt.date() if hasattr(dt, "date") else dt
        if day not in groups:
            groups[day] = []
            order.append(day)
        groups[day].append(obs)

    out: list = []
    for day in order:
        group = groups[day]
        if len(group) == 1:
            out.append(group[0])
            continue
        lbs_values = [convert_weight_to_lbs(_obs_value(o), _obs_unit(o)) for o in group]
        first = group[0]
        merged = {
            "id": _obs_id(first),
            "value_original": sum(lbs_values) / len(lbs_values),
            "unit_original": "lbs",
            "canvas_note_id": (
                first.get("canvas_note_id") if isinstance(first, dict) else _note_id_of(first)
            ),
            "datetime_of_service": min(
                (_obs_date(o) for o in group), key=_strip_tz
            ),
            "_loaded_at": first.get("_loaded_at") if isinstance(first, dict) else None,
            "deduped_from": [_obs_id(o) for o in group],
        }
        out.append(merged)
    return out + passthrough


def _axis_domain(weights_lbs: list) -> tuple | None:
    """The y-domain the chart will use: pad = max(range * AXIS_PAD_FRACTION,
    AXIS_PAD_MIN_LBS). The template reads the same constants from chart_config,
    so the rule is defined exactly once. Conservative vs d3 `.nice()`, which
    may round the rendered domain slightly outward — documented as intentional.
    """
    weights = [float(w) for w in weights_lbs if w is not None]
    if not weights:
        return None
    lo, hi = min(weights), max(weights)
    pad = max((hi - lo) * AXIS_PAD_FRACTION, AXIS_PAD_MIN_LBS)
    return (lo - pad, hi + pad)


def _collect_axis_weights(datapoints: list[dict], baseline_lbs: float, expected_band: dict) -> list:
    """Every weight that drives the y-axis, in one place.

    Any future plotted layer must register its weights here so the milestone
    suppression domain (`_axis_domain`) and the rendered axis stay in lockstep.
    Milestone lines themselves are deliberately excluded (they never widen
    the axis).
    """
    weights = [dp.get("value_lbs") for dp in datapoints]
    weights.append(baseline_lbs)
    for band_point in expected_band.get("points") or []:
        weights.append(band_point.get("lower_lbs"))
        weights.append(band_point.get("upper_lbs"))
    return weights


def compute_milestone_lines(
    baseline_lbs: float,
    axis_weights_lbs: list,
    latest_tbwl_pct: float | None = None,
    display_unit: str = DISPLAY_UNIT,
) -> list[dict]:
    """E1: 5/10/15% TBWL reference lines, suppressed outside the y-domain.

    `axis_weights_lbs` must be everything that drives the axis: datapoints,
    baseline, and expected-band edge weights. Milestones never widen the axis.
    """
    if baseline_lbs is None or float(baseline_lbs) <= 0:
        return []
    domain = _axis_domain(axis_weights_lbs)
    if domain is None:
        return []
    baseline_disp = lbs_to_display(baseline_lbs, display_unit)
    lines: list[dict] = []
    for pct in MILESTONE_PCTS:
        weight = float(baseline_lbs) * (1.0 - pct / 100.0)
        if domain[0] <= weight <= domain[1]:
            weight_disp = baseline_disp * (1.0 - pct / 100.0)
            lines.append({
                "pct": pct,
                "weight_lbs": weight,
                # Patient-unit weight alongside the percent (v0.2.5), e.g.
                # "5% — 209 lb". Computed from the baseline in the display unit,
                # never from any trial figure.
                "weight_display": weight_disp,
                "display_unit": display_unit,
                "label": f"{pct:g}% — {weight_disp:.0f} {display_unit}",
                "crossed": latest_tbwl_pct is not None and float(latest_tbwl_pct) >= pct,
            })
    return lines


def _enrich_population_line(meta: dict) -> dict:
    """Add a dual-unit POPULATION line to band metadata (v0.2.5 / B4).

    Only when the trial reports an absolute mean (`absolute_mean_kg`); the lb
    equivalent is computed from LB_PER_KG, never hardcoded. Percent-only trials
    are returned unchanged — no kg is invented. The line is explicitly labeled
    a population figure with the trial's mean baseline so it cannot be mistaken
    for an individual patient's target.
    """
    kg = meta.get("absolute_mean_kg")
    if kg is None:
        return dict(meta)  # copy — preserve prior dict(metadata) semantics
    lb = kg * LB_PER_KG
    pct = meta.get("center")
    base_kg = meta.get("mean_baseline_kg")
    base_clause = f", at a {base_kg:g} kg mean baseline" if base_kg else ""
    enriched = dict(meta)
    enriched["population_line"] = (
        f"{meta.get('trial', 'Trial')} population: {pct:.1f}% mean "
        f"({kg:g} kg ≈ {lb:.1f} lb lost{base_clause}). "
        f"Your patient's band uses the {pct:.1f}% figure applied to their own baseline."
    )
    return enriched


def _interp_band_at_week(table: tuple, week: float) -> tuple:
    """Linear interpolation of (week, lower_pct, upper_pct) rows; clamps outside."""
    if week <= table[0][0]:
        return (table[0][1], table[0][2])
    if week >= table[-1][0]:
        return (table[-1][1], table[-1][2])
    for (w0, lo0, hi0), (w1, lo1, hi1) in zip(table, table[1:]):
        if w0 <= week <= w1:
            f = (week - w0) / (w1 - w0) if w1 > w0 else 0.0
            return (lo0 + f * (lo1 - lo0), hi0 + f * (hi1 - hi0))
    return (table[-1][1], table[-1][2])


def build_expected_band(
    baseline_lbs: float,
    baseline_date,
    max_weeks: float,
    agent: str = DEFAULT_AGENT,
) -> dict:
    """E2: expected-response corridor, clipped to the observed week range.

    Returns {"agent", "label", "points": [...]}; each point carries week, date,
    lower/upper %TBWL and the corresponding weights. Note the inversion:
    upper_pct (more loss) maps to the LOWER weight (upper_lbs < lower_lbs).
    Empty points when max_weeks <= 0 (e.g. a single observation) so the band
    never stretches the axes.
    """
    if agent not in EXPECTED_RESPONSE_BANDS:
        agent = DEFAULT_AGENT
    band_def = EXPECTED_RESPONSE_BANDS[agent]
    result = {
        "agent": agent,
        "label": band_def["label"],
        "band_metadata": _enrich_population_line(band_def["metadata"]),
        "points": [],
    }
    if baseline_lbs is None or float(baseline_lbs) <= 0:
        return result
    if max_weeks is None or float(max_weeks) <= 0:
        return result

    table = band_def["points"]
    max_weeks = float(max_weeks)
    weeks = sorted(
        {0.0, max_weeks} | {float(w) for (w, _lo, _hi) in table if 0 < w < max_weeks}
    )
    baseline_lbs = float(baseline_lbs)
    for week in weeks:
        lower_pct, upper_pct = _interp_band_at_week(table, week)
        result["points"].append({
            "week": week,
            "date": baseline_date + timedelta(weeks=week) if baseline_date is not None else None,
            "lower_pct": lower_pct,
            "upper_pct": upper_pct,
            "lower_lbs": baseline_lbs * (1.0 - lower_pct / 100.0),
            "upper_lbs": baseline_lbs * (1.0 - upper_pct / 100.0),
        })
    return result


def _dp_week(dp) -> float:
    return float(dp.get("weeks_since_baseline"))


def _dp_tbwl(dp) -> float:
    return float(dp.get("tbwl_pct"))


def _tbwl_at_week(datapoints: list[dict], week: float) -> float:
    """Linear interpolation of tbwl_pct at `week`, clamped to the observed range."""
    pts = sorted(datapoints, key=_dp_week)
    if not pts:
        raise ValueError("Cannot interpolate TBWL with zero datapoints")
    if week <= _dp_week(pts[0]):
        return _dp_tbwl(pts[0])
    if week >= _dp_week(pts[-1]):
        return _dp_tbwl(pts[-1])
    for a, b in zip(pts, pts[1:]):
        wa, wb = _dp_week(a), _dp_week(b)
        if wa <= week <= wb:
            if wb == wa:
                return _dp_tbwl(b)
            f = (week - wa) / (wb - wa)
            return _dp_tbwl(a) + f * (_dp_tbwl(b) - _dp_tbwl(a))
    return _dp_tbwl(pts[-1])


def _qualifies_for_velocity(pts: list[dict]) -> bool:
    """≥2 observations spanning ≥14 days (the E3 data-quality rule)."""
    if len(pts) < 2:
        return False
    span_weeks = _dp_week(pts[-1]) - _dp_week(pts[0])
    return span_weeks * 7.0 >= VELOCITY_MIN_SPAN_DAYS


def compute_velocity(
    datapoints: list[dict],
    window_weeks: float = VELOCITY_WINDOW_WEEKS,
) -> float | None:
    """E3: rolling %TBWL/week over the trailing window. Positive = losing.

    TBWL at (last - window) is linearly interpolated between the bracketing
    observations, so irregular visit spacing is handled. Returns None when the
    series has <2 observations or spans <14 days.
    """
    pts = sorted(
        [dp for dp in datapoints if dp.get("weeks_since_baseline") is not None],
        key=_dp_week,
    )
    if not _qualifies_for_velocity(pts):
        return None
    end_week = _dp_week(pts[-1])
    start_week = max(end_week - float(window_weeks), _dp_week(pts[0]))
    if end_week <= start_week:
        return None
    return (_dp_tbwl(pts[-1]) - _tbwl_at_week(pts, start_week)) / (end_week - start_week)


def build_velocity_stats(velocity_pct_per_week: float | None) -> dict:
    """Template-facing velocity summary. Display sign: loss renders negative
    (internal TBWL is positive-for-loss), e.g. velocity +0.6 → '-0.60%/wk'.
    """
    if velocity_pct_per_week is None:
        display = "—"  # em dash
    else:
        display = f"{-float(velocity_pct_per_week):.2f}%/wk"
    return {
        "velocity_pct_per_week": velocity_pct_per_week,
        "display": display,
        "window_weeks": VELOCITY_WINDOW_WEEKS,
        "_component": "velocity_stats",
        "_loaded_at": _now_iso(),
    }


def build_headline(
    baseline_lbs: float,
    latest_lbs: float,
    latest_tbwl_pct: float,
    display_unit: str = DISPLAY_UNIT,
) -> dict:
    """Dual-metric headline (v0.2.5): %TBWL AND absolute change in the
    patient's display unit, e.g. "−8.5% TBWL (−18.7 lb from 220 lb baseline)".

    BOTH figures come from the patient's own baseline and latest weight in the
    normalized display unit — never from any trial figure. Loss renders
    negative in both metrics (matching the velocity sign convention).
    """
    baseline_disp = lbs_to_display(baseline_lbs, display_unit)
    latest_disp = lbs_to_display(latest_lbs, display_unit)
    abs_change = latest_disp - baseline_disp          # negative = weight lost
    pct_display = -float(latest_tbwl_pct)             # negative = weight lost
    return {
        "tbwl_pct": float(latest_tbwl_pct),
        "pct_display": f"{pct_display:+.1f}% TBWL",
        "abs_change": abs_change,
        "abs_change_display": f"{abs_change:+.1f} {display_unit}",
        "baseline_display": f"{baseline_disp:.0f} {display_unit}",
        "display_unit": display_unit,
        "text": (
            f"{pct_display:+.1f}% TBWL "
            f"({abs_change:+.1f} {display_unit} from {baseline_disp:.0f} {display_unit} baseline)"
        ),
        "_component": "headline",
        "_loaded_at": _now_iso(),
    }


def detect_flags(datapoints: list[dict], velocity_pct_per_week: float | None) -> list[dict]:
    """E3 flags: plateau, regain (A5), rapid loss. Informational only.

    Plateau vs regain over the trailing 8 weeks (evaluated only after week 8):
      |ΔTBWL| < 0.5            → plateau (truly flat)
      ΔTBWL ≤ -0.5             → regain (weight moving UP — not a plateau)
      ΔTBWL ≥ +0.5             → still losing, no flag
    The absolute-value plateau test is what keeps P5-style regain from being
    mislabeled as a plateau. Rapid loss: trailing 4-week velocity > 1.0%/wk;
    the rolling-average window is the "sustained" test.
    """
    pts = sorted(
        [dp for dp in datapoints if dp.get("weeks_since_baseline") is not None],
        key=_dp_week,
    )
    flags: list[dict] = []
    if not _qualifies_for_velocity(pts):
        return flags

    last_week = _dp_week(pts[-1])
    if last_week > PLATEAU_MIN_WEEK:
        window_start = max(last_week - PLATEAU_WINDOW_WEEKS, _dp_week(pts[0]))
        delta8 = _dp_tbwl(pts[-1]) - _tbwl_at_week(pts, window_start)
        if abs(delta8) < PLATEAU_ABS_DELTA_PCT:
            flags.append(dict(FLAG_DEFINITIONS["plateau"]))
        elif delta8 <= REGAIN_DELTA_PCT:
            flags.append(dict(FLAG_DEFINITIONS["regain"]))

    if velocity_pct_per_week is not None and velocity_pct_per_week > RAPID_VELOCITY_PCT_PER_WEEK:
        flags.append(dict(FLAG_DEFINITIONS["rapid_loss"]))
    return flags


def build_chart_data(
    observations_raw: list,
    notes_or_baseline=None,
    agent: str | None = DEFAULT_AGENT,
    baseline_override: dict | None = None,
    band_weeks_override: float | None = None,
) -> dict:
    """Orchestrate the Processing Layer and return the chart payload.

    Second argument is overloaded (locked Option B):
      - dict  → a pre-fetched {note_id: Note} map; dates are attached from it.
      - numeric / None → observations already carry their own dates (raw dicts
        with datetime_of_service, or SDK-like objects). The numeric value is the
        legacy `baseline` arg and is ignored — baseline is always recomputed from
        the earliest observation.

    `agent` selects the expected-response band table (v0.2 / A3); callers pass
    detect_glp1_agent()'s result so this function stays SDK-free.

    v0.5.0 manual-baseline additions — all defaults preserve legacy behavior
    byte-identically (regression-pinned by the four baseline suites):
      - baseline_override: {"date", "value_lbs", "source_id"} from the
        provider-entered baseline. Week-0 / %TBWL / band anchoring then derive
        from baseline_override["date"] (the CLINICAL baseline_date, Amendment
        1) — never from the entry timestamp. With an override, zero usable
        observations is a valid state (datapoints = []).
      - agent=None: render NO projection band (bands are trial-specific;
        provider said Other / not on GLP-1).
      - band_weeks_override: minimum band horizon in weeks (manual mode shows
        the band even before two observations exist).
    """
    if isinstance(notes_or_baseline, dict):
        observations_with_dates = attach_dates_to_observations(observations_raw, notes_or_baseline)
    else:
        observations_with_dates = list(observations_raw)

    observations_with_dates = dedupe_same_day(observations_with_dates)
    if baseline_override is not None:
        baseline = baseline_override
    else:
        baseline = _baseline_record(observations_with_dates)

    datapoints = [
        build_observation_processed(obs, baseline) for obs in observations_with_dates
    ]
    # Strip timezone for sorting — FHIR dates are tz-aware, UI dates may be naive.
    datapoints.sort(key=lambda dp: _strip_tz(dp["date_obj"]))

    latest_tbwl_pct = datapoints[-1]["tbwl_pct"] if datapoints else 0.0

    # v0.2 derived layers. Band only with ≥2 datapoints (a single observation
    # has zero observed span, so the band would just stretch the axes) —
    # unless manual mode supplies a band horizon explicitly.
    if band_weeks_override is not None:
        last_week = band_weeks_override
        if datapoints:
            last_week = max(last_week, datapoints[-1]["weeks_since_baseline"])
    else:
        last_week = datapoints[-1]["weeks_since_baseline"] if len(datapoints) >= 2 else 0.0
    if agent is None:
        expected_band = {
            "agent": "none",
            "label": "No projection — not on GLP-1 therapy",
            "band_metadata": {},
            "points": [],
        }
    else:
        expected_band = build_expected_band(
            baseline["value_lbs"], baseline["date"], last_week, agent
        )
    axis_weights = _collect_axis_weights(datapoints, baseline["value_lbs"], expected_band)
    milestones = compute_milestone_lines(baseline["value_lbs"], axis_weights, latest_tbwl_pct)
    velocity = compute_velocity(datapoints)
    velocity_stats = build_velocity_stats(velocity)
    flags = detect_flags(datapoints, velocity)

    now = _now_iso()
    return {
        "baseline_data": {
            "value": baseline["value_lbs"],
            "value_lbs": baseline["value_lbs"],
            "unit": "lbs",
            "source_observation_id": baseline["source_id"],
            "_component": "baseline_layer",
            "_loaded_at": now,
        },
        "datapoints": datapoints,
        "latest_tbwl_pct": latest_tbwl_pct,
        "milestones": milestones,
        "expected_band": expected_band,
        "velocity_stats": velocity_stats,
        "flags": flags,
        "_pipeline_timestamps": {
            "demographics_loaded": now,
            "observations_loaded": now,
            "observations_raw_loaded": now,
            "notes_batch_loaded": now,
            "processing_complete": now,
        },
    }


# ─────────────────────────────────────────────────────────────
# SECTION 3: Validation Layer
# ─────────────────────────────────────────────────────────────


def validate_chart_payload(
    payload: dict, allow_empty_datapoints: bool = False
) -> tuple[bool, list[str]]:
    """Run BEFORE any LaunchModalEffect. Returns (is_valid, [error messages]).

    allow_empty_datapoints (v0.5.0): manual-baseline mode renders a valid
    chart from the provider-entered baseline before any follow-up weight
    exists. Default False keeps every legacy call site byte-identical.
    """
    errors: list[str] = []

    # 1. baseline present and positive
    baseline_data = payload.get("baseline_data")
    if not baseline_data or float(baseline_data.get("value", 0) or 0) <= 0:
        errors.append("Missing or non-positive baseline value")

    # 2. datapoints non-empty (unless manual mode explicitly allows empty)
    datapoints = payload.get("datapoints")
    if not datapoints:
        if not allow_empty_datapoints:
            errors.append("No datapoints to render")
        datapoints = []

    # 3. no future observation dates
    # Use timezone-aware now so we can compare with both aware and naive date_obj values.
    # FHIR-created observations carry tzinfo (+00:00); UI-created ones may be naive.
    now_naive = datetime.now()

    def _is_future(dt) -> bool:
        """Return True if dt is in the future, handling tz-aware and naive datetimes."""
        if dt is None:
            return False
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt.replace(tzinfo=None) > now_naive   # strip tz, compare in local time
        return dt > now_naive

    if any(_is_future(dp.get("date_obj")) for dp in datapoints):
        errors.append("Observation date is in the future")

    # 4. latest TBWL in plausible [-20, 50] range
    latest = payload.get("latest_tbwl_pct")
    if latest is not None and not (-20.0 <= float(latest) <= 50.0):
        errors.append("latest TBWL percentage out of plausible range")

    # 5. no zero/negative weights
    if any(float(dp.get("value_lbs", 0)) <= 0 for dp in datapoints):
        errors.append("Zero or negative weight value present")

    # 6. datapoints sorted ascending by date
    dates = [_strip_tz(dp.get("date_obj")) for dp in datapoints
             if dp.get("date_obj") is not None]
    if dates != sorted(dates):
        errors.append("Datapoints not sorted ascending by date / wrong order")

    # 7. pipeline timestamps present
    if "_pipeline_timestamps" not in payload:
        errors.append("Missing _pipeline_timestamps")

    # 8. all required template keys present
    for key in REQUIRED_TEMPLATE_KEYS:
        if key not in payload:
            errors.append(f"Missing required template key: {key}")

    # 9. v0.2 keys — shape-checked only when present, so legacy payloads
    # (pre-0.2 callers and the byte-untouched v0.1 tests) remain valid.
    # build_chart_data always emits them; tests assert that separately.
    if "milestones" in payload and not isinstance(payload.get("milestones"), list):
        errors.append("milestones must be a list")
    if "flags" in payload and not isinstance(payload.get("flags"), list):
        errors.append("flags must be a list")
    if "expected_band" in payload:
        band = payload.get("expected_band")
        if not isinstance(band, dict) or "points" not in band or "label" not in band:
            errors.append("expected_band malformed (needs label + points)")
    if "velocity_stats" in payload:
        stats = payload.get("velocity_stats")
        if not isinstance(stats, dict) or "display" not in stats:
            errors.append("velocity_stats malformed (needs display)")

    return (len(errors) == 0, errors)


# ─────────────────────────────────────────────────────────────
# SECTION 4: Render Layer (template context assembly)
# ─────────────────────────────────────────────────────────────

EM_DASH = "—"

# Footer order for the export citations — all three trial citations ship on
# every export regardless of the matched agent (v0.3.0). Strings are read from
# EXPECTED_RESPONSE_BANDS, never retyped.
_CITATION_AGENT_ORDER = ("semaglutide_step1", "tirzepatide_surmount1", "liraglutide_scale")


def export_citations() -> list[str]:
    """The three shipped trial citation strings, in fixed footer order."""
    return [
        EXPECTED_RESPONSE_BANDS[agent]["metadata"]["citation"]
        for agent in _CITATION_AGENT_ORDER
    ]


def build_milestone_status(datapoints: list[dict]) -> list[dict]:
    """Export stats block: reached yes/no + date for EVERY milestone pct.

    Independent of compute_milestone_lines (whose axis-domain suppression is a
    chart-rendering concern only). Reached date = date_label of the FIRST
    datapoint whose already-computed tbwl_pct meets the threshold — a mapping
    over the existing payload, no interpolation, no recomputation.
    """
    status: list[dict] = []
    for pct in MILESTONE_PCTS:
        reached_dp = next(
            (dp for dp in datapoints if float(dp.get("tbwl_pct", 0.0)) >= pct), None
        )
        status.append({
            "pct": pct,
            "reached": reached_dp is not None,
            "date_label": reached_dp["date_label"] if reached_dp else EM_DASH,
        })
    return status


def build_export_summary(
    patient: dict,
    baseline: dict,
    datapoints: list[dict],
    latest_tbwl_pct: float,
    expected_band: dict,
    velocity_stats: dict,
    flags: list[dict],
    display_unit: str = DISPLAY_UNIT,
    baseline_date_label_override: str | None = None,
) -> dict:
    """v0.3.0 print-export stats block, assembled ONLY from the already-computed
    payload (constraint 5: no second data path). Missing values render as
    em-dashes, never blanks. All clinical strings (band label, disclosure,
    citations) are referenced from EXPECTED_RESPONSE_BANDS verbatim.

    baseline_date_label_override (v0.5.0): manual mode anchors the baseline
    to the provider-entered clinical date, not the first observation's date.
    Default None keeps legacy output byte-identical.
    """
    name_parts = [patient.get("first_name"), patient.get("last_name")]
    patient_name = " ".join(p for p in name_parts if p) or EM_DASH
    birth_date = patient.get("birth_date")
    patient_dob = f"{birth_date}" if birth_date else EM_DASH

    baseline_lbs = baseline.get("value_lbs") or baseline.get("value")
    if datapoints and baseline_lbs:
        baseline_display = (
            f"{lbs_to_display(baseline_lbs, display_unit):.1f} {display_unit}"
        )
        baseline_date_label = baseline_date_label_override or datapoints[0]["date_label"]
        latest = datapoints[-1]
        latest_display = (
            f"{lbs_to_display(latest['value_lbs'], display_unit):.1f} {display_unit}"
        )
        latest_date_label = latest["date_label"]
        total_tbwl_display = f"{-float(latest_tbwl_pct):+.1f}% TBWL"
    else:
        baseline_display = EM_DASH
        baseline_date_label = EM_DASH
        latest_display = EM_DASH
        latest_date_label = EM_DASH
        total_tbwl_display = EM_DASH

    # Same legend-label rule as assemble_template_context: the band-basis
    # qualifier (SCALE: "±1 SD") is part of the label wherever it appears.
    band_label = expected_band.get("label") or EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["label"]
    band_metadata = expected_band.get("band_metadata") or {}
    qualifier = band_metadata.get("legend_qualifier")
    band_display = f"{band_label}, {qualifier}" if qualifier else band_label
    estimated_bounds = bool(band_metadata.get("estimated_bounds"))

    return {
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "plugin_version": PLUGIN_VERSION,
        "baseline_display": baseline_display,
        "baseline_date_label": baseline_date_label,
        "latest_display": latest_display,
        "latest_date_label": latest_date_label,
        "total_tbwl_display": total_tbwl_display,
        "milestone_status": build_milestone_status(datapoints),
        "velocity_display": velocity_stats.get("display", EM_DASH),
        "velocity_window_weeks": velocity_stats.get("window_weeks", VELOCITY_WINDOW_WEEKS),
        "flags": [
            {"label": f.get("label"), "severity": f.get("severity")} for f in flags
        ],
        "agent": expected_band.get("agent", DEFAULT_AGENT),
        "band_display": band_display,
        # The uncertainty disclosure must survive into the export VERBATIM
        # whenever the band carries estimated bounds (clinical-integrity rule).
        "estimated_bounds": estimated_bounds,
        "band_disclosure": band_metadata.get("disclosure") if estimated_bounds else None,
        "citations": export_citations(),
        "_component": "export_summary",
        "_loaded_at": _now_iso(),
    }


# ── v0.4.0 support-report export + weight-data table ──

# Support-report schema version. Future transports (email/direct-to-support)
# are explicitly out of scope for 0.4.0; bump this only when the payload
# shape changes.
LOG_EXPORT_SCHEMA_VERSION = "1"

# Universal value for the weight-data table's source/method column. Gate 2
# (v0.4.0): verified against canvas_sdk/v1/data/observation.py on disk AND
# docs.canvasmedical.com/sdk/data-observation that the SDK 0.163.1 Observation
# model exposes NO method or device field, so the column cannot be populated
# without heuristic inference — which is forbidden.
SOURCE_METHOD_NOT_RECORDED = "Not recorded"

# Origin taxonomy mirrors the debug-capture console-mode classification:
# entries the plugin itself recorded are "plugin"; entries attributed to the
# host EHR page are "host"; anything unattributable is "unknown".
LOG_ORIGINS = ("plugin", "host", "unknown")

_PLUGIN_EVENT_PREFIXES = ("python.", "js.")
_PLUGIN_COMPONENT_NAMES = frozenset({
    "StatsBar",
    "ChartScaffold",
    "ExpectedBandLayer",
    "BaselineLayer",
    "MilestoneLayer",
    "DataPointLayer",
    "AnnotationLayer",
    "TooltipManager",
    "ExportView",
    "DiagnosticsPanel",
})


def classify_log_origin(name) -> str:
    """Classify an event-log entry name into the debug-capture origin taxonomy.

    `python.*` / `js.*` events and the plugin's own component lifecycle events
    are plugin-attributable; `host.*` is reserved for entries attributed to
    the surrounding EHR page; everything else is "unknown" — never guessed
    into "plugin".
    """
    if not isinstance(name, str) or not name:
        return "unknown"
    if name.startswith(_PLUGIN_EVENT_PREFIXES):
        return "plugin"
    if name.split(".", 1)[0] in _PLUGIN_COMPONENT_NAMES:
        return "plugin"
    if name.startswith("host."):
        return "host"
    return "unknown"


def build_log_export(
    entries,
    *,
    launch_target: str,
    patient_fhir_id,
    plugin_version: str = PLUGIN_VERSION,
    generated_at=None,
    user_agent=None,
) -> dict:
    """Pure mapping: event-log entries + metadata in, schema-valid payload out
    (same pattern as build_export_summary — no second data path, fully
    unit-testable without a browser).

    Schema knowledge lives HERE only. The JS side fills exactly three
    browser-only values at download time — generated_at, user_agent, and its
    own runtime entry appends — and serializes; it constructs no schema keys.

    patient_fhir_id is the ID ONLY — never name, DOB, or any other
    demographic. The v0.4 tests scan the payload recursively for demographic
    keys to keep it that way.
    """
    norm_entries = []
    for entry in entries or []:
        name = str(entry.get("name") or "")
        origin = entry.get("origin")
        if origin not in LOG_ORIGINS:
            origin = classify_log_origin(name)
        norm_entries.append({
            "name": name,
            "timestamp_utc": str(entry.get("timestamp_utc") or ""),
            "origin": origin,
        })
    return {
        "schema_version": LOG_EXPORT_SCHEMA_VERSION,
        "plugin_version": plugin_version,
        "generated_at": generated_at,  # browser-only fill at download time
        "launch_target": launch_target,
        "patient_fhir_id": patient_fhir_id,
        "user_agent": user_agent,  # browser-only fill at download time
        "entries": norm_entries,
    }


def _capture_iso(date_obj) -> str:
    """ISO-8601 string for a table row's capture datetime.

    Aware datetimes (FHIR-created observations) are normalized to UTC with a
    Z suffix; naive ones (UI-created) are emitted as recorded — converting
    them would mean guessing an offset, which the timestamp-normalization
    rule forbids.
    """
    if date_obj is None:
        return ""
    if getattr(date_obj, "tzinfo", None) is not None:
        return date_obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return date_obj.isoformat()


def build_table_rows(datapoints: list[dict], baseline: dict) -> list[dict]:
    """v0.4.0 read-only weight-data table rows, derived ONLY from the
    already-computed datapoints the chart consumed (no second data path —
    no FHIR/SDK queries at render time).

    Display strings follow the shipped conventions: positive TBWL = weight
    lost = "↓X.X%" (the v0.2.5 headline convention); Δ is signed pounds vs.
    baseline. source/method is SOURCE_METHOD_NOT_RECORDED universally per the
    Gate 2 verdict (see that constant) — never inferred.
    """
    baseline_lbs = float(baseline.get("value_lbs") or baseline.get("value") or 0.0)
    rows: list[dict] = []
    for dp in datapoints or []:
        value_lbs = float(dp.get("value_lbs") or 0.0)
        tbwl_pct = float(dp.get("tbwl_pct") or 0.0)
        arrow = "↓" if tbwl_pct >= 0 else "↑"
        rows.append({
            "capture_iso": _capture_iso(dp.get("date_obj")),
            "weight_display": f"{value_lbs:.1f} lb",
            "delta_display": f"{value_lbs - baseline_lbs:+.1f} lb",
            "tbwl_display": f"{arrow}{abs(tbwl_pct):.1f}%",
            "source_method": SOURCE_METHOD_NOT_RECORDED,
        })
    return rows


# ── v0.5.0 manual-baseline pure functions ──


def parse_manual_baseline(value) -> dict | None:
    """Parse a stored manual-baseline metadata value. Fail-closed: anything
    other than a well-formed schema-2 record (unknown schema versions
    included) returns None and the patient is treated as having no
    provider-entered baseline."""
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != MANUAL_BASELINE_SCHEMA_VERSION:
        return None
    if data.get("agent") not in MANUAL_AGENT_OPTIONS:
        return None
    try:
        weight_lb = float(data.get("weight_lb"))
        baseline_date = datetime.fromisoformat(str(data.get("baseline_date")))
    except (TypeError, ValueError):
        return None
    if weight_lb <= 0:
        return None
    return {
        "weight_lb": weight_lb,
        "baseline_date": baseline_date,
        "agent": data.get("agent"),
        "set_by_staff_id": data.get("set_by_staff_id"),
        "set_at_utc": data.get("set_at_utc"),
        "note_id": data.get("note_id"),
        "revision": int(data.get("revision") or 0),
        "superseded_note_id": data.get("superseded_note_id"),
    }


def resolve_render_mode(manual_baseline: dict | None, obs_raw: list) -> str:
    """Decision 3C render gate: "manual" | "legacy" | "empty".

    A provider-entered baseline always wins. Otherwise, patients whose
    earliest weight observation RECORD predates MANUAL_BASELINE_CUTOVER keep
    the legacy visit-1-baseline rendering byte-identically; everyone else
    (no observations, or all records created post-cutover) gets the empty
    state until a provider enters the baseline.
    """
    if manual_baseline:
        return "manual"
    created_times = [
        _strip_tz(obs.get("created"))
        for obs in obs_raw or []
        if isinstance(obs, dict) and obs.get("created") is not None
    ]
    if created_times and min(created_times) < _strip_tz(MANUAL_BASELINE_CUTOVER):
        return "legacy"
    return "empty"


def build_discrepancy_notice(detected_agent_key: str | None, selected: str) -> str | None:
    """Decision 5: non-blocking notice when the active medication list
    contradicts the provider's dropdown selection. None = no contradiction
    evidence (no/ambiguous active GLP-1, or agreement)."""
    if detected_agent_key is None or selected not in MANUAL_AGENT_OPTIONS:
        return None
    if MANUAL_AGENT_OPTIONS[selected] == detected_agent_key:
        return None
    detected_name = detected_agent_key.split("_", 1)[0].capitalize()
    if MANUAL_AGENT_OPTIONS[selected] is None:
        return (
            f"Active medication list shows {detected_name} — no projection "
            f"shown for provider-selected {MANUAL_AGENT_LABELS['other']}."
        )
    return (
        f"Active medication list shows {detected_name} — projection shown "
        f"for provider-selected {MANUAL_AGENT_LABELS[selected]}."
    )


def build_correction_header(
    *, old_weight_lb: float, old_date_label: str, new_weight_lb: float,
    new_date_label: str, staff_display: str, timestamp: str, reason: str,
) -> str:
    """Amendment 3 correction header — exact template, pinned verbatim."""
    return CORRECTION_HEADER_TEMPLATE.format(
        old_weight=f"{old_weight_lb:.1f}",
        old_date=old_date_label,
        new_weight=f"{new_weight_lb:.1f}",
        new_date=new_date_label,
        staff=staff_display,
        timestamp=timestamp,
        reason=reason,
    )


def build_note_narrative(
    *, weight_lb: float, baseline_date_label: str, agent_label: str,
    provider_text: str, minutes: int | None, correction_header: str | None = None,
) -> str:
    """Amendment 2 billing-supportive narrative. The time line is populated
    only from the provider-entered minutes field — never fabricated; the
    blank stays blank when minutes were not entered."""
    lines: list[str] = []
    if correction_header:
        lines.append(correction_header)
        lines.append("")
    lines.append("Weight-management counseling — provider-confirmed baseline.")
    lines.append(f"Baseline weight: {weight_lb:.1f} lb (as of {baseline_date_label}).")
    lines.append(f"Medication: {agent_label}.")
    lines.append(f"Counseling: {provider_text}")
    lines.append(
        f"Time spent: {minutes} minutes" if minutes else "Time spent: ___ minutes"
    )
    return "\n".join(lines)


def build_manual_baseline_value(
    *, weight_lb: float, baseline_date_iso: str, agent: str, staff_id,
    note_id, revision: int, superseded_note_id=None,
) -> str:
    """Serialize the schema-2 metadata value. baseline_date is the CLINICAL
    anchor; set_at_utc is the entry timestamp — distinct, never conflated."""
    return json.dumps({
        "schema": MANUAL_BASELINE_SCHEMA_VERSION,
        "weight_lb": weight_lb,
        "baseline_date": baseline_date_iso,
        "agent": agent,
        "set_by_staff_id": staff_id,
        "set_at_utc": _now_iso(),
        "note_id": note_id,
        "revision": revision,
        "superseded_note_id": superseded_note_id,
    })


def validate_baseline_form(form: dict, *, is_correction: bool) -> tuple[list[str], bool]:
    """Validate the manual-baseline dialog POST. Returns (errors,
    needs_bounds_confirm).

    Hard rejects: non-numeric/non-positive weight, bad/future/ancient
    baseline date, unknown agent, empty note text, bad minutes, missing
    correction reason. Soft (Amendment 4): weight outside
    ADULT_WEIGHT_PLAUSIBILITY_LB needs confirm-to-override — this is the ONLY
    code path wired to that constant (scope guard)."""
    errors: list[str] = []
    needs_confirm = False

    try:
        weight_lb = float(form.get("weight_lb"))
    except (TypeError, ValueError):
        weight_lb = 0.0
    if weight_lb <= 0:
        errors.append("Baseline weight must be a positive number (lb)")
    else:
        low, high = ADULT_WEIGHT_PLAUSIBILITY_LB
        if not (low <= weight_lb <= high) and not form.get("confirm_bounds"):
            needs_confirm = True

    baseline_date_raw = str(form.get("baseline_date") or "")
    try:
        baseline_date = datetime.fromisoformat(baseline_date_raw)
    except ValueError:
        baseline_date = None
    if baseline_date is None:
        errors.append("Baseline date is required (YYYY-MM-DD)")
    elif _strip_tz(baseline_date).date() > date.today():
        errors.append("Baseline date cannot be in the future")
    elif baseline_date.year < 1900:
        errors.append("Baseline date is implausibly old")

    if form.get("agent") not in MANUAL_AGENT_OPTIONS:
        errors.append("Select which medication the patient is starting")

    note_text = str(form.get("note_text") or "").strip()
    if not note_text:
        errors.append("An accompanying note is required")
    elif len(note_text) > 10000:
        errors.append("Note text is too long (10,000 character limit)")

    minutes_raw = form.get("minutes")
    if minutes_raw not in (None, ""):
        try:
            minutes = int(minutes_raw)
        except (TypeError, ValueError):
            minutes = -1
        if not (1 <= minutes <= 600):
            errors.append("Time spent must be a whole number of minutes (1–600)")

    if is_correction and not str(form.get("reason") or "").strip():
        errors.append("A reason is required when revising an existing baseline")

    return errors, needs_confirm


def assemble_template_context(
    patient: dict,
    baseline: dict,
    datapoints: list[dict],
    pipeline_timestamps: dict,
    milestones: list[dict] | None = None,
    expected_band: dict | None = None,
    velocity_stats: dict | None = None,
    flags: list[dict] | None = None,
    mode: str = "legacy",
    manual_baseline: dict | None = None,
    discrepancy_notice: str | None = None,
) -> dict:
    """Assemble the final context for render_to_string().

    Each top-level component dict carries `_component` and `_loaded_at`.
    The v0.2 arguments are keyword-optional so v0.1 call sites (and the
    byte-untouched v0.1 tests) keep working; defaults are valid empty states.
    v0.5.0 adds mode / manual_baseline / discrepancy_notice the same way —
    defaults keep every legacy call site byte-identical.
    """
    now = _now_iso()

    if milestones is None:
        milestones = []
    if expected_band is None:
        expected_band = {
            "agent": DEFAULT_AGENT,
            "label": EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["label"],
            "band_metadata": _enrich_population_line(EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["metadata"]),
            "points": [],
        }
    if velocity_stats is None:
        velocity_stats = build_velocity_stats(None)
    if flags is None:
        flags = []

    baseline_lbs_val = float(baseline.get("value_lbs") or baseline.get("value") or 0.0)
    if datapoints:
        latest = datapoints[-1]
        latest_annotation = {
            "tbwl_pct": latest["tbwl_pct"],
            "weight_lbs": latest["value_lbs"],
            "date_label": latest["date_label"],
            "_component": "annotation_layer",
            "_loaded_at": now,
        }
        latest_tbwl_pct = latest["tbwl_pct"]
        headline = build_headline(baseline_lbs_val, latest["value_lbs"], latest["tbwl_pct"], DISPLAY_UNIT)
    else:
        latest_annotation = {
            "tbwl_pct": 0.0,
            "weight_lbs": 0.0,
            "date_label": "",
            "_component": "annotation_layer",
            "_loaded_at": now,
        }
        latest_tbwl_pct = 0.0
        headline = None

    timestamps = dict(pipeline_timestamps)
    timestamps.setdefault("demographics_loaded", now)
    timestamps.setdefault("observations_raw_loaded", now)
    timestamps.setdefault("notes_batch_loaded", now)
    timestamps.setdefault("processing_complete", now)
    timestamps["validation_passed"] = now
    timestamps["template_context_assembled"] = now

    band_label = expected_band.get("label") or EXPECTED_RESPONSE_BANDS[DEFAULT_AGENT]["label"]
    band_metadata = expected_band.get("band_metadata") or {}
    # Band-basis qualifier shown in the legend itself (v0.2.4: SCALE reads
    # "±1 SD"; trial-percentile bands carry no qualifier).
    qualifier = band_metadata.get("legend_qualifier")
    legend_label = f"{band_label}, {qualifier}" if qualifier else band_label
    return {
        "patient": {**patient, "_component": "patient_info", "_loaded_at": now},
        "baseline_data": {**baseline, "_component": "baseline_layer", "_loaded_at": now},
        "datapoints": datapoints,
        "latest_annotation": latest_annotation,
        "latest_tbwl_pct": latest_tbwl_pct,
        "headline": headline,
        "milestones": milestones,
        "expected_band": {**expected_band, "_component": "expected_band_layer", "_loaded_at": now},
        "velocity_stats": velocity_stats,
        "flags": flags,
        # v0.5.0 manual-baseline surface (defaults: legacy mode, no notice).
        "mode": mode,
        "manual_baseline": manual_baseline,
        "discrepancy_notice": discrepancy_notice,
        "export_summary": build_export_summary(
            patient=patient,
            baseline=baseline,
            datapoints=datapoints,
            latest_tbwl_pct=latest_tbwl_pct,
            expected_band=expected_band,
            velocity_stats=velocity_stats,
            flags=flags,
            display_unit=DISPLAY_UNIT,
            baseline_date_label_override=(
                (manual_baseline or {}).get("baseline_date_label") if mode == "manual" else None
            ),
        ),
        # v0.4.0 support-report scaffold: schema + Python pipeline entries,
        # pre-classified. The browser fills generated_at/user_agent and
        # appends its runtime entries at download time — nothing else.
        "log_export_base": build_log_export(
            [
                {"name": f"python.{key}", "timestamp_utc": value}
                for key, value in timestamps.items()
            ],
            launch_target=LAUNCH_TARGET.value,
            patient_fhir_id=patient.get("patient_id"),
        ),
        # v0.4.0 weight-data table (read-only view inside the event-log panel).
        "table_rows": build_table_rows(datapoints, baseline),
        "chart_config": {
            "x_axis_type": "calendar_date",
            "y_axis_unit": "lbs",
            "display_unit": DISPLAY_UNIT,
            "show_benchmark_overlay": bool(expected_band.get("points")),
            "benchmark_source": band_label,
            "legend_text": f"Expected response ({legend_label})",
            # Axis padding rule — JS must use these, not hardcoded values, so
            # the rendered domain can't drift from _axis_domain's suppression.
            "axis_pad_fraction": AXIS_PAD_FRACTION,
            "axis_pad_min_lbs": AXIS_PAD_MIN_LBS,
        },
        "_pipeline_timestamps": timestamps,
    }


# ─────────────────────────────────────────────────────────────
# SECTION 5: ActionButton Handler
# ─────────────────────────────────────────────────────────────


class GenerateVitalsGraphs(ActionButton):
    """Thin orchestration layer. Business logic lives in Sections 1-4."""

    BUTTON_TITLE = "Weight Trajectory"
    BUTTON_KEY = "show_cardiometabolic_tracker"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_VITALS_SECTION

    def _patient_id(self) -> str:
        """Resolve the patient id from the action-button event target."""
        event = getattr(self, "event", None)
        target = getattr(event, "target", None)
        target_id = getattr(target, "id", None)
        if target_id:
            return target_id
        context = getattr(self, "context", {}) or {}
        patient = context.get("patient")
        return patient.get("id") if isinstance(patient, dict) else context.get("patient_id")

    def compute(self) -> list[Effect]:
        """Dispatch (Option B).

        For SHOW_*_BUTTON events, defer to the base class so the button renders
        and clicks route normally. Otherwise (button click, or a direct test
        invocation) run the pipeline via handle(). The regex match is guarded so a
        mocked event in tests falls through to handle().
        """
        try:
            is_show_event = SHOW_BUTTON_REGEX.fullmatch(self.event.name) is not None
        except (AttributeError, TypeError):
            is_show_event = False

        if is_show_event:
            return super().compute()
        return self.handle()

    def handle(self) -> list[Effect]:
        # 1. Load + render-gate (v0.5.0 decision 3C)
        patient_id = self._patient_id()
        patient = load_patient_demographics(patient_id)
        manual = load_manual_baseline(patient_id)
        obs_raw = load_weight_observations_raw(patient_id)
        mode = resolve_render_mode(manual, obs_raw)

        if mode == "empty":
            return self._render_empty_state(patient_id)

        note_ids = [o["canvas_note_id"] for o in obs_raw if o.get("canvas_note_id")]
        notes = batch_load_notes(note_ids)

        manual_display = None
        discrepancy = None
        if mode == "manual":
            # Band from the provider's dropdown selection (decision 5);
            # week-0 / %TBWL anchor to the CLINICAL baseline_date (Amendment 1).
            band_agent = MANUAL_AGENT_OPTIONS.get(manual["agent"])
            baseline_override = {
                "date": manual["baseline_date"],
                "value_lbs": manual["weight_lb"],
                "source_id": "provider-entered",
            }
            weeks_now = max(
                0.0,
                calculate_weeks_since_baseline(manual["baseline_date"], datetime.now()),
            )
            try:
                payload = build_chart_data(
                    obs_raw,
                    notes,
                    agent=band_agent,
                    baseline_override=baseline_override,
                    band_weeks_override=max(16.0, weeks_now),
                )
            except ValueError as exc:
                return self._render_error([str(exc)])

            discrepancy = build_discrepancy_notice(
                detect_glp1_agent_raw(patient_id), manual["agent"]
            )
            if discrepancy:
                payload["_pipeline_timestamps"]["agent_discrepancy_detected"] = _now_iso()
                log.info(
                    "Agent discrepancy for patient %s: %s", patient_id, discrepancy
                )
            manual_display = {
                "weight_lb": manual["weight_lb"],
                "baseline_date_label": manual["baseline_date"].date().isoformat(),
                "agent": manual["agent"],
                "agent_label": MANUAL_AGENT_LABELS.get(manual["agent"], manual["agent"]),
                "revision": manual["revision"],
            }
            is_valid, errors = validate_chart_payload(
                payload, allow_empty_datapoints=True
            )
        else:
            # Legacy mode — byte-identical to the pre-v0.5.0 flow.
            agent = detect_glp1_agent(patient_id)
            try:
                payload = build_chart_data(obs_raw, notes, agent=agent)
            except ValueError as exc:
                return self._render_error([str(exc)])
            is_valid, errors = validate_chart_payload(payload)

        # 3. Validate — BEFORE any LaunchModalEffect
        if not is_valid:
            return self._render_error(errors)

        # 4. Assemble context
        context = assemble_template_context(
            patient=patient,
            baseline=payload["baseline_data"],
            datapoints=payload["datapoints"],
            pipeline_timestamps=payload.get("_pipeline_timestamps", {}),
            milestones=payload.get("milestones"),
            expected_band=payload.get("expected_band"),
            velocity_stats=payload.get("velocity_stats"),
            flags=payload.get("flags"),
            mode=mode,
            manual_baseline=manual_display,
            discrepancy_notice=discrepancy,
        )

        # 5. Render — serialize the whole context for the template's JSON.parse().
        # The baseline dialog ships ONLY in manual mode (structural absence for
        # legacy patients — no Set-baseline button can exist in their document).
        dialog_html = BASELINE_DIALOG_HTML if mode == "manual" else ""
        chart_data_json = json.dumps(context, default=_json_default)
        rendered_html = render_to_string(
            "templates/chart.html",
            {"chart_data_json": chart_data_json, "baseline_dialog_html": dialog_html},
        )
        return [
            LaunchModalEffect(
                content=rendered_html,
                target=LAUNCH_TARGET,
                title="Weight Trajectory",
            ).apply()
        ]

    def _render_empty_state(self, patient_id: str) -> list[Effect]:
        """v0.5.0: no provider-confirmed baseline → a friendly empty state
        that asks for one. Structurally separate document (L2, assembled
        inline like the error doc — no chart, no export, no event-log panel
        ships to these patients; only the baseline dialog does)."""
        ctx_json = json.dumps(
            {"mode": "empty", "patient_id": patient_id, "current": None},
            default=_json_default,
        ).replace("</", "<\\/")
        empty_html = (
            "<div style=\"font-family: Lato, Arial, sans-serif; padding: 24px;\">"
            "<h2 style=\"margin-top:0;\">Weight Trajectory</h2>"
            f"<p style=\"color:#44505c;\">{html.escape(EMPTY_STATE_MESSAGE)}</p>"
            "<span id=\"cm-baseline-btn-slot\"></span>"
            "</div>"
            f"<script>window.CM_BASELINE_CTX = {ctx_json};</script>"
            f"{BASELINE_DIALOG_HTML}"
        )
        return [
            LaunchModalEffect(
                content=empty_html,
                target=LAUNCH_TARGET,
                title="Weight Trajectory",
            ).apply()
        ]

    def _render_error(self, errors: list[str]) -> list[Effect]:
        """Validation failure → an error modal (locked Option B), never [] or a banner.

        Every interpolated value is html.escape()d (R2, v0.4.0): the
        ValueError path carries observation-entered content (e.g.
        "Unknown weight unit: {unit!r}" from convert_weight_to_lbs), and
        about:srcdoc inherits the EHR parent origin, so unescaped markup
        here would execute in the host context.
        """
        items = "".join(f"<li>{html.escape(str(e))}</li>" for e in errors)
        error_html = (
            "<div style=\"font-family: Lato, Arial, sans-serif; padding: 24px;\">"
            "<h2 style=\"margin-top:0;\">Unable to render weight trajectory</h2>"
            "<p>The chart could not be generated because the data did not pass validation:</p>"
            f"<ul>{items}</ul>"
            "</div>"
        )
        return [
            LaunchModalEffect(
                content=error_html,
                target=LAUNCH_TARGET,
                title="Weight Trajectory",
            ).apply()
        ]


# ─────────────────────────────────────────────────────────────
# SECTION 6: Manual-Baseline API (v0.5.0)
# ─────────────────────────────────────────────────────────────


class ManualBaselineAPI(StaffSessionAuthMixin, SimpleAPI):
    """POST /plugin-io/api/cardiometabolic_tracker/baseline

    Saves the provider-entered baseline (decision 1b): one PatientMetadata
    upsert (machine-readable source of truth: weight + clinical date +
    selected agent together) plus one visit note with a PlanCommand narrative
    (the clinical/insurance documentation), created in the same effect batch
    via a user-set note UUID (decision 2, verified docs pattern).

    Staff session auth only (StaffSessionAuthMixin); the staff id comes from
    the Canvas-set canvas-logged-in-user-id header — never client input.
    Fail-closed everywhere: validation errors, missing note type, or missing
    practice location return 4xx/5xx with ZERO partial effects.
    """

    @api.post("/baseline")
    def save_baseline(self) -> list:
        try:
            body = self.request.json()
        except (ValueError, TypeError):
            return [JSONResponse({"status": "error", "errors": ["Invalid JSON body"]}, status_code=400)]
        if not isinstance(body, dict):
            return [JSONResponse({"status": "error", "errors": ["Invalid JSON body"]}, status_code=400)]

        patient_id = str(body.get("patient_id") or "")
        if not patient_id or not Patient.objects.filter(id=patient_id).exists():
            return [JSONResponse({"status": "error", "errors": ["Unknown patient"]}, status_code=400)]

        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        if not staff_id:
            return [JSONResponse({"status": "error", "errors": ["No authenticated staff session"]}, status_code=401)]

        # Correction mode iff a parseable manual baseline already exists (A3).
        existing = load_manual_baseline(patient_id)
        is_correction = existing is not None

        errors, needs_confirm = validate_baseline_form(body, is_correction=is_correction)
        if errors:
            return [JSONResponse({"status": "error", "errors": errors}, status_code=400)]
        if needs_confirm:
            # Soft plausibility bounds (Amendment 4): confirm-to-override.
            return [JSONResponse(
                {"status": "confirm_required", "message": BOUNDS_CONFIRM_MESSAGE},
                status_code=200,
            )]

        weight_lb = float(body["weight_lb"])
        baseline_date = datetime.fromisoformat(str(body["baseline_date"]))
        baseline_date_label = baseline_date.date().isoformat()
        agent = str(body["agent"])
        minutes_raw = body.get("minutes")
        minutes = int(minutes_raw) if minutes_raw not in (None, "") else None
        provider_text = str(body.get("note_text") or "").strip()

        note_type, used_review_fallback = select_counseling_note_type()
        if note_type is None:
            return [JSONResponse(
                {"status": "error", "errors": ["No usable note type configured on this instance"]},
                status_code=500,
            )]
        practice_location = PracticeLocation.objects.order_by("dbid").first()
        if practice_location is None:
            return [JSONResponse(
                {"status": "error", "errors": ["No practice location configured on this instance"]},
                status_code=500,
            )]

        correction_header = None
        revision = 1
        superseded_note_id = None
        if is_correction:
            revision = int(existing["revision"]) + 1
            superseded_note_id = existing.get("note_id")
            correction_header = build_correction_header(
                old_weight_lb=existing["weight_lb"],
                old_date_label=existing["baseline_date"].date().isoformat(),
                new_weight_lb=weight_lb,
                new_date_label=baseline_date_label,
                staff_display=staff_display_name(staff_id),
                timestamp=_now_iso(),
                reason=str(body.get("reason") or "").strip(),
            )

        narrative = build_note_narrative(
            weight_lb=weight_lb,
            baseline_date_label=baseline_date_label,
            agent_label=MANUAL_AGENT_LABELS[agent],
            provider_text=provider_text,
            minutes=minutes,
            correction_header=correction_header,
        )

        # Note + command chained via a user-set UUID (decision 2).
        note_uuid = uuid4()
        note_effect = NoteEffect(
            instance_id=note_uuid,
            note_type_id=str(note_type.id),
            datetime_of_service=datetime.now(timezone.utc),
            patient_id=patient_id,
            practice_location_id=str(practice_location.id),
            provider_id=str(staff_id),
            title=MANUAL_NOTE_TITLE,
        )
        plan_command = PlanCommand(note_uuid=str(note_uuid), narrative=narrative)
        metadata_effect = PatientMetadataEffect(
            patient_id=patient_id, key=MANUAL_BASELINE_METADATA_KEY
        )
        metadata_value = build_manual_baseline_value(
            weight_lb=weight_lb,
            baseline_date_iso=baseline_date_label,
            agent=agent,
            staff_id=staff_id,
            note_id=str(note_uuid),
            revision=revision,
            superseded_note_id=superseded_note_id,
        )

        now = _now_iso()
        events = [
            {"name": "python.baseline_saved", "timestamp_utc": now},
            {"name": "python.medication_selected", "timestamp_utc": now},
            {"name": "python.note_created", "timestamp_utc": now},
        ]
        low, high = ADULT_WEIGHT_PLAUSIBILITY_LB
        if body.get("confirm_bounds") and not (low <= weight_lb <= high):
            events.append({"name": "python.baseline_bounds_override", "timestamp_utc": now})
            log.warning(
                "Baseline bounds override confirmed for patient %s: %.1f lb",
                patient_id, weight_lb,
            )

        cpt_reminder = {
            "heading": CPT_REMINDER_HEADING,
            "body": (
                f"{CPT_REMINDER_BODY} {CPT_REMINDER_REVIEW_ADDENDUM}"
                if used_review_fallback else CPT_REMINDER_BODY
            ),
        }
        response = JSONResponse({
            "status": "saved",
            "revision": revision,
            "note_id": str(note_uuid),
            "is_correction": is_correction,
            "used_review_fallback": used_review_fallback,
            "cpt_reminder": cpt_reminder,
            "events": events,
        })
        return [
            note_effect.create(),
            plan_command.originate(),
            metadata_effect.upsert(metadata_value),
            response,
        ]
