# Claude Code skills — shareable source copies

These are the Claude Code skills used to build, debug, test, and ship the
`cardiometabolic_tracker` plugin. They originally lived only in
`~/.claude/skills/` on one workstation; the copies here are the **shareable
source** so the team can read them, review changes to them in PRs, and
install them on any machine.

| Skill | Lifecycle | What it does |
|---|---|---|
| [`build-discipline`](build-discipline/SKILL.md) | read at SESSION START of any build/verify/test/debug/deploy session | Five gates + known-facts fast path that govern the session. Facts dual-recorded with [`../DEBUG_TOOLING.md`](../DEBUG_TOOLING.md) (canonical). |
| [`debug-capture`](debug-capture/SKILL.md) | Tier 3–4 browser debugging | Playwright capture sessions (visual / accessibility / performance / console / network / figma-reference) with structured, agent-readable artifacts. |
| [`deploy-report`](deploy-report/SKILL.md) | run at DEPLOY CLOSE | Self-contained HTML release report into `../deploy_reports/`. |
| [`toolbox-review`](toolbox-review/SKILL.md) | `/toolbox-review`, or when `../TOOLBOX.md`'s "Last reviewed" date is >30 days old | Periodic audit of the toolbox index, test suites, skill drift, and stale environment facts. |

## Installing

Copy a skill directory into your local Claude Code skills folder:

```bash
cp -R extensions/skills/build-discipline ~/.claude/skills/
cp -R extensions/skills/debug-capture   ~/.claude/skills/
cp -R extensions/skills/deploy-report   ~/.claude/skills/
cp -R extensions/skills/toolbox-review  ~/.claude/skills/
```

## Sync direction: repo → install

The repo copy is the source of truth. Edit skills **here**, in a PR, then
re-copy to `~/.claude/skills/`. Never edit the installed copy directly — the
`toolbox-review` skill diffs installed copies against these sources and flags
divergence.

Two intentional differences between repo copies and a working install:

- **Placeholders.** Repo copies use `<repo>` (absolute path to your clone),
  `<instance>` (your Canvas instance name), and `<your-username>` instead of
  personal absolute paths. A working install may substitute real local
  values; the drift check ignores exactly these substitutions and nothing
  else.
- **No credentials, ever.** Real values live only in the gitignored
  `extensions/.env` (template: `extensions/.env.example`). If a skill edit
  would embed a hostname-with-secret, credential, or personal path, fix the
  edit, not the scan.

## `debug-capture/scripts/` — committed Playwright reference scripts

`tier2_v02_assertions.js`, `tier4_v02_full_session.js`, and
`capture_lori_collins.js` are working live-validation scripts, committed here
so they survive the original workstation. On that machine they run from
`extensions/.workspace_state/debug/` (gitignored), where Playwright
(`node_modules/`) and the seeded-patient manifest live.

To run a committed copy on a fresh machine:

1. `cd extensions/.workspace_state/debug && npm i playwright` (first time only)
2. Copy the script into `extensions/.workspace_state/debug/tools/`
3. Populate `extensions/.env` from `.env.example`
4. For the Tier-2 runner: generate `seeded_patients.json` by running
   `extensions/growth_charts/tools/seed_zztest_patients.py`

Paths inside the scripts resolve relative to their committed location
(`../../../.env` etc.) and can be overridden with `CANVAS_ENV_FILE`,
`DEBUG_BASE_DIR`, and `SEEDED_MANIFEST` environment variables — set those
when running from a different directory.

Machine-local scripts **not** committed (too workstation-specific):
`~/launch_workspace.sh` and `~/run_tests.sh` (personal two-panel workspace
orchestration) and the one-shot capture scripts under
`extensions/.workspace_state/debug/tools/`. See
[`../TOOLBOX.md`](../TOOLBOX.md) for the full inventory with recreate notes.
