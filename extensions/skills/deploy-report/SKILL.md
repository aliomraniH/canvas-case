---
name: deploy-report
description: Generate a polished, self-contained HTML deployment report artifact at the end of every plugin deployment. Always use this skill after a successful `canvas install` + live validation pass, when a version ships, or whenever the user says "deployment report", "highlights artifact", "release summary", "wrap up this deploy", or finishes a build session — even if they don't explicitly ask for a report. The output is a single shareable HTML file (embedded screenshots, no external requests) saved to deploy_reports/, covering highlights, bugs found, observations, and future-version considerations.
---

# Deploy Report

Produces one self-contained HTML artifact per deployment that tells the story
of the release: what shipped, what it looks like, what broke and was fixed,
what was learned, and what's queued for the next version.

## When to run

At the end of every deployment, after:
1. Tests are green and the version is deployed + enabled (Tier 0 confirmed)
2. Live validation has completed (whatever tiers were used)
3. Final commits are pushed

Run it as the last step before closing the session. If the user ends a deploy
session without one, offer to generate it. Generating this report satisfies
items 1–2 of the build-discipline session-end checklist (test composition
reported + push verified) — do not duplicate that work separately.

## Output contract

**Location:** `extensions/deploy_reports/v<version>_<YYYY-MM-DD>.html`
(this folder is committed and shareable — NOT inside the gitignored
`.workspace_state/`). Create the folder if missing.

**Format:** ONE self-contained HTML file:
- All CSS inline in a `<style>` block; no external fonts, scripts, or requests
  of any kind (the file must render identically offline and when emailed)
- Screenshots embedded as base64 `data:` URIs
- Renders correctly in any modern browser with no server

## Required sections (in order)

1. **Header strip** — plugin name, version, deploy date, commit hashes,
   target instance, and badge-style stats (e.g. `107/107 pytest`,
   `95/95 browser`, `Tier 3: not needed`). Per build-discipline Gate 4,
   the pytest badge must show suite composition, not just the pass count:
   `107 collected · 0 skipped · 103 mocked · 4 live` — a green number from a
   suite that cannot fail is not a stat worth reporting.
2. **Highlights** — what shipped, one short paragraph or 3–6 bullets, written
   for a reader who didn't follow the build (e.g. Kristen). Lead with the
   clinical/user-facing value, not the file names.
3. **Screenshots** — 3–6 images with one-line captions, pulled from the most
   recent debug-capture session's `screenshots/` folder. Choose the images
   that show the new features, not login screens. Downscale to ≤1200px wide
   before embedding to keep the file portable (target <8 MB total).
4. **Bugs found & fixed** — anything discovered during the build or live
   validation, with the fix. Include schema/platform quirks (these are often
   the most valuable content).
5. **Observations & architectural findings** — facts learned about the
   platform or tooling that change how future work should be done.
6. **Future version considerations** — the v-next backlog: deferred features,
   design questions raised by this release, and data gaps.
7. **Tooling & skill notes** — friction or wins from the debug/test harness
   worth feeding back into the skill playbooks.

## Sources to read (in this order)

- `git log` since the previous report (or since the last version tag)
- The latest `*_full*/agent-handoff/brief.md` and `session.json` under
  `.workspace_state/debug/`
- `debug_skill_findings.md`
- `assumptions_tests_rationale.md` (decisions + deferrals feed sections 5–6)
- Pytest summary from the final green run

Read these; do not regenerate or modify them. This skill is **read-only**
toward debug-capture artifacts (non-interference rule) — it consumes the
session folder, never writes into it.

## Hard rules

- **No credentials, ever.** Before writing the file, scan the assembled HTML
  for the strings `password`, `client_secret`, `CANVAS_PASSWORD`, and any
  value loaded from `.env`. Any hit → remove and re-scan before saving.
- **No PHI-style content beyond ZZTEST patients.** Screenshots showing real-ish
  seeded patients (e.g. Lori Collins) are fine in this sandbox, but never
  include patient lists beyond what the captioned feature requires.
- **No external requests in the HTML.** No CDN links, no Google Fonts, no
  analytics. System font stack only.
- **One file per deploy.** Re-running for the same version overwrites the
  same filename (idempotent), it does not accumulate near-duplicates.

## Style

Clean single-column document, max-width ~860px, generous whitespace, a muted
professional palette with one accent color, system font stack
(`-apple-system, Segoe UI, Roboto, sans-serif`). Badges as small rounded
pills. Captions small and muted. Section anchors so the file is linkable.
The bar: someone should be able to attach this file to an email to a hiring
manager with zero edits.

## After generating

1. Save the file, confirm it opens (file size + a grep for `data:image` count
   as a sanity check).
2. Commit it with message `docs: deploy report v<version>`.
3. Print the absolute path and a one-line summary of what was included.
