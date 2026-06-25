"""Regression tests for the PreToolUse guard wrapper's exit-code contract.

Background: the wrapper (`.claude/hooks/pretooluse_guards.sh`) once located the
engine via `$0`. When the hook runner did not set `$0` to the script path, the
relative `../lib/guard_engine.py` slipped, `python3` opened a missing file and
exited 2 — the SAME code the engine uses to BLOCK — so an infra path error was
misread as a guard block on every Bash call.

The contract these tests lock in:
  * the engine emits exactly 0 (ALLOW) or 2 (BLOCK),
  * the wrapper propagates an engine BLOCK as exit 2 (with a stderr reason),
  * the wrapper FAILS OPEN (exit 0) when the engine cannot be located/run, so a
    broken guard can never block all tool use.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

CLAUDE_DIR = Path(__file__).resolve().parents[1] / ".claude"
HOOK = CLAUDE_DIR / "hooks" / "pretooluse_guards.sh"
ENGINE = CLAUDE_DIR / "lib" / "guard_engine.py"

# A benign call the ruleset should allow.
ALLOW_INPUT = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
# `canvas install` against a non-dev host must be blocked (command_host_allowlist).
BLOCK_INPUT = {
    "tool_name": "Bash",
    "tool_input": {"command": "canvas install --host https://prod.example.com"},
}

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="bash and python3 are required to exercise the hook wrapper",
)


def _run(argv: list[str], payload: dict) -> subprocess.CompletedProcess[str]:
    # Isolate the engine's persistent repeat-counter (block_<hash>.count) per call
    # via a fresh AGENT_CACHE_DIR, so a block test sees a first-time "BLOCKED" and
    # not an escalated "REPEATED BLOCK (n=…)" inherited from prior sessions/runs.
    env = {**os.environ, "AGENT_CACHE_DIR": tempfile.mkdtemp(prefix="guard_attempts_")}
    return subprocess.run(
        argv,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


def test_hook_allows_benign_call() -> None:
    res = _run(["bash", str(HOOK)], ALLOW_INPUT)
    assert res.returncode == 0, res.stderr


def test_hook_blocks_disallowed_call_with_reason() -> None:
    res = _run(["bash", str(HOOK)], BLOCK_INPUT)
    assert res.returncode == 2, f"expected BLOCK, got {res.returncode}: {res.stderr}"
    assert "BLOCKED" in res.stderr


def test_hook_fails_open_when_engine_missing(tmp_path: Path) -> None:
    # Copy only the wrapper into an isolated tree (no sibling lib/ engine).
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    stray = hooks / HOOK.name
    shutil.copy(HOOK, stray)
    res = _run(["bash", str(stray)], ALLOW_INPUT)
    assert res.returncode == 0, "missing engine must fail open, not block"
    assert "fail-open" in res.stderr


def test_engine_two_valued_contract() -> None:
    allow = _run(["python3", str(ENGINE)], ALLOW_INPUT)
    assert allow.returncode == 0, allow.stderr
    block = _run(["python3", str(ENGINE)], BLOCK_INPUT)
    assert block.returncode == 2, block.stderr
