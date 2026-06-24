"""TIER 2 — generic config loader. The sole reader of the project pack
(agent.config.json). No project name appears in this file; it is data read at
runtime. Swapping the Tier-3 pack reconfigures the machinery with no code change.
"""
from __future__ import annotations

import json
import os
import pathlib

AGENT_DIR = pathlib.Path(__file__).resolve().parents[1]  # .claude/
_CONFIG_PATH = pathlib.Path(os.environ.get("AGENT_CONFIG", AGENT_DIR / "agent.config.json"))


def _load_dotenv() -> None:
    """Fold a local, gitignored `.claude/.env` into os.environ for the hook path.

    Claude Code expands `${VAR}` in `.mcp.json` from the *launch* shell only, so
    the in-session agents still need the URLs/tokens exported at launch. But the
    hooks (server_sync.py) run as plain subprocesses and read os.environ at
    runtime, so honoring this file lets a user paste the tokens once and have the
    reconcile path work without re-exporting. The real environment always wins
    (setdefault), so an explicit export overrides the file.
    """
    env_path = AGENT_DIR / ".env"
    try:
        lines = env_path.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()



class AgentConfig:
    def __init__(self) -> None:
        with _CONFIG_PATH.open() as fh:
            self._raw = json.load(fh)

    @property
    def project(self) -> str:
        return self._raw["project"]

    @property
    def memory_namespace(self) -> str:
        return self._raw["memory_namespace"]

    @property
    def key_scopes(self) -> dict:
        return self._raw.get("key_scopes", {})

    def scoped_key(self, scope: str, key: str) -> str:
        return f"{self.key_scopes.get(scope, '')}{key}"

    @property
    def guards_rules_path(self) -> pathlib.Path:
        return AGENT_DIR / self._raw["guards_rules"]

    @property
    def claude_md_path(self) -> pathlib.Path:
        return (AGENT_DIR / self._raw["claude_md"]).resolve()

    @property
    def test_project(self) -> str:
        return self._raw.get("test_project", "proj-test")

    def env_name(self, logical: str) -> str:
        return self._raw.get("env", {}).get(logical, logical.upper())


def load() -> AgentConfig:
    return AgentConfig()
