"""
Shared Canvas API plumbing for tools/ scripts (v0.2.2, review finding 5).

Used by seed_zztest_patients.py and rename_and_annotate_patients.py so .env
loading, OAuth token fetch, and HTTP request handling exist exactly once.
Pure plumbing — all write-safety guards stay in the calling scripts.

Credentials come from extensions/.env ONLY. Never hardcoded, never printed.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EXTENSIONS_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = EXTENSIONS_DIR / ".env"


def abort(message: str, epilogue: str | None = None) -> None:
    """Print the failure and stop the run. Callers rely on this never returning."""
    print(f"\nABORT: {message}", file=sys.stderr)
    if epilogue:
        print(epilogue, file=sys.stderr)
    raise SystemExit(1)


def load_env(required: tuple = ()) -> dict:
    """Parse extensions/.env (KEY=value lines). Aborts on missing file/keys."""
    if not ENV_PATH.exists():
        abort(f"Missing credentials file: {ENV_PATH}")
    env: dict = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in required:
        if not env.get(key):
            abort(f"{key} missing from extensions/.env")
    return env


def hosts(env: dict) -> tuple[str, str]:
    """(instance_base, fhir_base) from CANVAS_HOST, scheme-tolerant."""
    host = env["CANVAS_HOST"].replace("https://", "").replace("http://", "").strip("/")
    return f"https://{host}", f"https://fumage-{host}"


def fetch_token(env: dict, instance_base: str) -> str:
    """OAuth client-credentials token from <instance>/auth/token/."""
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": env["CANVAS_CLIENT_ID"],
        "client_secret": env["CANVAS_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        f"{instance_base}/auth/token/", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            token = json.loads(resp.read().decode()).get("access_token", "")
    except Exception as exc:
        abort(f"Token request failed: {type(exc).__name__}: {exc}")
    if not token:
        abort("Token response carried no access_token")
    return token


def request(url: str, token: str, method: str = "GET", payload: dict | None = None,
            params: dict | None = None,
            abort_epilogue: str | None = None) -> tuple[int, dict, dict | None]:
    """JSON request with bearer auth → (status, headers, parsed body).

    HTTP errors abort the run (the safe default for write scripts — callers
    that can continue past a failure should not exist in this toolset).
    `abort_epilogue` lets write scripts keep their run-level abort notice.
    """
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, dict(resp.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        abort(f"{method} {url} failed: HTTP {exc.code} — {exc.read().decode()[:500]}",
              abort_epilogue)


def id_from_location(headers: dict, resource: str) -> str:
    """Extract the created resource id from a create response's Location header."""
    location = headers.get("Location") or headers.get("location") or ""
    marker = f"/{resource}/"
    if marker not in location:
        abort(f"Create response Location missing {resource} id: {location!r}")
    return location.split(marker, 1)[1].split("/")[0]
