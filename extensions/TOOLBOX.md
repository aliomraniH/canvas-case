# Debug/Test Toolbox — Master Index

> **Maintenance:** This index is reviewed periodically by the `toolbox-review`
> skill (see `extensions/skills/toolbox-review/SKILL.md`). Last reviewed:
> 2026-06-12. If you add, move, or retire any debug/test tool, skill, or test
> suite, update this index in the same PR — and append environment facts to
> `DEBUG_TOOLING.md` (canonical) per the dual-record rule.

One page that answers: *what debugging/testing tooling exists for the
`cardiometabolic_tracker` work, where does it live, and how do I run it?*

Two rules govern this file:

1. **It links, it does not copy.** [`DEBUG_TOOLING.md`](DEBUG_TOOLING.md) is
   the canonical record for environment facts, the 6-tier complexity ladder,
   credential rules, and the session-folder schema. Copied content drifts;
   every entry here points at the canonical source instead.
2. **Paths are repo-root-relative** unless marked `~` (home directory).
   *Scope* legend: **in-repo** = committed, anyone can use it after clone;
   **machine-local** = exists only on the original dev workstation, not in
   git (loss risk; recreate notes included where applicable).

---

## A. Skills (session lifecycle + capture)

Installed copies live at `~/.claude/skills/<name>/`; shareable source copies
are committed under [`extensions/skills/`](skills/README.md) (sync direction:
**repo → install**, see that README).

| Name | Category | Location | Purpose | How to invoke | Scope | Status |
|---|---|---|---|---|---|---|
| `build-discipline` | session guardrails | `extensions/skills/build-discipline/` (source), `~/.claude/skills/build-discipline/` (installed) | Five gates + known-facts fast path governing any build/verify/test/debug/deploy session. Facts dual-recorded with `DEBUG_TOOLING.md` (canonical). | Read at SESSION START of any build-type session; auto-triggers on "build", "verify", "deploy", handed-over build prompts | in-repo + installed | active |
| `debug-capture` | browser debugging (Tier 3–4) | `extensions/skills/debug-capture/` (source), `~/.claude/skills/debug-capture/` (installed) | Playwright capture with modes: visual, accessibility, performance, console (plugin/host/unknown attribution), network, figma-reference. Emits timestamped session folder: `session.json`, screenshots, network/console logs, visual assertions, core web vitals, `agent-handoff/brief.md` + `test_deploy.sh`. | Auto-triggers on any browser debugging/testing request; mode prompt on start | in-repo + installed | active |
| `deploy-report` | release reporting | `extensions/skills/deploy-report/` (source), `~/.claude/skills/deploy-report/` (installed) | Generates self-contained HTML release report into `extensions/deploy_reports/` (committed, one per version); satisfies build-discipline session-end checklist items 1–2. | Run at DEPLOY CLOSE, after install + live validation + push | in-repo + installed | active |
| `toolbox-review` | toolbox maintenance | `extensions/skills/toolbox-review/` (source), `~/.claude/skills/toolbox-review/` (installed) | Periodic audit: index accuracy, test health, skills drift, stale environment facts, retirement candidates. Output report in `extensions/toolbox_reviews/`. | `/toolbox-review`, or when the "Last reviewed" date above is >30 days old | in-repo + installed | active |

## B. Debug tooling — guides & findings

| Name | Category | Location | Purpose | How to use | Scope | Status |
|---|---|---|---|---|---|---|
| Debug Tooling Guide | master guide (**canonical**) | [`extensions/DEBUG_TOOLING.md`](DEBUG_TOOLING.md) | 6-tier complexity ladder (Tier 0 `canvas list` → Tier 5 new tool), copy-paste one-liners, Canvas architectural findings (server-side SDK data access, `about:srcdoc` sandboxed iframe, API URL structure, FHIR write gotchas, console-noise triage by URL), credential rules, session folder schema, "What not to do" table. | Read the tier guide before picking any debug tool; append new environment facts here first | in-repo | active |
| Debug-skill findings log | tooling meta-audit | [`extensions/growth_charts/debug_skill_findings.md`](growth_charts/debug_skill_findings.md) | Running per-tier evaluation of debug-capture during v0.2–v0.2.5: what was asked, did the tier answer it, friction found and closed. | Append after each debug session that exposes tooling friction | in-repo | active |
| RUNBOOK gap report | onboarding stress test | [`extensions/growth_charts/runbook_gap_report.md`](growth_charts/runbook_gap_report.md) | Cold-start stress test (v0.3.0): which onboarding questions the RUNBOOK answered vs. missed. (The RUNBOOK itself is machine-local at `~/Documents/RUNBOOK.md` — not in git.) | Read before editing the RUNBOOK; repeat the exercise after major workflow changes | in-repo | active |

## C. Standalone tools & scripts

| Name | Category | Location | Purpose | How to run | Scope | Status |
|---|---|---|---|---|---|---|
| `_canvas_api.py` | shared plumbing | `extensions/growth_charts/tools/_canvas_api.py` | `.env` load, OAuth token, HTTP for everything in `tools/`. Exists exactly once; write-safety guards stay in callers. | imported by the other tools, not run directly | in-repo | active |
| ZZTEST patient seeder | test-fixture seeding | `extensions/growth_charts/tools/seed_zztest_patients.py` | Seeds the 9 ZZTEST-GLP1 demo patients (P1–P9) via FHIR. Pre-write guards: writes only to patients created in the same run with ZZTEST-GLP1 family name; aborts run on any guard failure. Writes manifest `seeded_patients.json`. | `python tools/seed_zztest_patients.py [--dry-run]` (needs `extensions/.env`) | in-repo | active |
| Patient rename/annotate | fixture polish | `extensions/growth_charts/tools/rename_and_annotate_patients.py` | One-off: realistic names + scenario chart note for the 9 seeded patients; manifest-driven, read-back guard before every write. | `python tools/rename_and_annotate_patients.py` (after seeding) | in-repo | one-shot (done; keep as guarded-write reference) |
| `cleanup_samuel` plugin | test-data remediation | `extensions/cleanup_samuel/` | One-shot ActionButton entering 5 accidental Samuel Alta weight observations in error via `Observation.enter_in_error()`; hardcoded patient key + 5 UUIDs; uninstall after use. | `canvas install` → click button once → `canvas uninstall` | in-repo (TEMPORARY plugin) | one-shot — **retirement candidate**: not installed on the sandbox as of 2026-06-12 (Tier-0 verified); first toolbox review to confirm remediation and propose removal |
| Tier-2 assertion runner | live validation | `extensions/skills/debug-capture/scripts/tier2_v02_assertions.js` (committed copy); runs machine-local from `extensions/.workspace_state/debug/tools/` | Login-once, per-patient Tier-2 assertions driven by `seeded_patients.json`; non-zero exit on failure. | `node tier2_v02_assertions.js [P1 P2 ...]` (needs `extensions/.env` + Playwright; see scripts README) | in-repo copy + machine-local | active |
| Tier-4 full-session capture | live validation | `extensions/skills/debug-capture/scripts/tier4_v02_full_session.js` (committed copy); runs machine-local | Full-session capture producing schema-conformant artifacts incl. regression fixtures (P1, P8 + read-only regression checks). | `node tier4_v02_full_session.js` | in-repo copy + machine-local | active |
| Lori Collins capture | live capture reference | `extensions/skills/debug-capture/scripts/capture_lori_collins.js` (committed copy); runs machine-local from `extensions/.workspace_state/debug/` | The working Playwright login + capture session script (dotenv credentials); the reference implementation for new capture scripts. | `node capture_lori_collins.js` | in-repo copy + machine-local | active |
| Tier-0 export check | live validation | `extensions/.workspace_state/debug/tools/tier0_v03_export.js` | v0.3 export smoke check (added since the 2026-06-12 inventory). | `node tier0_v03_export.js` | machine-local | active |
| v0.2.3 popover capture | live capture | `extensions/.workspace_state/debug/tools/capture_v023_popover.js` | Targeted popover capture for the v0.2.3 fix (added since the 2026-06-12 inventory). | `node capture_v023_popover.js` | machine-local | one-shot |
| Workspace launcher | workstation setup | `~/launch_workspace.sh` | Two-panel Claude Code workspace setup (CLI + Desktop, Chrome connector, shared state). `--check` verifies without launching. | `bash ~/launch_workspace.sh [--check\|--reset]` | machine-local — personal-workstation orchestration (hardcoded local paths, Chrome port); to recreate: see header comments, it checks PATH, Canvas CLI, Chrome debug port 9222, and shared `state.json` | active |
| Workspace test harness | workstation setup | `~/run_tests.sh` | 27 automated checks across environment, Canvas CLI, Chrome, shared state, CPA, cross-panel sync. | `bash ~/run_tests.sh [--quick\|--chrome]` | machine-local — same reasons as the launcher | active |
| Seeded-patient manifest | fixture manifest | `extensions/.workspace_state/debug/seeded_patients.json` | Patient keys/names for P1–P9; drives the Tier-2 runner. | regenerate any time by re-running the seeder (it writes the manifest) | machine-local (gitignored) | active |

## D. Test suites (pytest, in-repo, mocked at the SDK boundary)

Run all suites (system `python3` silently under-collects — always use the
Canvas CLI's interpreter):

```bash
cd extensions/growth_charts
~/.local/share/uv/tools/canvas/bin/python -m pytest tests/ -q
```

| Suite | Size | Purpose | Status |
|---|---|---|---|
| [`tests/test_cardiometabolic.py`](growth_charts/tests/test_cardiometabolic.py) | 58 tests / 14 classes | v0.1 baseline. Internal tiers: unit → mocked-SDK integration → clinical validation vs published data → edge/error. Runs in CI with no Canvas credentials. | active |
| [`tests/test_v02_enhancements.py`](growth_charts/tests/test_v02_enhancements.py) | 79 tests / 15 classes | v0.2: E1 milestones, E2 expected band + agent detection, E3 velocity/flags, same-day dedup, `TestNoStrayConversionLiterals` (single `KG_PER_LB` constant), `TestGate1ReferenceConcordance` (code == reference == primary citation). Kept separate so v0.1 stays byte-untouched. | active |
| [`tests/test_v03_export.py`](growth_charts/tests/test_v03_export.py) | 13 tests / 7 classes | v0.3: print-summary stats block, milestone-status derivation, disclosure survival in PDF, button visibility, version pairing. | active |
| [`tests/test_v04_event_log.py`](growth_charts/tests/test_v04_event_log.py) | 29 tests / 9 classes | v0.4: event-log panel hardening (R1 local export date, R2 error-path escaping), support-report export schema + origin taxonomy, de-clinicalized copy scan, read-only weight-data table. *(Added since the 2026-06-12 inventory.)* | active |

**Cross-suite principle:** mocked tests cannot catch SDK field-name drift or
Canvas runtime behavior — live tiered validation (per the
[`DEBUG_TOOLING.md`](DEBUG_TOOLING.md) ladder) is always the second gate.
Mock-green alone is never "done"; mock-green **plus** live-smoke-green is.

## E. Test/QA process docs

| Name | Category | Location | Purpose | Scope | Status |
|---|---|---|---|---|---|
| Test plan | gate orchestration | [`extensions/growth_charts/test_plan.md`](growth_charts/test_plan.md) | Maps TC-01–TC-10 → pytest → Chrome connector checks → bash greps, in P0→P1→P2 order. Gate order: static checks → pytest → browser (post-deploy only). | in-repo | active |
| Browser test protocol | post-deploy standing order | [`extensions/growth_charts/browser_test_protocol.md`](growth_charts/browser_test_protocol.md) | Chrome connector verification protocol; auto-triggers on "deployed"; Tier-0 pre-check first. | in-repo | active |
| Test report v0.1.3 | execution record | [`extensions/growth_charts/test_report.md`](growth_charts/test_report.md) | v0.1.3 execution report (environment, methods, results). | in-repo | one-shot (historical record) |
| Assumptions & rationale | decision record | [`extensions/growth_charts/assumptions_tests_rationale.md`](growth_charts/assumptions_tests_rationale.md) | Ties tests to clinical/design rationale (percent-TBWL unit invariance, single conversion constant, SCALE ±1 SD band). | in-repo | active |
| Acceptance reviews | independent verification | [`v02`](growth_charts/v02_acceptance_review.md) · [`v025`](growth_charts/v025_acceptance_review.md) · [`v030`](growth_charts/v030_acceptance_review.md) · [`v040`](growth_charts/v040_acceptance_review.md) | Read-only, independent, per-version reviews; re-derive every checkable claim; record verdict + v-next findings. (v040 added since the 2026-06-12 inventory.) | in-repo | active (one file per version) |

## F. Setup & configuration

| Name | Category | Location | Purpose | Scope | Status |
|---|---|---|---|---|---|
| Credential template | secrets discipline | [`extensions/.env.example`](.env.example) | Committed template; real values only in the gitignored `extensions/.env`. Never paste values from `.env` or `~/.canvas/credentials.ini` into any artifact — see [`DEBUG_TOOLING.md`](DEBUG_TOOLING.md) § Credential management (canonical). | in-repo | active |
| Secrets gitignore | secrets discipline | `extensions/.gitignore` | Keeps `.env`, `.env.*`, `*.env` out of git (plus debug-session screenshots/node_modules). Repo-root `.gitignore` additionally excludes all of `**/.workspace_state/`. | in-repo | active |
| Deploy reports | release history | [`extensions/deploy_reports/`](deploy_reports/README.md) | Committed release-history trail emitted by the deploy-report skill — README + 5 HTML reports, v0.2.3 → v0.4.0 (v0.4.0 added since the 2026-06-12 inventory). | in-repo | active |
| Review reports | toolbox audit trail | `extensions/toolbox_reviews/` | Output directory for `toolbox-review` runs: one `<YYYY-MM-DD>_review.md` per audit. | in-repo | active |

---

## Drift flagged at first indexing (vs. the 2026-06-12 inventory)

- The inventory wrote `.workspace_state/...` paths repo-root-relative; the
  directory actually lives at `extensions/.workspace_state/` (gitignored via
  repo-root `.gitignore` `**/.workspace_state/`). Paths above are corrected.
- Added since the inventory was compiled: `tests/test_v04_event_log.py`,
  `v040_acceptance_review.md`, deploy report `v0.4.0_2026-06-12.html`,
  `tier0_v03_export.js`, `capture_v023_popover.js`.
- `cleanup_samuel` is no longer installed on the sandbox (Tier-0 check,
  2026-06-12) — repo copy flagged as a retirement candidate above.

---

## Purpose summary

- **Debugging** (find why): the [`DEBUG_TOOLING.md`](DEBUG_TOOLING.md) tier
  ladder picks the cheapest answering tool; debug-capture is the heavy
  artifact-producing session; the findings log and RUNBOOK gap report are
  meta-tools that audit the tooling itself and feed fixes back.
- **Testing** (prove right): the pytest suites are the fast credential-free
  gate; `test_plan.md` + `browser_test_protocol.md` orchestrate the
  static → pytest → live order; the seeding tools produce guarded fixtures;
  `cleanup_samuel` remediates bad test data on a sandbox where FHIR writes
  are permanent.
- **Setup** (reproducible & safe): `.env` discipline keeps secrets out of
  artifacts; build-discipline and deploy-report bookend every session with
  gates and a committed report.
