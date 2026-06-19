"""PreToolUse guard teeth (Phase 4). Deterministic, no server needed.

Reads the hook JSON on stdin. Exit code 2 BLOCKS the tool call and feeds stderr
back to the model as the reason — so stderr is a precise *negative constraint*,
not a generic denial. A repeat-attempt counter escalates on identical re-tries so
the agent can't blindly loop (addendum #3).

Blocks:
  * FHIR Observation PATCH/DELETE (immutable: Create/Read/Search only)
  * writes to canvas_sdk.v1.data models (read-only; use typed Effects)
  * non-allow-listed imports (RestrictedPython sandbox)
  * writes to a non-ZZTEST patient
  * `canvas install` targeting a non-dev host
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import time

ATTEMPTS_DIR = pathlib.Path(
    pathlib.Path(__file__).resolve().parents[2] / ".agent-cache"
)
ALLOWED_IMPORTS_PREFIXES = (
    "canvas_sdk", "datetime", "json", "math", "re", "typing", "decimal",
    "collections", "enum", "dataclasses", "functools", "itertools", "uuid",
    "__future__",
)
DEV_HOST_RE = re.compile(r"(dev|uat|sandbox|localhost|127\.0\.0\.1)", re.IGNORECASE)


def _attempts_path(key_hash: str) -> pathlib.Path:
    ATTEMPTS_DIR.mkdir(parents=True, exist_ok=True)
    return ATTEMPTS_DIR / f"block_{key_hash}.count"


def _bump_attempts(signature: str) -> int:
    h = hashlib.sha256(signature.encode()).hexdigest()[:16]
    p = _attempts_path(h)
    n = (int(p.read_text()) if p.exists() else 0) + 1
    p.write_text(str(n))
    return n


def block(signature: str, reason: str, allowed: str) -> None:
    n = _bump_attempts(signature)
    msg = f"BLOCKED: {reason} Allowed: {allowed} Do NOT retry the same action."
    if n >= 3:
        msg = (
            f"REPEATED BLOCK (n={n}). {reason} Stop retrying this action and either "
            f"choose a different approach or hand off to a human. Allowed: {allowed}"
        )
    print(msg, file=sys.stderr)
    sys.exit(2)


def check(tool_name: str, tool_input: dict) -> None:
    text_fields = " ".join(
        str(tool_input.get(f, "")) for f in ("content", "new_string", "command", "file_path", "url")
    )
    sig = f"{tool_name}:{text_fields}"

    # 1. FHIR Observation PATCH/DELETE
    if re.search(r"Observation", text_fields) and re.search(r"\b(PATCH|DELETE)\b", text_fields):
        block(sig, "FHIR Observations are immutable (Create/Read/Search only).",
              "create a new Observation, or mark the prior one entered_in_error.")

    # 2. Writes to read-only data models
    if re.search(r"canvas_sdk\.v1\.data", text_fields) and re.search(
        r"\.(save|create|update|delete)\(", text_fields
    ):
        block(sig, "canvas_sdk.v1.data models are read-only.",
              "return a typed Effect from compute() instead of writing directly.")

    # 3. Non-allow-listed imports (only inspect code edits)
    if tool_name in ("Write", "Edit"):
        code = str(tool_input.get("content", "")) + str(tool_input.get("new_string", ""))
        for m in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", code, re.MULTILINE):
            mod = m.group(1).split(".")[0]
            if not any(m.group(1).startswith(p) for p in ALLOWED_IMPORTS_PREFIXES) and mod not in (
                "os", "sys"  # allowed in tooling/scripts, blocked only inside sandbox modules
            ):
                # Heuristic: flag clearly non-allow-listed third-party imports.
                if mod in ("requests", "httpx", "subprocess", "socket", "pickle", "ctypes"):
                    block(sig, f"Import '{mod}' is not on the sandbox allow-list.",
                          "use canvas_sdk.utils.http.Http; no raw network/process/serialization libs.")

    # 4. Non-ZZTEST patient writes (live writes only to ZZTEST-*)
    if re.search(r"\b(patient|first_name|last_name)\b", text_fields, re.IGNORECASE) and re.search(
        r"\b(create|POST|write|save)\b", text_fields, re.IGNORECASE
    ):
        # If a patient identifier appears, require it to be ZZTEST-*.
        if re.search(r"ZZTEST", text_fields):
            pass
        elif re.search(r"patient[_-]?id|mrn|first_name", text_fields, re.IGNORECASE):
            block(sig, "Live writes may target ZZTEST-* test patients only.",
                  "use a ZZTEST-* patient; existing patients are read-only fixtures.")

    # 5. canvas install / deploy to a non-dev host
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        if re.search(r"canvas\s+install", cmd) and not DEV_HOST_RE.search(cmd):
            block(sig, "canvas install may target the DEV/UAT host only.",
                  "pass a dev/uat/sandbox host; production deploys require human sign-off.")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing to inspect; do not block
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    check(tool_name, tool_input)
    return 0


if __name__ == "__main__":
    sys.exit(main())
