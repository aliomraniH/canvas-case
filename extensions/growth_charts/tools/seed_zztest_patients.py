#!/usr/bin/env python3
"""
Seed ZZTEST-GLP1 test patients (P1-P9) for cardiometabolic_tracker v0.2.

HARD RULES (spec section 3):
  * Observation writes to this sandbox are PERMANENT (DELETE/PUT/PATCH and
    enter_in_error() are all blocked — verified in v0.1).
  * NEVER writes to an existing patient. Every Observation and
    MedicationStatement POST passes the pre-write guard: the target patient id
    must have been returned by a Patient create call IN THIS RUN, and the
    patient's stored family name must start with ZZTEST-GLP1 (verified by
    reading the created patient back). Any guard failure aborts the entire run.
  * Idempotency: re-runs create NEW patients (tagged with a run id in the
    given name); prior patients are never touched.

Endpoints: Canvas FHIR API on the fumage host — the v0.1-verified working
path on this instance (demo_patients.md): token via /auth/token/ on the
instance host, then POST /Patient, POST /Observation (two-step: Vital Signs
Panel 85353-1, then weight 29463-7 with derivedFrom), and POST
/MedicationStatement (medicationReference resolved via Medication?_text=
search per the v0.2 addendum; RxNorm medicationCodeableConcept fallback).

Credentials: read from extensions/.env ONLY. Never hardcoded, never printed.

Usage:
  python3 tools/seed_zztest_patients.py --dry-run   # print plan, no writes
  python3 tools/seed_zztest_patients.py             # seed for real

After seeding, run tools/rename_and_annotate_patients.py to give the new
patients their readable demo names (Margaret Okafor, Derek Vance, ...) and a
chart note describing each scenario — its guard accepts only ZZTEST-GLP1
patients from the freshly written manifest, so the two-step flow stays safe.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone

import _canvas_api

OUT_PATH = _canvas_api.EXTENSIONS_DIR / ".workspace_state" / "debug" / "seeded_patients.json"

ABORT_EPILOGUE = "No further writes will be attempted in this run."

RUN_TAG = datetime.now(timezone.utc).strftime("R%Y%m%d%H%M")
NAME_PREFIX = "ZZTEST-GLP1"

# ── Series definitions (spec 3.1). spacing_days between consecutive points;
# explicit day_offsets override spacing. Values are (weight, unit) or weight
# (defaults to lbs). The whole series is anchored so the LAST observation
# lands one week before the run date.
PATIENTS = {
    "P1": {
        "given": "Responder",
        "gender": "female",
        "spacing_days": 14,
        "weights": [220.0, 218.1, 216.4, 214.0, 211.8, 209.4, 207.2, 205.1,
                    202.9, 200.6, 198.0, 196.4, 195.1, 194.0, 193.4],
        "medication_search": "wegovy",
        "medication_fallback": {"code": "2553501", "display": "Wegovy 2.4 MG/0.75 ML Pen Injector"},
    },
    "P2": {
        "given": "Nonresponder",
        "gender": "male",
        "spacing_days": 14,
        "weights": [245.0, 244.2, 243.5, 243.0, 242.1, 241.4, 240.6, 239.9],
        # NO medication record — live test of the default-agent fallback.
    },
    "P3": {
        "given": "Plateau",
        "gender": "female",
        "spacing_days": 14,
        "weights": [232.0, 229.8, 227.1, 224.6, 222.0, 219.5, 217.4, 215.8,
                    215.3, 215.0, 214.8, 214.7, 214.6, 214.6, 214.5],
        "medication_search": "zepbound",
        "medication_fallback": {"code": "2601723", "display": "Zepbound 10 MG/0.5 ML Pen Injector"},
    },
    "P4": {
        "given": "Rapid",
        "gender": "male",
        "spacing_days": 7,
        "weights": [260.0, 256.2, 252.5, 248.9, 245.3, 241.8, 238.4, 235.0,
                    231.7, 228.5, 225.4],
        "medication_search": "saxenda",
        "medication_fallback": {"code": "1727500", "display": "Saxenda 18 MG/3 ML Pen Injector"},
    },
    "P5": {
        "given": "Regain",
        "gender": "female",
        "spacing_days": 14,
        "weights": [215.0, 212.4, 209.7, 206.9, 204.3, 202.0, 199.5, 197.3,
                    195.7, 197.0, 199.2, 201.6, 204.0, 206.5],
    },
    "P6": {
        "given": "Sparse",
        "gender": "male",
        "day_offsets": [0, 90],
        "weights": [240.0, 233.5],
    },
    "P7": {
        "given": "Single",
        "gender": "female",
        "day_offsets": [0],
        "weights": [198.0],
    },
    "P8": {
        "given": "MixedUnits",
        "gender": "male",
        "spacing_days": 14,
        "weights": [(104.3, "kg"), (228.0, "lb"), (102.1, "kg"),
                    (223.0, "lb"), (100.2, "kg"), (219.0, "lb")],
    },
    "P9": {
        "given": "Duplicate",
        "gender": "female",
        "day_offsets": [0, 14, 14, 28],
        "weights": [250.0, 247.0, 246.4, 244.0],
    },
}


def load_env() -> dict:
    return _canvas_api.load_env(
        required=("CANVAS_HOST", "CANVAS_CLIENT_ID", "CANVAS_CLIENT_SECRET")
    )


def abort(message: str) -> None:
    _canvas_api.abort(message, ABORT_EPILOGUE)


class CanvasFHIR:
    """Guarded FHIR write session. HTTP/auth plumbing lives in _canvas_api;
    everything write-safety-related (the pre-write guard) lives HERE."""

    def __init__(self, env: dict):
        self.instance_base, self.fhir_base = _canvas_api.hosts(env)
        self.token = _canvas_api.fetch_token(env, self.instance_base)
        # Pre-write guard state: ONLY ids returned by Patient creates this run.
        self.created_this_run: set[str] = set()

    def request(self, method: str, path: str, payload: dict | None = None,
                params: dict | None = None) -> tuple[int, dict, dict | None]:
        return _canvas_api.request(
            f"{self.fhir_base}{path}", self.token, method, payload, params,
            abort_epilogue=ABORT_EPILOGUE,
        )

    @staticmethod
    def id_from_location(headers: dict, resource: str) -> str:
        return _canvas_api.id_from_location(headers, resource)

    # ── Guarded operations ────────────────────────────────────────────

    def create_patient(self, given: str, gender: str) -> str:
        family = NAME_PREFIX
        payload = {
            "resourceType": "Patient",
            # us-core-birthsex extension is REQUIRED on create (Canvas docs).
            "extension": [{
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
                "valueCode": "F" if gender == "female" else "M",
            }],
            "name": [{"use": "official", "family": family, "given": [given, RUN_TAG]}],
            "gender": gender,
            "birthDate": "1980-01-01",
        }
        _status, headers, _body = self.request("POST", "/Patient", payload)
        patient_id = self.id_from_location(headers, "Patient")

        # Read-back verification: the stored name must carry the prefix BEFORE
        # this id is admitted to the writable set.
        _s, _h, stored = self.request("GET", f"/Patient/{patient_id}")
        names = (stored or {}).get("name", [])
        family_stored = names[0].get("family", "") if names else ""
        if not family_stored.startswith(NAME_PREFIX):
            abort(
                f"Read-back guard failure: Patient/{patient_id} family name "
                f"{family_stored!r} lacks the {NAME_PREFIX} prefix"
            )
        self.created_this_run.add(patient_id)
        return patient_id

    def _guard(self, patient_id: str, what: str) -> None:
        if patient_id not in self.created_this_run:
            abort(
                f"PRE-WRITE GUARD: refusing {what} for Patient/{patient_id} — "
                "id was not created in this run"
            )

    def create_weight_observation(self, patient_id: str, when: date,
                                  value: float, unit: str) -> str:
        self._guard(patient_id, "Observation POST")
        effective = f"{when.isoformat()}T09:00:00+00:00"
        subject = {"reference": f"Patient/{patient_id}"}
        category = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs",
        }]}]
        # Step 1: Vital Signs Panel (85353-1) — required parent (demo_patients.md).
        _s, headers, _b = self.request("POST", "/Observation", {
            "resourceType": "Observation",
            "status": "final",
            "category": category,
            "code": {"coding": [{"system": "http://loinc.org", "code": "85353-1",
                                 "display": "Vital signs, weight, height, head circumference, oxygen saturation and BMI panel"}]},
            "subject": subject,
            "effectiveDateTime": effective,
        })
        panel_id = self.id_from_location(headers, "Observation")
        # Step 2: the weight itself, derived from the panel.
        self._guard(patient_id, "Observation POST")
        _s, headers, _b = self.request("POST", "/Observation", {
            "resourceType": "Observation",
            "status": "final",
            "category": category,
            "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7",
                                 "display": "Weight"}]},
            "subject": subject,
            "effectiveDateTime": effective,
            "valueQuantity": {"value": value, "unit": unit},
            "derivedFrom": [{"reference": f"Observation/{panel_id}"}],
        })
        return self.id_from_location(headers, "Observation")

    def find_medication(self, search_text: str) -> dict | None:
        """Medication search endpoint (addendum-preferred medicationReference)."""
        status, _h, bundle = self.request("GET", "/Medication", params={"_text": search_text})
        entries = (bundle or {}).get("entry", [])
        if status == 200 and entries:
            return entries[0].get("resource")
        return None

    def create_medication_statement(self, patient_id: str, start: date,
                                    search_text: str, fallback: dict) -> str:
        self._guard(patient_id, "MedicationStatement POST")
        payload = {
            "resourceType": "MedicationStatement",
            "status": "active",
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectivePeriod": {"start": f"{start.isoformat()}T09:00:00+00:00"},
        }
        med_resource = self.find_medication(search_text)
        if med_resource and med_resource.get("id"):
            payload["medicationReference"] = {
                "reference": f"Medication/{med_resource['id']}",
            }
            codings = (med_resource.get("code") or {}).get("coding") or []
            if codings:
                payload["medicationReference"]["display"] = codings[0].get("display", search_text)
        else:
            print(f"    Medication search for {search_text!r} empty — using RxNorm fallback")
            payload["medicationCodeableConcept"] = {
                "coding": [{
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": fallback["code"],
                    "display": fallback["display"],
                }],
                "text": fallback["display"],
            }
        _s, headers, _b = self.request("POST", "/MedicationStatement", payload)
        return self.id_from_location(headers, "MedicationStatement")


def schedule_dates(cfg: dict, run_day: date) -> list[date]:
    """Anchor each series so its LAST observation is one week before the run."""
    offsets = cfg.get("day_offsets")
    if offsets is None:
        offsets = [i * cfg["spacing_days"] for i in range(len(cfg["weights"]))]
    last_offset = max(offsets)
    anchor = run_day - timedelta(days=7) - timedelta(days=last_offset)
    return [anchor + timedelta(days=o) for o in offsets]


def normalized_weights(cfg: dict) -> list[tuple[float, str]]:
    # Canvas's weight vital validation accepts "lb" (not "lbs").
    return [w if isinstance(w, tuple) else (w, "lb") for w in cfg["weights"]]


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    run_day = date.today()
    plan = {}
    for key, cfg in PATIENTS.items():
        dates = schedule_dates(cfg, run_day)
        plan[key] = list(zip(dates, normalized_weights(cfg)))

    if dry_run:
        for key, rows in plan.items():
            cfg = PATIENTS[key]
            med = cfg.get("medication_search", "none")
            print(f"{key} ZZTEST-GLP1 {cfg['given']} ({RUN_TAG})  medication={med}")
            for when, (value, unit) in rows:
                print(f"    {when}  {value} {unit}")
        print("\nDry run only — nothing written.")
        return

    env = load_env()
    api = CanvasFHIR(env)
    manifest = {"run_tag": RUN_TAG, "run_date": run_day.isoformat(),
                "instance": api.instance_base, "patients": {}}

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
            med_id = api.create_medication_statement(
                patient_id, plan[key][0][0],
                cfg["medication_search"], cfg.get("medication_fallback", {}),
            )
            print(f"    medication ({cfg['medication_search']}) → {med_id}")
        manifest["patients"][key] = {
            "patient_id": patient_id,
            "name": f"{NAME_PREFIX} {cfg['given']} {RUN_TAG}",
            "chart_url": f"{api.instance_base}/patient/{patient_id}",
            "observation_ids": obs_ids,
            "medication_statement_id": med_id,
            "medication_search": cfg.get("medication_search"),
        }
        # Persist progress after every patient so a later abort loses nothing.
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(manifest, indent=2))

    print(f"\nSeed complete. Manifest: {OUT_PATH}")


if __name__ == "__main__":
    main()
