# PROMPT — Build & publish the Debug/Test Toolbox documentation

> Paste everything below this line into a Claude Code **Desktop** session opened in
> `~/Documents/Canvas-case/canvas` (the machine that has `~/.claude/skills/` installed).
> The Desktop machine is required because three skills and several scripts referenced
> here are machine-local and not in git.

---

## Mission

Turn the complete inventory below (compiled 2026-06-12 from my commits of the last
10 days, `2019aa1`..`21b6b38`) into a structured, public, in-repo documentation set,
publish it to GitHub so the whole team can read it, and install + commit a **new
periodic-review skill** that keeps the docs, tests, and skills from going stale.

Work on a fresh branch off the default branch (suggested name:
`docs/toolbox-index`). Commit with clear messages and push with
`git push -u origin <branch>`. Open a PR at the end so the team can read and review
it — title: "docs: debug/test toolbox index + maintenance skill".

## Hard rules

1. **No credentials anywhere.** Reference `extensions/.env` / `.env.example` only.
   Never paste values from `.env` or `~/.canvas/credentials.ini` into any artifact.
2. **Non-interference rule holds:** do NOT modify `~/.claude/skills/debug-capture/`,
   `build-discipline/`, or `deploy-report/`. The new review skill is a NEW skill.
3. **No duplication of canonical records.** `extensions/DEBUG_TOOLING.md` stays the
   canonical record for environment facts and the tier guide. The new index LINKS to
   it (and to the other docs); it does not copy their content. Copied content drifts.
4. Follow repo conventions in `CLAUDE.md` / `REVIEW.md`.

---

## Deliverable 1 — `extensions/TOOLBOX.md` (master index)

A single structured index of every debugging/testing tool, skill, instruction doc,
and setup artifact. For each entry: **name · category · location · purpose · how to
run/invoke · scope (in-repo vs machine-local) · status (active / one-shot / stale)**.

Use the inventory below as the content source. Verify each path still exists before
listing it; flag anything that moved.

### Inventory (verified 2026-06-12)

#### A. Skills (machine-local, `~/.claude/skills/` — see Deliverable 2)

| Skill | Lifecycle | Purpose |
|---|---|---|
| `build-discipline` | Read at SESSION START of any build/verify/test/debug/deploy session | Five gates + known-facts fast path that govern the session. Facts dual-recorded with `DEBUG_TOOLING.md` (canonical). |
| `debug-capture` | Tier 3–4 browser debugging | Playwright capture with modes: visual, accessibility, performance, console (with plugin/host/unknown attribution), network, figma-reference. Emits timestamped session folder: `session.json`, screenshots, network/console logs, visual assertions, core web vitals, `agent-handoff/brief.md` + `test_deploy.sh`. |
| `deploy-report` | Run at DEPLOY CLOSE | Generates self-contained HTML release report into `extensions/deploy_reports/` (committed, one per version); satisfies build-discipline session-end checklist items 1–2. |

#### B. Debug tooling — guides & findings (in-repo)

| File | Purpose |
|---|---|
| `extensions/DEBUG_TOOLING.md` | Master guide: 6-tier complexity ladder (Tier 0 `canvas list` → Tier 5 new tool), copy-paste one-liners, Canvas architectural findings (server-side SDK data access, `about:srcdoc` sandboxed iframe, API URL structure, FHIR write gotchas, console-noise triage by URL), credential rules, session folder schema, "What not to do" table. |
| `extensions/growth_charts/debug_skill_findings.md` | Running per-tier evaluation log of debug-capture during v0.2–v0.2.5: what was asked, did the tier answer it, friction found and closed. |
| `extensions/growth_charts/runbook_gap_report.md` | RUNBOOK cold-start stress test (v0.3.0): which onboarding questions the RUNBOOK answered vs. missed. |

#### C. Standalone tools & scripts

| Tool | Scope | Purpose |
|---|---|---|
| `extensions/growth_charts/tools/_canvas_api.py` | in-repo | Shared plumbing for tools/: `.env` load, OAuth token, HTTP. Exists exactly once; write-safety guards stay in callers. |
| `extensions/growth_charts/tools/seed_zztest_patients.py` | in-repo | Seeds the 9 ZZTEST-GLP1 demo patients (P1–P9) via FHIR. Pre-write guards: only patients created in the same run with ZZTEST-GLP1 family name; aborts run on any guard failure. `--dry-run` supported. Writes manifest `seeded_patients.json`. |
| `extensions/growth_charts/tools/rename_and_annotate_patients.py` | in-repo | One-off: realistic names + scenario chart note for the 9 seeded patients; manifest-driven, read-back guard before every write. |
| `extensions/cleanup_samuel/` | in-repo, TEMPORARY plugin | One-shot ActionButton entering 5 accidental Samuel Alta weight observations in error via `Observation.enter_in_error()`; hardcoded patient key + 5 UUIDs; uninstall after use. |
| `.workspace_state/debug/tools/tier2_v02_assertions.js` | machine-local | Login-once per-patient Tier-2 assertion runner driven by `seeded_patients.json`; non-zero exit on failure. |
| `.workspace_state/debug/tools/tier4_v02_full_session.js` | machine-local | Full-session capture producing schema-conformant artifacts incl. regression fixtures. |
| `.workspace_state/debug/capture_lori_collins.js` | machine-local | Working Playwright login + capture session script (dotenv credentials). |
| `~/launch_workspace.sh` (+ `--check`), `~/run_tests.sh` | machine-local | Two-panel workspace launcher / verify; 27 automated checks. |

#### D. Test suites (pytest, in-repo, mocked at the SDK boundary)

| Suite | Size | Purpose |
|---|---|---|
| `extensions/growth_charts/tests/test_cardiometabolic.py` | 58 tests / 14 classes | v0.1 baseline. Internal tiers: unit → mocked-SDK integration → clinical validation vs published data → edge/error. Runs in CI with no Canvas credentials. |
| `extensions/growth_charts/tests/test_v02_enhancements.py` | 79 tests / 15 classes | v0.2: E1 milestones, E2 expected band + agent detection, E3 velocity/flags, same-day dedup, `TestNoStrayConversionLiterals` (single `KG_PER_LB` constant), `TestGate1ReferenceConcordance` (code == reference == primary citation). Kept separate so v0.1 stays byte-untouched. |
| `extensions/growth_charts/tests/test_v03_export.py` | 13 tests / 7 classes | v0.3: print-summary stats block, milestone-status derivation, disclosure survival in PDF, button visibility, version pairing. |

Cross-suite principle to state in TOOLBOX.md: **mocked tests cannot catch SDK
field-name drift or Canvas runtime behavior — live tiered validation is always the
second gate.**

#### E. Test/QA process docs (in-repo)

| File | Purpose |
|---|---|
| `extensions/growth_charts/test_plan.md` | Maps TC-01–TC-10 → pytest → Chrome connector checks → bash greps, in P0→P1→P2 order. Gate order: static checks → pytest → browser (post-deploy only). |
| `extensions/growth_charts/browser_test_protocol.md` | Chrome connector standing order for post-deploy verification; auto-triggers on "deployed"; Tier-0 pre-check first. |
| `extensions/growth_charts/test_report.md` | v0.1.3 execution report (environment, methods, results). |
| `extensions/growth_charts/assumptions_tests_rationale.md` | Decision record tying tests to clinical/design rationale (percent-TBWL unit invariance, single conversion constant, SCALE ±1 SD band). |
| `extensions/growth_charts/v02_acceptance_review.md`, `v025_…`, `v030_…` | Independent read-only acceptance reviews per version; re-derive every checkable claim; record verdict + v-next findings. |

#### F. Setup & configuration

| File | Purpose |
|---|---|
| `extensions/.env.example` | Committed credential template; real values only in gitignored `.env`. |
| `extensions/.gitignore` | Keeps `.env`, `.env.*`, `*.env` out of git. |
| `extensions/deploy_reports/` (README + 4 HTML, v0.2.3–v0.3.0) | Committed release-history trail emitted by the deploy-report skill. |

### Required closing section of TOOLBOX.md — "Purpose summary"

- **Debugging** (find why): tier ladder picks the cheapest answering tool;
  debug-capture is the heavy artifact-producing session; findings/gap-report docs
  are meta-tools that audit the tooling itself and feed fixes back.
- **Testing** (prove right): pytest suites are the fast credential-free gate;
  test_plan + browser_test_protocol orchestrate the static → pytest → live order;
  seeding tools produce guarded fixtures; cleanup_samuel remediates bad test data
  on a sandbox where FHIR writes are permanent.
- **Setup** (reproducible & safe): `.env` discipline keeps secrets out of artifacts;
  build-discipline and deploy-report bookend every session with gates and a
  committed report.

### Required maintenance note (verbatim, at the top of TOOLBOX.md)

> **Maintenance:** This index is reviewed periodically by the `toolbox-review`
> skill (see `extensions/skills/toolbox-review/SKILL.md`). Last reviewed:
> <date>. If you add, move, or retire any debug/test tool, skill, or test
> suite, update this index in the same PR — and append environment facts to
> `DEBUG_TOOLING.md` (canonical) per the dual-record rule.

---

## Deliverable 2 — publish the machine-local skills in-repo

The three skills exist only in `~/.claude/skills/` and would be lost with the
machine. Copy their definitions into the repo so everyone can read and install them:

```
extensions/skills/
├── README.md                      ← what these are, how to install to ~/.claude/skills/
├── build-discipline/   (SKILL.md + any references/)
├── debug-capture/      (SKILL.md + references/: session-schema.md,
│                         mode-playbooks.md, agent-handoff.md, figma-integration.md)
└── deploy-report/      (SKILL.md + any references/)
```

Before committing: scan every copied file for credentials, hostnames-with-secrets,
or personal absolute paths (`/Users/aliomrani/...`) and genericize them. The
in-repo copy is the shareable source; `~/.claude/skills/` remains the installed
copy. State in the README which direction syncs (repo → install).

Also evaluate committing the machine-local scripts from inventory section C
(`tier2_v02_assertions.js`, `tier4_v02_full_session.js`, `capture_lori_collins.js`,
`launch_workspace.sh`, `run_tests.sh`) under `extensions/growth_charts/tools/` or
`extensions/skills/debug-capture/scripts/` — same credential scan first. If any is
too machine-specific to commit, list it in TOOLBOX.md as machine-local with a note
on how to recreate it.

---

## Deliverable 3 — NEW skill: `toolbox-review` (periodic audit)

Create it in BOTH places: install at `~/.claude/skills/toolbox-review/` and commit
at `extensions/skills/toolbox-review/`. This is a new skill, not a modification of
debug-capture (non-interference rule).

**Trigger:** invoked manually (`/toolbox-review`) or at the start of any session
where the last-reviewed date in `TOOLBOX.md` is **more than 30 days old** —
build-discipline users will see the stale date at session start.

**The skill's checklist:**

1. **Index accuracy** — every entry in `TOOLBOX.md` still exists at its path; every
   debug/test artifact added since the last review is indexed (sweep `git log
   --since=<last review>` for tools/, tests/, skills/, *.md additions).
2. **Test health** — run all three pytest suites; report pass/skip counts. Flag:
   tests pinned to retired features, duplicated coverage across suites, suites
   whose "kept separate" rationale has expired and could be consolidated, and
   missing coverage for features shipped since the last review.
3. **Skills drift** — diff in-repo skill copies vs `~/.claude/skills/` installs;
   sync repo → install or flag divergence. Check skill known-facts lists against
   `DEBUG_TOOLING.md` (dual-record rule: both must carry the same facts).
4. **Stale environment facts** — spot-check dated facts in `DEBUG_TOOLING.md`
   ("Last validated:" header, CLI version notes, patient keys) against the live
   sandbox at Tier 0/1 cost only; correct or mark unverified.
5. **Retirement candidates** — one-shot tools past their use (e.g.
   `cleanup_samuel` once Samuel Alta's data is fixed and verified), superseded
   docs, dead session artifacts. Propose removal; never delete without listing in
   the review output first.
6. **Output** — write `extensions/toolbox_reviews/<YYYY-MM-DD>_review.md` with:
   what was checked, what changed, what was flagged, proposed adds/removals per
   category (skills / debug tools / tests / docs / setup). Update the
   "Last reviewed" date in `TOOLBOX.md`. Commit both in one PR-able change.

**Skill scope limits (state in SKILL.md):** read-only toward the sandbox EHR
(Tier 0–2 only, no writes, no seeding); never edits the other skills; proposes
test changes but applies only mechanical ones (path fixes, dead-test flags) —
behavioral test changes go to a human-reviewed PR.

---

## Deliverable 4 — wire-up notes

1. Add one line to `extensions/DEBUG_TOOLING.md` "Installed tools" section:
   `toolbox-review` skill — periodic audit of TOOLBOX.md, tests, and skills;
   output in `extensions/toolbox_reviews/`. (This is an additive doc edit, allowed.)
2. Add a short "Toolbox" pointer near the top of `extensions/growth_charts/README.md`
   linking to `extensions/TOOLBOX.md`.
3. Run the full pytest suites once before pushing; include counts in the PR body.
4. Push the branch and open the PR. PR body: what TOOLBOX.md is, why skills are now
   committed in-repo, what toolbox-review does and its 30-day cadence.

## Acceptance checklist (verify before declaring done)

- [ ] `extensions/TOOLBOX.md` exists, all paths verified, maintenance note + purpose summary present
- [ ] Three existing skills committed under `extensions/skills/`, credential-scanned
- [ ] `toolbox-review` skill installed locally AND committed, with cadence + checklist + scope limits
- [ ] First review stub or "Last reviewed: <today>" recorded
- [ ] DEBUG_TOOLING.md and growth_charts README pointers added
- [ ] No secrets or personal paths in any committed file (`git grep` for usernames, `aliomrani`, password-like strings)
- [ ] Pytest suites green; counts recorded in PR body
- [ ] Branch pushed, PR opened
