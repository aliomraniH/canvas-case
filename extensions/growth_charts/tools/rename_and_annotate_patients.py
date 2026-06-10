#!/usr/bin/env python3
"""
One-off (2026-06-10): give the nine seeded GLP-1 demo patients distinct,
realistic names and attach one chart note describing each scenario.

Requested after v0.2 sign-off: the ZZTEST-GLP1 role names were hard to tell
apart in patient lists. Patient identity (id), observations, and medication
records are untouched — only the Patient.name changes (FHIR PUT, verified
allowed on this sandbox) plus one new Note per patient (Canvas Note API).

WRITE SAFETY: every write targets an id loaded from the seeded manifest
(.workspace_state/debug/seeded_patients.json) — the nine patients created by
seed_zztest_patients.py on 2026-06-10. Before each write, the patient is read
back and must carry either the original ZZTEST-GLP1 family name or the new
target name (re-run idempotency). Anything else aborts the run. Pre-existing
patients are never touched.

Usage: python3 tools/rename_and_annotate_patients.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EXTENSIONS_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = EXTENSIONS_DIR / ".env"
MANIFEST_PATH = EXTENSIONS_DIR / ".workspace_state" / "debug" / "seeded_patients.json"

# Looked up live (FHIR Practitioner/Location search, 2026-06-10):
PROVIDER_KEY = "e766816672f34a5b866771c773e38f3c"          # Richard Wilson MD
PRACTICE_LOCATION_KEY = "d1eacdb5-9ead-47ce-855a-c8c6ef3932a6"  # California location
NOTE_TYPE_NAME = "Office visit"

# key → (given, family, note title describing the scenario)
RENAMES = {
    "P1": ("Margaret", "Okafor",
           "GLP-1 weight mgmt — strong semaglutide responder: 12.1% TBWL at week 28, 5% and 10% milestones crossed"),
    "P2": ("Derek", "Vance",
           "GLP-1 weight mgmt — non-responder: 2.1% TBWL at week 14, tracking above expected band; no GLP-1 med on file"),
    "P3": ("Sylvia", "Tran",
           "GLP-1 weight mgmt — plateau on tirzepatide: lost 7.5% then flat weeks 16-28 (plateau flag expected)"),
    "P4": ("Hector", "Ramirez",
           "GLP-1 weight mgmt — rapid loss on liraglutide: ~1.3%/week over 10 weeks (rapid-loss flag expected)"),
    "P5": ("Janelle", "Whitfield",
           "GLP-1 weight mgmt — regain: reached 9% TBWL by week 16, regained to ~4% by week 26 (regain flag expected)"),
    "P6": ("Owen", "Castellano",
           "GLP-1 weight mgmt — sparse data: only two weights, 90 days apart"),
    "P7": ("Priya", "Raghunathan",
           "GLP-1 weight mgmt — single measurement: minimum-data chart state"),
    "P8": ("Tobias", "Lindqvist",
           "GLP-1 weight mgmt — mixed units: weights alternate kg and lb entries"),
    "P9": ("Carmen", "Delgado",
           "GLP-1 weight mgmt — duplicate same-day weights: tests averaging dedup"),
}


def abort(message: str) -> None:
    print(f"\nABORT: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_env() -> dict:
    env: dict = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def request(url: str, token: str, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        abort(f"{method} {url} → HTTP {exc.code}: {exc.read().decode()[:400]}")


def main() -> None:
    env = load_env()
    host = env["CANVAS_HOST"].replace("https://", "").replace("http://", "").strip("/")
    instance = f"https://{host}"
    fhir = f"https://fumage-{host}"

    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": env["CANVAS_CLIENT_ID"],
        "client_secret": env["CANVAS_CLIENT_SECRET"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(
        f"{instance}/auth/token/", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )) as resp:
        token = json.loads(resp.read().decode()).get("access_token", "")
    if not token:
        abort("no access_token")

    manifest = json.loads(MANIFEST_PATH.read_text())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for key, info in manifest["patients"].items():
        given, family, note_title = RENAMES[key]
        patient_id = info["patient_id"]
        print(f"[{key}] {patient_id} → {given} {family}")

        # Read back + guard: only our seeded patients (old or already-new name).
        _s, resource = request(f"{fhir}/Patient/{patient_id}", token)
        current_family = (resource.get("name") or [{}])[0].get("family", "")
        if current_family not in ("ZZTEST-GLP1", family):
            abort(f"guard: Patient/{patient_id} family is {current_family!r} — not a seeded demo patient")

        # Rename (full-resource PUT; drop server-generated narrative).
        resource["name"] = [{"use": "official", "family": family, "given": [given]}]
        resource.pop("text", None)
        request(f"{fhir}/Patient/{patient_id}", token, "PUT", resource)
        print(f"    renamed (was {current_family})")

        # One descriptive chart note per patient (skip if already created).
        if not info.get("description_note_key"):
            _s, note = request(f"{instance}/core/api/notes/v1/Note", token, "POST", {
                "title": note_title,
                "noteTypeName": NOTE_TYPE_NAME,
                "patientKey": patient_id,
                "providerKey": PROVIDER_KEY,
                "practiceLocationKey": PRACTICE_LOCATION_KEY,
                "encounterStartTime": now_iso,
            })
            note_key = (note or {}).get("noteKey") or (note or {}).get("key")
            info["description_note_key"] = note_key
            print(f"    note created: {note_key} — {note_title[:60]}...")

        info["name"] = f"{given} {family}"
        info["scenario"] = note_title
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print("\nDone. Manifest updated:", MANIFEST_PATH)


if __name__ == "__main__":
    main()
