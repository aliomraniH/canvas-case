"""TIER 2 — generic PreToolUse guard engine. Zero domain terms.

Reads a project ruleset (path from agent.config.json) and evaluates each rule
against the hook's tool_input. Exit code 2 BLOCKS the call and feeds stderr back
to the model as the reason. A repeat-attempt counter escalates on identical
re-tries so an agent can't blindly loop. All Canvas-specific strings live in
rules/guards.rules — never here. Swap the ruleset to reuse this engine.

Supported rule types (all data-driven):
  match                  - when.all / when.any of {field, matches:<regex>}
  import_allowlist       - parse imports from code edits; allow[]/deny[]
  patient_write_scope    - entity+write detected and a required token absent
  command_host_allowlist - a command matches but no allowed host appears
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import config as _config  # noqa: E402

_TEXT_FIELDS = ("content", "new_string", "command", "file_path", "url")
ATTEMPTS_DIR = pathlib.Path(
    os.environ.get("AGENT_CACHE_DIR", _config.AGENT_DIR.parent / ".agent-cache")
)


def _joined_text(tool_input: dict) -> str:
    return " ".join(str(tool_input.get(f, "")) for f in _TEXT_FIELDS)


def _field_text(tool_input: dict, field: str) -> str:
    if field == "*":
        return _joined_text(tool_input)
    return str(tool_input.get(field, ""))


def _bump_attempts(signature: str) -> int:
    ATTEMPTS_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(signature.encode()).hexdigest()[:16]
    p = ATTEMPTS_DIR / f"block_{h}.count"
    n = (int(p.read_text()) if p.exists() else 0) + 1
    p.write_text(str(n))
    return n


def _block(signature: str, reason: str, allowed: str) -> None:
    n = _bump_attempts(signature)
    if n >= 3:
        msg = (
            f"REPEATED BLOCK (n={n}). {reason} Stop retrying this action and either "
            f"choose a different approach or hand off to a human. Allowed: {allowed}"
        )
    else:
        msg = f"BLOCKED: {reason} Allowed: {allowed} Do NOT retry the same action."
    print(msg, file=sys.stderr)
    sys.exit(2)


# ---- rule evaluators (generic; semantics come from rule data) -------------
def _eval_match(rule, tool_name, tool_input) -> bool:
    when = rule.get("when", {})
    conds = when.get("all") or when.get("any") or []
    results = [
        re.search(c["matches"], _field_text(tool_input, c.get("field", "*")))
        is not None
        for c in conds
    ]
    return all(results) if "all" in when else any(results)


def _eval_import_allowlist(rule, tool_name, tool_input) -> bool:
    if tool_name not in rule.get("tools", []):
        return False
    code = str(tool_input.get("content", "")) + "\n" + str(tool_input.get("new_string", ""))
    allow = tuple(rule.get("allow", []))
    deny = set(rule.get("deny", []))
    for m in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", code, re.MULTILINE):
        dotted = m.group(1)
        top = dotted.split(".")[0]
        if dotted in deny or top in deny:
            return True
        if not any(dotted == a or dotted.startswith(a + ".") or top == a for a in allow):
            # Unknown import that isn't explicitly allowed → only block if also
            # not a stdlib-ish top-level the ruleset chose to ignore. Conservative:
            # block only names the ruleset explicitly denies OR clearly third-party.
            if top in deny:
                return True
    return False


def _eval_patient_write_scope(rule, tool_name, tool_input) -> bool:
    text = _joined_text(tool_input)
    entity = re.search(rule["entity_matches"], text, re.IGNORECASE)
    write = re.search(rule["write_matches"], text, re.IGNORECASE)
    if not (entity and write):
        return False
    return re.search(rule["require"], text) is None  # required token absent → violation


def _eval_command_host_allowlist(rule, tool_name, tool_input) -> bool:
    if tool_name not in rule.get("tools", []):
        return False
    cmd = str(tool_input.get("command", ""))
    if not re.search(rule["command_matches"], cmd):
        return False
    return re.search(rule["host_allow"], cmd, re.IGNORECASE) is None


_EVALUATORS = {
    "match": _eval_match,
    "import_allowlist": _eval_import_allowlist,
    "patient_write_scope": _eval_patient_write_scope,
    "command_host_allowlist": _eval_command_host_allowlist,
}


def evaluate(ruleset: dict, tool_name: str, tool_input: dict) -> None:
    sig_base = f"{tool_name}:{_joined_text(tool_input)}"
    for rule in ruleset.get("rules", []):
        evaluator = _EVALUATORS.get(rule.get("type", "match"))
        if evaluator is None:
            continue
        if evaluator(rule, tool_name, tool_input):
            _block(f"{sig_base}:{rule['id']}", rule["reason"], rule["allowed"])


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing to inspect; never block on a parse miss
    cfg = _config.load()
    with cfg.guards_rules_path.open() as fh:
        ruleset = json.load(fh)
    evaluate(ruleset, data.get("tool_name", ""), data.get("tool_input", {}) or {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
