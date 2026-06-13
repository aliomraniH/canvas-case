#!/usr/bin/env python3
"""
Seed the two v0.5.0 manual-baseline test patients (P10, P11) — ADDITIVE ONLY.

P10 — pure empty state: zero weight observations, no MedicationStatement.
      (Provider will enter the baseline and select Tirzepatide in the dialog.)
P11 — gated follow-ups: four backdated follow-up weights (records created
      NOW, i.e. after MANUAL_BASELINE_CUTOVER, so the render gate hides the
      chart until a provider baseline exists) + an ACTIVE semaglutide
      MedicationStatement (the agreement path: dropdown Semaglutide → band,
      no discrepancy notice).

HARD RULES (inherited verbatim from seed_zztest_patients.py):
  * Writes to this sandbox are PERMANENT.
  * NEVER writes to an existing patient. Every Observation /
    MedicationStatement / rename PUT passes the pre-write guard: the target
    id must have been returned by a Patient create call IN THIS RUN and read
    back with the ZZTEST-GLP1 family name. Any guard failure aborts the run.
  * P1–P9 and every other patient are untouched; the manifest is MERGED,
    never overwritten.

Phase 2 (same run, rename_and_annotate pattern): realistic display names +
one scenario chart note, guarded by read-back (ZZTEST-GLP1 or already-new
name only).

Usage:
  python3 tools/seed_v05_patients.py --dry-run
  python3 tools/seed_v05_patients.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone

import _canvas_api
from _canvas_api import abort as _abort

MANIFEST_PATH = _canvas_api.EXTENSIONS_DIR / ".workspace_state" / "debug" / "seeded_patients.json"
ABORT_EPILOGUE = "No further writes will be attempted in this run."

RUN_TAG = datetime.now(timezone.utc).strftime("R%Y%m%d%H%M")
NAME_PREFIX = "ZZTEST-GLP1"

# Records must be CREATED after the render-gate cutover or P11 would be
# grandfathered into legacy mode (the gate uses record-creation time, not
# the backdated service dates).
MANUAL_BASELINE_CUTOVER = datetime(2026, 6, 12, 18, 0, 0, tzinfo=timezone.utc)

PATIENTS = {
    "P10": {
        "given": "Emptystate",
        "gender": "female",
        "weights": [],          # zero observations — pure empty state
        "day_offsets": [],
        "rename": ("Noor", "Haddad"),
        "note_title": ("GLP-1 weight mgmt — v0.5 manual-baseline demo: no weight data; "
                       "provider enters baseline + selects Tirzepatide in the dialog"),
    },
    "P11": {
        "given": "Gated",
        "gender": "male",
        # Follow-ups only — therapy started ~9 weeks ago, baseline never
        # recorded. Provider will backdate the baseline (Amendment 1).
        "weights": [238.0, 233.5, 229.8, 226.9],
        "day_offsets": [0, 14, 28, 42],
        "medication_search": "wegovy",
        "medication_fallback": {"code": "2553501",
                                "display": "Wegovy 2.4 MG/0.75 ML Pen Injector"},
        "rename": ("Marcus", "Bell"),
        "note_title": ("GLP-1 weight mgmt — v0.5 manual-baseline demo: follow-up weights "
                       "without a recorded baseline; chart gated until provider backdates "
                       "the baseline (semaglutide active — agreement path)"),
    },
}

# Same live-verified keys the rename tool used (2026-06-10):
PROVIDER_KEY = "e766816672f34a5b866771c773e38f3c"
PRACTICE_LOCATION_KEY = "d1eacdb5-9ead-47ce-855a-c8c6ef3932a6"
NOTE_TYPE_NAME = "Office visit"


def abort(message: str) -> None:
    _canvas_api.abort(message, ABORT_EPILOGUE)


class CanvasFHIR:
    """Guarded FHIR write session (pattern copied from seed_zztest_patients)."""

    def __init__(self, env: dict):
        self.instance_base, self.fhir_base = _canvas_api.hosts(env)
        self.token = _canvas_api.fetch_token(env, self.instance_base)
        self.created_this_run: set[str] = set()

    def request(self, method: str, path: str, payload: dict | None = None,
                params: dict | None = None):
        return _canvas_api.request(
            f"{self.fhir_base}{path}", self.token, method, payload, params,
            abort_epilogue=ABORT_EPILOGUE,
        )

    def instance_request(self, method: str, path: str, payload: dict | None = None):
        status, _headers, body = _canvas_api.request(
            f"{self.instance_base}{path}", self.token, method, payload,
            abort_epilogue=ABORT_EPILOGUE,
        )
        return status, body

    def create_patient(self, given: str, gender: str) -> str:
        payload = {
            "resourceType": "Patient",
            "extension": [{
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
                "valueCode": "F" if gender == "female" else "M",
            }],
            "name": [{"use": "official", "family": NAME_PREFIX, "given": [given, RUN_TAG]}],
            "gender": gender,
            "birthDate": "1981-01-01",
        }
        _s, headers, _b = self.request("POST", "/Patient", payload)
        patient_id = _canvas_api.id_from_location(headers, "Patient")
        _s, _h, stored = self.request("GET", f"/Patient/{patient_id}")
        names = (stored or {}).get("name", [])
        family_stored = names[0].get("family", "") if names else ""
        if not family_stored.startswith(NAME_PREFIX):
            abort(f"Read-back guard failure: Patient/{patient_id} family "
                  f"{family_stored!r} lacks the {NAME_PREFIX} prefix")
        self.created_this_run.add(patient_id)
        return patient_id

    def _guard(self, patient_id: str, what: str) -> None:
        if patient_id not in self.created_this_run:
            abort(f"PRE-WRITE GUARD: refusing {what} for Patient/{patient_id} — "
                  "id was not created in this run")

    def create_weight_observation(self, patient_id: str, when: date,
                                  value: float, unit: str) -> str:
        self._guard(patient_id, "Observation POST")
        effective = f"{when.isoformat()}T09:00:00+00:00"
        subject = {"reference": f"Patient/{patient_id}"}
        category = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs",
        }]}]
        _s, headers, _b = self.request("POST", "/Observation", {
            "resourceType": "Observation",
            "status": "final",
            "category": category,
            "code": {"coding": [{"system": "http://loinc.org", "code": "85353-1",
                                 "display": "Vital signs, weight, height, head circumference, oxygen saturation and BMI panel"}]},
            "subject": subject,
            "effectiveDateTime": effective,
        })
        panel_id = _canvas_api.id_from_location(headers, "Observation")
        self._guard(patient_id, "Observation POST")
        _s, headers, _b = self.request("POST", "/Observation", {
            "resourceType": "Observation",
            "status": "final",
            "category": category,
            "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7",
                                 "display": "Weight"}]},
            "subject": subject,
            "effectiveDateTime": effective,
            "valueQuantity": {"value": value, "unit": unit},   # unit "lb" exactly
            "derivedFrom": [{"reference": f"Observation/{panel_id}"}],
        })
        return _canvas_api.id_from_location(headers, "Observation")

    def create_medication_statement(self, patient_id: str, start: date,
                                    search_text: str, fallback: dict) -> str:
        self._guard(patient_id, "MedicationStatement POST")
        payload = {
            "resourceType": "MedicationStatement",
            "status": "active",
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectivePeriod": {"start": f"{start.isoformat()}T09:00:00+00:00"},
        }
        status, _h, bundle = self.request("GET", "/Medication", params={"_text": search_text})
        entries = (bundle or {}).get("entry", []) if status == 200 else []
        med = entries[0].get("resource") if entries else None
        if med and med.get("id"):
            payload["medicationReference"] = {"reference": f"Medication/{med['id']}"}
            codings = (med.get("code") or {}).get("coding") or []
            if codings:
                payload["medicationReference"]["display"] = codings[0].get("display", search_text)
        else:
            print(f"    Medication search for {search_text!r} empty — using RxNorm fallback")
            payload["medicationCodeableConcept"] = {
                "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": fallback["code"], "display": fallback["display"]}],
                "text": fallback["display"],
            }
        _s, headers, _b = self.request("POST", "/MedicationStatement", payload)
        return _canvas_api.id_from_location(headers, "MedicationStatement")

    def rename_patient(self, patient_id: str, given: str, family: str) -> None:
        # Phase-2 guard (rename_and_annotate pattern): created this run AND
        # read-back carries the seed name (or the target name on re-run).
        self._guard(patient_id, "Patient rename PUT")
        _s, _h, resource = self.request("GET", f"/Patient/{patient_id}")
        current_family = ((resource or {}).get("name") or [{}])[0].get("family", "")
        if current_family not in (NAME_PREFIX, family):
            abort(f"guard: Patient/{patient_id} family is {current_family!r} — "
                  "not a patient seeded by this run")
        resource["name"] = [{"use": "official", "family": family, "given": [given]}]
        resource.pop("text", None)
        self.request("PUT", f"/Patient/{patient_id}", resource)

    def create_scenario_note(self, patient_id: str, title: str) -> str | None:
        self._guard(patient_id, "scenario Note POST")
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _s, note = self.instance_request("POST", "/core/api/notes/v1/Note", {
            "title": title,
            "noteTypeName": NOTE_TYPE_NAME,
            "patientKey": patient_id,
            "providerKey": PROVIDER_KEY,
            "practiceLocationKey": PRACTICE_LOCATION_KEY,
            "encounterStartTime": now_iso,
        })
        return (note or {}).get("noteKey") or (note or {}).get("key")


def schedule_dates(cfg: dict, run_day: date) -> list[date]:
    offsets = cfg.get("day_offsets") or []
    if not offsets:
        return []
    anchor = run_day - timedelta(days=7) - timedelta(days=max(offsets))
    return [anchor + timedelta(days=o) for o in offsets]


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    now_utc = datetime.now(timezone.utc)
    if now_utc < MANUAL_BASELINE_CUTOVER:
        abort(f"Refusing to seed before the render-gate cutover "
              f"({MANUAL_BASELINE_CUTOVER.isoformat()}): P11's records would "
              f"be grandfathered into legacy mode. Now: {now_utc.isoformat()}")

    run_day = date.today()
    plan = {key: list(zip(schedule_dates(cfg, run_day),
                          [(w, "lb") for w in cfg["weights"]]))
            for key, cfg in PATIENTS.items()}

    if dry_run:
        for key, cfg in PATIENTS.items():
            med = cfg.get("medication_search", "none")
            print(f"{key} {NAME_PREFIX} {cfg['given']} ({RUN_TAG}) → "
                  f"{' '.join(cfg['rename'])}  medication={med}")
            for when, (value, unit) in plan[key]:
                print(f"    {when}  {value} {unit}")
        print("\nDry run only — nothing written.")
        return

    env = _canvas_api.load_env(
        required=("CANVAS_HOST", "CANVAS_CLIENT_ID", "CANVAS_CLIENT_SECRET")
    )
    api = CanvasFHIR(env)

    if not MANIFEST_PATH.exists():
        abort(f"Manifest {MANIFEST_PATH} missing — refusing to start a new one "
              "(P1–P9 entries must be preserved)")
    manifest = json.loads(MANIFEST_PATH.read_text())
    for key in PATIENTS:
        if key in manifest.get("patients", {}):
            abort(f"{key} already present in the manifest — additive seeder "
                  "refuses to reseed an existing fixture")

    manifest.setdefault("v05_run_tag", RUN_TAG)

    for key, cfg in PATIENTS.items():
        print(f"Creating {key}: {NAME_PREFIX} {cfg['given']} ({RUN_TAG})")
        patient_id = api.create_patient(cfg["given"], cfg["gender"])
        print(f"    Patient/{patient_id}")
        obs_ids = []
        for when, (value, unit) in plan[key]:
            obs_id = api.create_weight_observation(patient_id, when, value, unit)
            obs_ids.append(obs_id)
            print(f"    obs {when}  {value} {unit}  → {obs_id}")
        med_id = None
        if cfg.get("medication_search"):
            med_start = plan[key][0][0] if plan[key] else run_day - timedelta(days=63)
            med_id = api.create_medication_statement(
                patient_id, med_start, cfg["medication_search"],
                cfg.get("medication_fallback", {}),
            )
            print(f"    medication ({cfg['medication_search']}) → {med_id}")

        given, family = cfg["rename"]
        api.rename_patient(patient_id, given, family)
        print(f"    renamed → {given} {family}")
        note_key = api.create_scenario_note(patient_id, cfg["note_title"])
        print(f"    scenario note: {note_key}")

        manifest["patients"][key] = {
            "patient_id": patient_id,
            "name": f"{given} {family}",
            "chart_url": f"{api.instance_base}/patient/{patient_id}",
            "observation_ids": obs_ids,
            "medication_statement_id": med_id,
            "medication_search": cfg.get("medication_search"),
            "description_note_key": note_key,
            "scenario": cfg["note_title"],
            "seeded_by": "seed_v05_patients.py",
            "run_tag": RUN_TAG,
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"\nSeed complete (additive). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
