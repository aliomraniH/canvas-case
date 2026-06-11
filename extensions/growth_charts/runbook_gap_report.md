# RUNBOOK Gap Report — v0.3.0-export cold-start stress test

Session: CPA CLI builder, 2026-06-11. RUNBOOK read first (cold), before any
repo file. Every question below was logged as it occurred during the build.

---

## 1. Answered (questions the RUNBOOK resolved)

- Where is the repo and what is the plugin actually called? — §1 (`growth_charts` folder, `cardiometabolic_tracker` name).
- Which sandbox instance and login do live checks use? — §1.
- Which Python runs pytest (and avoids the system-python trap)? — §1 / §3.
- What is the mandatory gate order? pytest → install → Tier 0 → Tier 2 — §3.
- Why can't I trust a green pytest run? Mock false-green warning + skip-count rule — §3.
- What is the handoff artifact after deploy and who consumes it? deploy-report → Desktop reviewer — §2.5.
- Is an MCP memory server allowed? No — deferred, git is the only sync medium — §2.5 / §4.10.
- What iframe context does the chart render in, and do Tier selectors survive target switches? `about:srcdoc`, yes — §5.
- What is the network signature the export must preserve? One GraphQL POST, no FHIR from browser — §5.
- What does the validation layer guarantee before any modal? `validate_chart_payload()` runs first; failure returns an error modal, never `[]` — §5.
- How do I triage console errors in live checks? Classify plugin/host/unknown, assert plugin-only — §5 (this rule directly resolved the only red check in the Tier 0 run).
- Which patients may be written to, and who is untouchable? ZZTEST-only; Samuel Alta never — §4 / §6.
- Which trials anchor the clinical content? STEP-1 / SURMOUNT-1 / SCALE + the SCALE estimated-disclosure rule — §7 / §4.9.
- Field-name gotchas (`units`, `dbid__in`, `lb`, `from __future__ import annotations`, `.get()`) — §5, all held true.

## 2. Missing (questions the RUNBOOK could not answer)

- **Where do live browser checks run from, and with what tooling?** §3 says "Desktop + Chrome connector" but the workspace contains a Playwright harness (`.workspace_state/debug/tools/tier2_v02_assertions.js`) runnable from the CLI with credentials in `extensions/.env`. The build prompt required Tier 0 + `--capture` from this session; the RUNBOOK gave no path to it.
  *Suggested edit (§3, after the Tier 2 line):* "CLI sessions can run the Playwright harness directly: `node .workspace_state/debug/tools/tier2_v02_assertions.js [P1 ...] [--capture]` (login creds from `extensions/.env`; patient registry in `.workspace_state/debug/seeded_patients.json`). Login selector is `button:has-text(\"Login\")`."
- **Which concrete patient exercises the no-data/error path, and at what URL?** §6 names a patient (see Wrong/stale) but gives no patient key/URL; the answer lived only in `demo_patients.md`.
  *Suggested edit (§6):* replace the no-data row with "Jane Will — zero observations, validation-blocked error pane — key `53e062d0dc5249eb9309cb900754a050` — writes NO", and add a pointer: "Per-patient keys/URLs: `demo_patients.md` (v0.1 fixtures) + `.workspace_state/debug/seeded_patients.json` (P1–P9)."
- **How does `canvas install` actually run in a CPA session?** §3 says "via CPA workflow"; the real mechanism is the `mcp__plugin_cpa_canvas_cmd_line__installer` MCP tool with `plugin_name=growth_charts`, `instance=pxbuilder-aomrani`, `cwd=<extensions dir>`.
  *Suggested edit (§3, step 2):* spell out the installer tool name and its three arguments, and note that the plugin uploads under the manifest name (`cardiometabolic_tracker`) despite the folder being `growth_charts`.
- **Does the platform offer any native print/export capability?** Not mentioned; answered from SDK source + docs.canvasmedical.com (`GenerateFullChartPDFEffect`: whole-chart, async, task-bound).
  *Suggested edit (§5, new row):* "Native PDF export | `GenerateFullChartPDFEffect` renders the ENTIRE native chart async to a task (~10 min) and creates EHR artifacts — not usable for plugin-view export; plugin views use the browser print pipeline (`window.print()` works inside `about:srcdoc`, verified v0.3.0)."
- **Is there a runtime source for the plugin version?** Not covered; v0.3.0 pairs a `PLUGIN_VERSION` constant with the manifest via a test.
  *Suggested edit (§5, new row):* "Plugin version at runtime | No SDK API; keep `PLUGIN_VERSION` in `growth_charts.py` paired to `CANVAS_MANIFEST.json` by `test_plugin_version_matches_manifest`."

## 3. Wrong or stale (contradicted reality, with corrections)

- **Location of the RUNBOOK itself.** The prompt's path `~/Downloads/RUNBOOK.md` was unreadable (macOS TCC blocks the whole Downloads folder for this CLI). Cost the session a full stop until the file moved to `~/Documents/RUNBOOK.md`. §1's own outstanding item ("move to repo root") is the fix — do it; a cold-start context layer must not live in a TCC-protected folder.
- **"Current version v0.2.1" (§1).** The manifest said 0.2.5 at session start (now 0.3.0); the version-history list stops at v0.2.1 and omits v0.2.2–v0.2.5. Material consequence: the build prompt (written against the RUNBOOK) mandated the v0.2.1 `(SCALE, estimated)` string verbatim, but the shipped v0.2.4+ legend is `(SCALE, ±1 SD)` with a fuller disclosure — a prompt/codebase conflict that needed a user ruling mid-build.
- **"expect 107/107" pytest (§3).** Actual at session start: 137 collected / 0 skipped (now 150). Correction: don't pin a count in §3; say "expect the count asserted by the latest acceptance review" or update on every release.
- **No-data patient "Carol Singh" (§6).** The zero-observation, validation-blocked patient on this instance is **Jane Will** (`53e062d0dc5249eb9309cb900754a050`) per `demo_patients.md`; no Carol Singh reference exists anywhere in the repo or seeded registry.
- **"95/95 browser checks" framing (§1 v0.2.0 entry).** Harmless here, but like the pytest count it drifts every release; counts belong in acceptance reviews, not the RUNBOOK.
- **Stale outstanding item (§1):** "git push to remote (verify — commits may be local-only)" — resolved before this session; local `main` was 0 ahead / 0 behind `canvas-case/main`.

## 4. Verdict

**No.** The RUNBOOK alone could not have completed this build: it correctly
carried the environment, gates, write boundaries, and platform gotchas (every
§5 fact held), but the live-verification path (Playwright harness, `.env`
credentials, patient keys/URLs), the real installer mechanism, and an accurate
current-version/test-count baseline all had to be recovered from the repo —
and its v0.2.1-era version history actively injected one wrong clinical-string
requirement into the build prompt. With the §2.5/§3/§5/§6 edits above, a
cold-start session could plausibly run on RUNBOOK + repo alone.

Sections actually consulted this session: §1, §2.5, §3, §4, §5, §6, §7.
