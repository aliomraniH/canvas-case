---
name: toolbox-review
description: >
  Periodic audit that keeps the debug/test toolbox from going stale. Use when
  the user says "/toolbox-review", "audit the toolbox", "review the tooling",
  or at the start of any session where the "Last reviewed" date at the top of
  extensions/TOOLBOX.md is more than 30 days old (build-discipline users will
  see the stale date at session start — run this skill before proceeding).
  Checks index accuracy, test-suite health, skill drift between repo and
  installed copies, stale environment facts, and retirement candidates, then
  writes a dated review report to extensions/toolbox_reviews/ and refreshes
  the Last-reviewed date.
---

# Toolbox Review

A periodic audit of everything indexed in `extensions/TOOLBOX.md`: the
skills, debug tools, test suites, process docs, and setup artifacts. Its job
is to keep the index truthful, the tests meaningful, and the skill copies in
sync — and to surface what should be retired.

## Cadence and trigger

- **Manual:** `/toolbox-review` at any time.
- **Staleness:** if the "Last reviewed" date in `extensions/TOOLBOX.md` is
  **more than 30 days old**, run this review at the start of the session
  before other work. (build-discipline reads at session start; a stale date
  there is the signal.)

## Scope limits (hard rules)

- **Read-only toward the sandbox EHR.** Tier 0–2 checks only (`canvas list`,
  log peeks, targeted read-only assertions). No FHIR writes, no patient
  seeding, no plugin installs/uninstalls. If a check would require a write,
  record it as a proposed action instead.
- **Never edits the other skills.** `build-discipline`, `debug-capture`, and
  `deploy-report` (installed or in-repo) are out of write scope
  (non-interference rule). Divergence is reported, and repo → install sync is
  performed only by copying the repo source over the install — never the
  reverse, and never an edit to skill content itself.
- **Tests: propose, don't rewrite.** Apply only mechanical changes (path
  fixes, marking dead tests with a skip-reason flag). Any behavioral test
  change — new assertions, changed expectations, consolidation of suites —
  goes into the review report as a proposal for a human-reviewed PR.
- **Never delete without listing first.** Retirement candidates are proposed
  in the review output; actual removal happens in a follow-up PR after a
  human confirms.

## Checklist (run in order)

### 1. Index accuracy

- Every entry in `TOOLBOX.md` still exists at its stated path. Flag moves,
  renames, deletions.
- Every debug/test artifact added since the last review is indexed. Sweep:
  `git log --since=<last review date> --name-status -- '*tools/*' '*tests/*'
  '*skills/*' '*.md'` plus a look at `extensions/.workspace_state/debug/`
  (machine-local additions don't show in git).

### 2. Test health

- Run all pytest suites with the Canvas CLI's interpreter (system `python3`
  silently under-collects):
  `~/.local/share/uv/tools/canvas/bin/python -m pytest extensions/growth_charts/tests/ -q`
- Report composition per build-discipline Gate 4: collected / passed /
  skipped counts per suite. A green count from tests that cannot fail is not
  health.
- Flag: tests pinned to retired features; duplicated coverage across suites;
  suites whose "kept separate" rationale has expired and could be
  consolidated; missing coverage for features shipped since the last review
  (diff shipped versions against suite scopes).

### 3. Skills drift

- Diff each in-repo skill copy against its `~/.claude/skills/` install.
  Expected differences are exactly the placeholder substitutions documented
  in `extensions/skills/README.md` (`<repo>`, `<instance>`,
  `<your-username>`); anything else is drift.
- Drift resolution: sync repo → install (copy the repo source over the
  install), or — if the install carries a change the repo lacks — flag it in
  the report for a human to bring into the repo via PR. Never silently adopt
  install-side edits.
- Check the build-discipline known-facts list against `DEBUG_TOOLING.md`'s
  architectural findings (dual-record rule: both must carry the same facts).
  List facts present in one but not the other.

### 4. Stale environment facts

- Spot-check dated facts in `DEBUG_TOOLING.md` — "Last validated:" headers,
  CLI version notes, patient keys — against the live sandbox at **Tier 0/1
  cost only** (`canvas list`, a single read-only page/log check).
- Correct what a Tier 0/1 check can confirm; mark anything else
  "unverified as of <date>" rather than guessing.

### 5. Retirement candidates

- One-shot tools past their use (e.g. `extensions/cleanup_samuel/` once
  Samuel Alta's data fix is verified), superseded docs, dead session
  artifacts under `extensions/.workspace_state/debug/`.
- Propose removal in the report with the evidence; never delete in the same
  change.

### 6. Output

- Write `extensions/toolbox_reviews/<YYYY-MM-DD>_review.md` with sections:
  **what was checked** (commands run, paths verified), **what changed since
  last review**, **what was flagged**, and **proposed adds/removals** grouped
  by category (skills / debug tools / tests / docs / setup).
- Update the "Last reviewed" date in `extensions/TOOLBOX.md`.
- Commit the report + the TOOLBOX.md date bump (and any mechanical fixes from
  the checklist) as one PR-able change.
