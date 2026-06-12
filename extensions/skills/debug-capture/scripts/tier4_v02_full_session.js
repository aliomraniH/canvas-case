// Tier 4 — full debug-capture session, cardiometabolic_tracker v0.2.0
// pre-submission run. Targets: P1 (Responder, semaglutide-detected) and
// P8 (MixedUnits edge). Same authenticated run also performs the read-only
// regression checks (Lori Collins, Samuel Alta, Jane Will) — NO writes.
//
// Modes: network + console registered before navigation, then visual,
// accessibility (aria snapshot), performance per page. Screenshots local
// only — Figma upload removed from v0.2 scope.
//
// Usage: node tier4_v02_full_session.js

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ENV_FILE = process.env.CANVAS_ENV_FILE || path.resolve(__dirname, '..', '..', '..', '.env');
const env = {};
fs.readFileSync(ENV_FILE, 'utf8').split('\n').filter(l => l && !l.startsWith('#')).forEach(l => {
  const [k, ...v] = l.split('=');
  if (k) env[k.trim()] = v.join('=').trim();
});
const HOST = env.CANVAS_HOST.replace(/^https?:\/\//, '').replace(/\/$/, '');
const BASE_URL = 'https://' + HOST;

const DEBUG_BASE = process.env.DEBUG_BASE_DIR || path.resolve(__dirname, '..', '..', '..', '.workspace_state', 'debug');
const SEEDED = JSON.parse(fs.readFileSync(path.join(DEBUG_BASE, 'seeded_patients.json'), 'utf8'));

const SESSION_ID = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19) + 'Z_full_v02_presubmission';
const SESSION_DIR = path.join(DEBUG_BASE, SESSION_ID);
['screenshots', 'api-calls', 'snapshots', 'performance', 'agent-handoff'].forEach(d =>
  fs.mkdirSync(path.join(SESSION_DIR, d), { recursive: true }));
console.log('Session:', SESSION_ID);

const TIER4_TARGETS = [
  { key: 'P1', ...SEEDED.patients.P1, expect: 'chart' },
  { key: 'P8', ...SEEDED.patients.P8, expect: 'chart' },
];
const REGRESSION = [
  { key: 'LORI', name: 'Lori Collins (v0.1 fixture, read-only)', expect: 'chart',
    chart_url: `${BASE_URL}/patient/0af123e5cc74483095399463fff6f002` },
  { key: 'SAMUEL', name: 'Samuel Alta (contaminated, read-only)', expect: 'error_pane',
    chart_url: `${BASE_URL}/patient/41fb2a51a18d4948afb9d874a7a2adcb` },
  { key: 'JANE', name: 'Jane Will (zero observations, read-only)', expect: 'error_pane',
    chart_url: `${BASE_URL}/patient/53e062d0dc5249eb9309cb900754a050` },
];

const apiLog = [];
const consoleLog = [];
let currentPhase = 'init';
let ssIdx = 0;

async function screenshot(page, label) {
  ssIdx++;
  const fname = `${String(ssIdx).padStart(3, '0')}_${label}.png`;
  await page.screenshot({ path: path.join(SESSION_DIR, 'screenshots', fname) });
  return `screenshots/${fname}`;
}

async function findPluginFrame(page) {
  for (let attempt = 0; attempt < 20; attempt++) {
    for (const frame of page.frames()) {
      try {
        if (await frame.locator('#cm-container').count() > 0) return { frame, frame_url: frame.url() };
        const body = await frame.locator('body').textContent({ timeout: 300 }).catch(() => '');
        if (body && body.includes('Unable to render weight trajectory'))
          return { frame, frame_url: frame.url(), error_pane: true };
      } catch { }
    }
    await page.waitForTimeout(500);
  }
  return null;
}

async function inspectChart(frame) {
  return frame.evaluate(() => {
    const svg = document.querySelector('#cm-chart svg');
    let layerData = {};
    try {
      layerData = {
        milestones: (typeof MilestoneLayer !== 'undefined' && MilestoneLayer._data) || [],
        band_label: ((typeof ExpectedBandLayer !== 'undefined' && ExpectedBandLayer._data) || {}).label || null,
        band_point_count: (((typeof ExpectedBandLayer !== 'undefined' && ExpectedBandLayer._data) || {}).points || []).length,
        datapoint_values: ((typeof DataPointLayer !== 'undefined' && DataPointLayer._data) || []).map(d => +d.value_lbs),
        velocity_display: (((typeof StatsBar !== 'undefined' && StatsBar._data) || {}).velocity_stats || {}).display || null,
        flags: (((typeof StatsBar !== 'undefined' && StatsBar._data) || {}).flags || []).map(f => f.key),
      };
    } catch (e) { layerData = { error: String(e) }; }
    return {
      svg_present: !!svg,
      circles: svg ? svg.querySelectorAll('.cm-layer-series circle').length : 0,
      dashed_lines: svg ? svg.querySelectorAll('line[stroke-dasharray]').length : 0,
      band_fill_present: !!(svg && svg.querySelector('.cm-layer-band path.cm-band-fill')),
      legend_text: (document.getElementById('cm-legend-text') || {}).textContent || null,
      badges: [...document.querySelectorAll('.cm-badge')].map(b => b.getAttribute('data-flag')),
      data_note: (() => { const n = document.getElementById('cm-data-note');
        return n && n.style.display !== 'none' ? n.textContent : null; })(),
      layer_data: layerData,
    };
  });
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });

  // ── network capture: registered BEFORE any navigation, all frames ──
  for (const matcher of [
    url => url.hostname === HOST && url.pathname.startsWith('/api/'),
    url => url.hostname === HOST && url.pathname === '/graphql',
  ]) {
    await context.route(matcher, async (route, request) => {
      const t0 = Date.now();
      let response;
      try { response = await route.fetch(); } catch (e) {
        apiLog.push({ id: `api_${String(apiLog.length).padStart(3, '0')}`, phase: currentPhase,
          timestamp: new Date().toISOString(), method: request.method(), url: request.url(),
          status: null, duration_ms: Date.now() - t0, error: e.message, tags: ['canvas_api'] });
        return route.abort();
      }
      let body = null;
      try { body = await response.text(); } catch { }
      const u = request.url();
      apiLog.push({
        id: `api_${String(apiLog.length).padStart(3, '0')}`, phase: currentPhase,
        timestamp: new Date().toISOString(), method: request.method(), url: u,
        status: response.status(), duration_ms: Date.now() - t0,
        request_body: request.postData() ? request.postData().substring(0, 2000) : null,
        response_body: body ? body.substring(0, 8000) : null,
        response_body_truncated: !!(body && body.length > 8000),
        tags: ['canvas_api', u.includes('graphql') ? 'graphql' : 'rest'],
      });
      await route.fulfill({ response });
    });
  }

  const page = await context.newPage();
  page.on('console', m => consoleLog.push({
    id: `con_${String(consoleLog.length).padStart(3, '0')}`, phase: currentPhase,
    timestamp: new Date().toISOString(), level: m.type(), message: m.text().substring(0, 500),
    source: m.location() && m.location().url ? `${m.location().url}:${m.location().lineNumber}` : null,
  }));
  page.on('pageerror', e => consoleLog.push({
    id: `con_${String(consoleLog.length).padStart(3, '0')}`, phase: currentPhase,
    timestamp: new Date().toISOString(), level: 'unhandled_error',
    message: e.message, stack_trace: e.stack || null,
  }));

  // ── login ──
  currentPhase = 'login';
  console.log('\n[login]');
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
  await page.fill('input[type="text"], input[name="username"]', env.CANVAS_USERNAME);
  await page.fill('input[type="password"]', env.CANVAS_PASSWORD);
  await page.click('button[type="submit"], button:has-text("Login")');
  try { await page.waitForURL(u => !String(u).includes('/login'), { timeout: 15000 }); } catch {}
  await page.waitForLoadState('networkidle').catch(() => {});

  const results = { passed: 0, failed: 0, warnings: 0, errors: [], patients: {} };
  function record(patient, name, ok, detail) {
    results.patients[patient].checks.push({ check: name, ok: !!ok, detail: detail || null });
    ok ? results.passed++ : (results.failed++, results.errors.push(`[${patient}] ${name}: ${detail || 'failed'}`));
    console.log(`    ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
  }

  for (const target of [...TIER4_TARGETS, ...REGRESSION]) {
    const { key, name, chart_url, expect } = target;
    currentPhase = `${key}_chart_load`;
    console.log(`\n[${key}] ${name}`);
    results.patients[key] = { name, chart_url, expect, checks: [], artifacts: {} };
    const r = results.patients[key];

    await page.goto(chart_url, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(2500);
    r.artifacts.chart_screenshot = await screenshot(page, `${key}_chart`);

    // performance snapshot of the chart page load
    r.performance = await page.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0] || {};
      return {
        ttfb_ms: Math.round(nav.responseStart || 0),
        dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
        load_event_ms: Math.round(nav.loadEventEnd || 0),
        resource_count: performance.getEntriesByType('resource').length,
      };
    });

    currentPhase = `${key}_plugin_trigger`;
    const btn = page.locator('button:has-text("Weight Trajectory")').first();
    if (await btn.count() === 0) { record(key, 'Weight Trajectory button present', false, 'not found'); continue; }
    record(key, 'Weight Trajectory button present', true);
    const apiCountBefore = apiLog.length;
    await btn.scrollIntoViewIfNeeded().catch(() => {});
    await btn.click();

    const found = await findPluginFrame(page);
    await page.waitForTimeout(1500);
    r.artifacts.pane_screenshot = await screenshot(page, `${key}_pane`);

    // The only browser-visible plugin signal: a GraphQL POST for the render.
    const renderCalls = apiLog.slice(apiCountBefore).filter(c => c.tags.includes('graphql') && c.method === 'POST');
    record(key, 'GraphQL render POST observed', renderCalls.length > 0, `${renderCalls.length} call(s)`);

    if (expect === 'error_pane') {
      record(key, 'validation blocks rendering (error pane)', !!(found && found.error_pane),
        found ? (found.error_pane ? 'error pane shown' : 'CHART RENDERED UNEXPECTEDLY') : 'no frame found');
      continue;
    }

    if (!found || found.error_pane) {
      record(key, 'chart renders', false, found ? 'error pane' : 'frame not found');
      continue;
    }
    record(key, 'chart renders', true, found.frame_url);

    const state = await inspectChart(found.frame);
    r.visual_state = state;
    record(key, 'svg + datapoints present', state.svg_present && state.circles > 0, `circles=${state.circles}`);
    record(key, 'velocity stat present', !!state.layer_data.velocity_display, state.layer_data.velocity_display);
    record(key, 'expected band rendered', state.band_fill_present, state.legend_text);

    if (key === 'P1') {
      record(key, 'STEP-1 legend (agent detected)', (state.legend_text || '').includes('STEP-1'), state.legend_text);
      record(key, '5%+10% milestones crossed',
        state.layer_data.milestones.filter(m => m.crossed).map(m => m.pct).join(',') === '5,10');
      record(key, 'no flags on responder', state.badges.length === 0, JSON.stringify(state.badges));
    }
    if (key === 'P8') {
      const vals = state.layer_data.datapoint_values;
      record(key, 'mixed units normalized to one range', vals.every(v => v > 200 && v < 235),
        JSON.stringify(vals.map(v => +v.toFixed(1))));
    }
    if (key === 'LORI') {
      record(key, 'v0.2 overlays on v0.1 fixture data',
        state.band_fill_present && !!state.layer_data.velocity_display,
        `band=${state.band_fill_present} velocity=${state.layer_data.velocity_display}`);
    }

    // accessibility snapshot of the plugin pane
    try {
      const aria = await found.frame.locator('#cm-container').ariaSnapshot();
      const fname = `snapshots/${key}_aria_snapshot.yaml`;
      fs.writeFileSync(path.join(SESSION_DIR, fname), aria);
      r.artifacts.aria_snapshot = fname;
      record(key, 'aria snapshot captured', aria.length > 0, `${aria.length} chars`);
    } catch (e) {
      results.warnings++;
      console.log(`    WARN  aria snapshot failed: ${String(e).substring(0, 120)}`);
    }
  }

  currentPhase = 'teardown';
  fs.writeFileSync(path.join(SESSION_DIR, 'api-calls', 'network_log.json'), JSON.stringify({
    schema_version: '1.0', session_id: SESSION_ID, requests: apiLog }, null, 2));
  fs.writeFileSync(path.join(SESSION_DIR, 'api-calls', 'console_log.json'), JSON.stringify({
    schema_version: '1.0', session_id: SESSION_ID, entries: consoleLog }, null, 2));
  fs.writeFileSync(path.join(SESSION_DIR, 'performance', 'page_timings.json'), JSON.stringify(
    Object.fromEntries(Object.entries(results.patients).map(([k, v]) => [k, v.performance || null])), null, 2));

  const session = {
    schema_version: '1.0',
    session_id: SESSION_ID,
    mode: ['network', 'console', 'visual', 'accessibility', 'performance'],
    metadata: {
      created_at: new Date().toISOString(), ended_at: new Date().toISOString(),
      duration_seconds: Math.round(process.uptime()), tool: 'debug-capture-skill',
      claude_surface: 'cli', operator: process.env.USER || 'unknown',
    },
    context: {
      project: 'cardiometabolic_tracker', plugin_version: '0.2.0',
      target_url: BASE_URL, canvas_host: HOST.split('.')[0],
      patient_name: 'ZZTEST-GLP1 P1+P8 / regression: Lori Collins, Samuel Alta, Jane Will',
      patient_key: null,
      test_description: 'v0.2.0 pre-submission Tier 4: full capture on P1+P8, read-only regression on v0.1 fixtures',
      git_branch: 'main', git_commit: 'cd507c1',
    },
    results: {
      passed: results.passed, failed: results.failed, warnings: results.warnings,
      errors: results.errors, summary: null, patients: results.patients,
    },
    artifacts: {
      screenshots: fs.readdirSync(path.join(SESSION_DIR, 'screenshots')).map(f => `screenshots/${f}`),
      network_log: 'api-calls/network_log.json',
      console_log: 'api-calls/console_log.json',
      accessibility_tree: fs.readdirSync(path.join(SESSION_DIR, 'snapshots')).map(f => `snapshots/${f}`),
      performance: 'performance/page_timings.json',
      figma_diff: null,
    },
    figma: { upload_file_key: null, upload_file_url: null, reference_file_key: null,
      reference_file_name: null, reference_node_id: null, reference_node_name: null,
      diff_report: null, note: 'Figma removed from v0.2 scope — screenshots local only' },
    agent_handoff: {
      brief: 'agent-handoff/brief.md',
      deploy_script: 'agent-handoff/test_deploy.sh',
      rerun_command: `node ${DEBUG_BASE}/tools/tier4_v02_full_session.js`,
      suggested_actions: [], ready_for_agent: true,
    },
  };
  session.results.summary =
    `${results.passed}/${results.passed + results.failed} checks passed across P1, P8 and 3 regression patients`;
  fs.writeFileSync(path.join(SESSION_DIR, 'session.json'), JSON.stringify(session, null, 2));

  console.log(`\n=== ${results.passed} passed / ${results.failed} failed / ${results.warnings} warnings ===`);
  results.errors.forEach(e => console.log('  ' + e));
  console.log('Session dir:', SESSION_DIR);
  await browser.close();
  process.exit(results.failed ? 1 : 0);
})();
