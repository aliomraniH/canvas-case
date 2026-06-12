---
name: build-discipline
description: Pre-flight and in-flight guardrails that prevent the five failure modes observed in this project's session transcripts - unverified environment assumptions, mock-green false confidence, write-boundary violations, building against a moving spec, and over-development. ALWAYS read this skill at the start of any build, verification, test-authoring, debugging, or deploy session for the Canvas plugin or any agentic coding task - even if the user does not mention it. Also trigger when the user says "build", "implement the spec", "write tests", "verify", "deploy", "fix this bug", "create test scenarios", or hands over a build prompt from another session. Re-read the Stop-Loss and Edit Discipline sections whenever you notice repeated edits to the same file or repeated failures of the same action.
---

# Build Discipline

Guardrails distilled from real incidents in this project's session transcripts.
Every rule below exists because its absence cost a deploy cycle, an irreversible
data write, or a 27-edit churn loop. The rules are ordered by when they apply:
before writing code, while writing code, and when things go wrong.

## The incident registry (why each rule exists)

| Incident | Cost | Rule it created |
|---|---|---|
| `obs.unit` vs `obs.units`, `id__in` vs `dbid__in` — field names guessed, and one was encoded as a "hard constraint" in the orchestration prompt itself | v0.1.3 patch cycle; silent prod failure behind green mocks | Gate 1 |
| Deploy sub-agent restructured flat package layout, unprompted | v0.1.1 failed deploy + diagnose + redeploy | Gate 2 |
| 5 observations written to real patient Samuel Alta; FHIR writes are permanent | Irreversible sandbox contamination | Gate 2 |
| 4 sequential reversal attempts (DELETE, PUT, PATCH, enter_in_error) on a provably immutable resource | Burned tokens on an unwinnable problem | Stop-Loss |
| `test_v02_verification.py` edited 27x, `oracle.py` 13x — verification suite written while the spec was still changing | ~40 re-sync edits, two full rewrites of browser_checks.js and acceptance_matrix.md | Gate 3 |
| 58-test suite where 55 were guaranteed skips, re-run repeatedly as a "gate" | False confidence + wasted output every run | Gate 4 |
| "File has not been read yet", "modified since read", "string not found", sed/chmod on nonexistent files (7 occurrences across 3 sessions) | Failed-edit retry chains | Edit Discipline |
| Shadow verification stack (oracle.py + seed_audit.py + 30K browser_checks.js written twice) duplicating existing pytest + Tier-2 coverage; Figma-reference mode built then deleted | Largest single token sink in the project | Gate 5 |

---

## GATE 1 — Environment truth before code

Never write code against an API/SDK field name, method, URL pattern, or schema
that you have not verified **this session** against one of:

1. The SDK source on disk (preferred — it cannot be stale):
   `SDK=$HOME/.local/share/uv/tools/canvas/lib/python3.13/site-packages/canvas_sdk` then `grep` the model definition.
2. Official docs at `docs.canvasmedical.com` (note the URL you checked).
3. A previous **live** observation recorded in DEBUG_TOOLING.md's
   "Canvas-specific architectural findings" or the known-facts list below.

**Prompts are not a verification source.** A build prompt, spec, or addendum
may state field names confidently and still be wrong (`id__in` was a "hard
constraint" in an approved prompt and was incorrect). If the prompt asserts an
environment fact you haven't verified, verify it anyway — one grep costs less
than one deploy cycle. If verification contradicts the prompt, stop and report
the contradiction; do not silently pick one.

**Known verified facts for this project** (re-verify only if the SDK version
changes from 0.163.1):
- `obs.units` (plural), never `obs.unit`
- `Note.objects.filter(dbid__in=...)`, never `id__in`
- Weight Observation unit string is `lb` exactly, never `lbs`
- `from __future__ import annotations` required in every module (RestrictedPython blocks `object` in annotations)
- No subscript access on underscore-prefixed keys — use `.get()` throughout
- Flat package layout, no intermediate folder nesting; manifest class path prefix must match plugin name
- Patient creation requires the `us-core-birthsex` extension
- FHIR writes are permanent: DELETE, PUT, PATCH, `enter_in_error()` all blocked
- FHIR-created MedicationStatements surface in the SDK `Medication` model: `Medication.objects.for_patient(id).active()` (verified live, v0.2)
- LaunchModalEffect target does not change iframe context: DEFAULT_MODAL and RIGHT_CHART_PANE_LARGE both render in `about:srcdoc`; Tier 1/2 selectors stay valid across target switches
- `window.print()` works inside the `about:srcdoc` iframe and prints only the iframe document (verified live, v0.3.0); Playwright `emulateMedia({media:'print'})` reaches iframes
- Native PDF: `GenerateFullChartPDFEffect` = whole native chart, async to a task, creates EHR artifacts — never usable for plugin-view export
- `Patient.first_name` / `Patient.last_name` exist on the SDK model (canvas_sdk/v1/data/patient.py)
- Canvas login submit selector is `button:has-text("Login")`; host S3 background image fails intermittently — attribute console errors by URL before asserting
- No-data validation-blocked patient on this instance is Jane Will `53e062d0dc5249eb9309cb900754a050` (RUNBOOK's "Carol Singh" is stale)
- Blob + anchor downloads work inside the `about:srcdoc` iframe (verified live, v0.4.0); Playwright catches them via `waitForEvent('download')` + `acceptDownloads: true`
- `Observation` (SDK 0.163.1) has NO `method`/`device` field — only `patient, is_member_of, category, units, value, note_id, name, effective_datetime` + audit/id base fields (canvas_sdk/v1/data/observation.py; Gate 2 v0.4.0)

## GATE 2 — Write boundaries (hard rules, no judgment calls)

- **Patient data:** write ONLY to patients whose given name starts with
  `ZZTEST`. No exception for "searching for a candidate", demo convenience, or
  user urgency. If no suitable ZZTEST patient exists, create one — never
  repurpose a real patient. Run the pre-write guard in the seeding script; if
  the guard is missing from a new script, add it before the first write.
- **Role boundaries:** if this session's role is reviewer/validator/debugger,
  you are read-only toward the plugin source and the EHR. Findings go into a
  brief or prompt for the builder session — you do not "quickly fix" things.
- **Structure boundaries:** never restructure package layout, rename folders,
  or move files unless the task explicitly says to. Sub-agents inherit this:
  include "do not restructure the package layout" in every deploy/sub-agent
  delegation.
- **Destructive or irreversible actions** (FHIR POST to non-ZZTEST resources,
  force-push, file deletion outside the plan, anything the registry marks
  permanent): name the action and its irreversibility to the user and wait for
  confirmation. One sentence is enough; silence is not consent.

## GATE 3 — Spec freeze before derived artifacts

Test suites, oracles, seed scripts, acceptance matrices, and verification
packs are **derived artifacts** — they encode the spec. Writing them against a
spec that is still moving guarantees churn (27 edits to one test file).

- Do not author derived artifacts until the spec is approved AND the build they
  verify has reached a pinned reference (a commit hash, a deployed version
  number, or an explicit "frozen" from the user). Record the pin at the top of
  the artifact: `# Verifies: v0.2 @ 7a98dda`.
- If the spec changes after you've started (an addendum arrives, patients are
  renamed): **stop and diff first.** List which derived artifacts are
  invalidated and how, give the user the count, and prefer one regeneration
  over incremental re-sync edits when more than ~5 edits would be needed.
- Never edit a file while a process that reads it is still running. Wait for
  the run to finish or kill it first.
- Baseline snapshots are only meaningful **before** the change they baseline.
  If that window has passed, say so and skip the snapshot — do not produce one
  anyway "for completeness."

## GATE 4 — A gate must measure reality

A test gate only counts if it can actually fail for the failure class it
guards. Before declaring any suite a deploy gate, report its composition:
`X collected / Y skipped / Z mocked / W live`. If the runtime-relevant tests
are all skipped or mocked, say explicitly: "this gate does not cover Canvas
runtime behavior" — and require **one live smoke check** (deploy to sandbox,
render one ZZTEST patient chart, confirm no console/plugin errors) before
calling anything done. Mock-green + live-smoke-green is the definition of
done; mock-green alone is not.

Do not re-run a suite whose outcome is already known and unchanged (e.g., 55
guaranteed skips) as a ritual. Re-run only what the latest change could have
affected; run the full suite once at the end.

## GATE 5 — Over-development check (run before creating anything new)

Before writing any new file, script, mode, or tool, answer in one line each:

1. **Consumer:** who/what reads this output, this week? If the answer is
   "a future agent might", it fails the check — note the idea in the backlog
   instead.
2. **Duplication:** does pytest, the Tier-2 browser assertions, debug-capture,
   deploy-report, or an existing script already cover this? Partial overlap
   counts — extend the existing thing rather than building a shadow version.
   (The oracle/
   seed_audit/browser_checks stack duplicated existing coverage and was the
   project's largest token sink.)
3. **Smallest version:** what is the 20% that delivers the value? Build only
   that. Modes, options, and schemas multiply maintenance — the six-mode
   debug skill's Figma mode was built and then deleted without ever running.
4. **Sized to the change:** a one-field patch needs a one-assertion check,
   not a new framework.

If the user explicitly asks for the larger version after seeing the small one,
build it — the gate guards defaults, not requests.

## Edit Discipline (mechanical rules)

- **Read before every edit.** Never edit a file you haven't read this session;
  re-read after any external process (linter, test run, another session) may
  have touched it. ("File has not been read yet" and "modified since read"
  both occurred in these transcripts.)
- **Verify existence before acting on paths**: `ls` before `chmod`/`sed`/`node`
  on files another process was supposed to create. Check you are in the
  directory you think you are in — two `sed: No such file` errors came from
  wrong cwd.
- **Three-edit rule:** if you have made 3 consecutive edits to the same file
  for the same logical change, stop patching — re-read the whole file and
  rewrite the affected section (or file) in one operation.
- **Batch permission-heavy work.** If a task will need many small approvals,
  propose the batch up front (one plan, one approval) instead of triggering
  line-by-line permission prompts.

## Stop-Loss (when things fail)

- **Two-strike rule for the same action:** the same command/edit/request
  failing twice with the same error class means the approach is wrong, not
  unlucky. Stop, state the hypothesis for why it fails, and change approach or
  ask.
- **Irreversibility probe:** before attempting to undo anything, check the
  incident registry / known facts. If the resource class is known-immutable,
  make at most ONE probe to confirm, then report "irreversible, here is the
  containment plan" — never iterate through reversal methods (four were
  attempted on Samuel Alta against a documented-permanent store).
- **Contradiction between prompt and environment:** report it; do not
  reconcile silently in either direction.
- **When interrupted by the user mid-tool-call:** treat it as a signal the
  plan drifted. Restate the current plan in 2 lines and confirm before
  resuming — do not simply continue.

## Session-end checklist (60 seconds, every session)

1. Tests: final composition reported (collected/skipped/mocked/live) + one
   live smoke if anything deployed.
2. If a version shipped: run the **deploy-report** skill (its header badges
   must carry the composition from item 1). A deploy session is not closed
   without its report unless the user explicitly skips it.
3. Git: committed AND pushed (an unpushed-commits gap survived a full
   submission in this project). `git status` + `git log origin/main..HEAD`
   must both be clean/empty or explained.
4. New environment facts discovered this session appended to
   DEBUG_TOOLING.md's "Canvas-specific architectural findings" (canonical,
   in-repo) and to this skill's Gate 1 known-facts list so the next session
   does not rediscover them.
5. Anything built but not consumed → flag to the user as candidate for
   deletion, not silent retention.
