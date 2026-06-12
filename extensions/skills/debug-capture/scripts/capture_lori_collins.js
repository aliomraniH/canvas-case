// Full debug capture — Lori Collins chart + cardiometabolic tracker modal
// Reads credentials from extensions/.env
// Usage: node capture_lori_collins.js

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// ── Config ────────────────────────────────────────────────────────────────
const ENV_FILE = process.env.CANVAS_ENV_FILE || path.resolve(__dirname, '..', '..', '..', '.env');
const env = {};
fs.readFileSync(ENV_FILE, 'utf8').split('\n').filter(l => l && !l.startsWith('#')).forEach(l => {
  const [k, ...v] = l.split('=');
  if (k) env[k.trim()] = v.join('=').trim();
});

const BASE_URL  = 'https://' + env.CANVAS_HOST;
const SESSION_ID = new Date().toISOString().replace(/[:.]/g, '').substring(0, 15) + 'Z_lori_collins_cardiometabolic';
const SESSION_DIR = path.join(__dirname, SESSION_ID);

['screenshots', 'api-calls', 'snapshots', 'performance', 'agent-handoff'].forEach(d =>
  fs.mkdirSync(path.join(SESSION_DIR, d), { recursive: true }));

console.log('Session:', SESSION_ID);
console.log('Dir:', SESSION_DIR);

// ── Helpers ───────────────────────────────────────────────────────────────
let ssIdx = 0;
async function screenshot(page, label) {
  ssIdx++;
  const fname = `${String(ssIdx).padStart(3, '0')}_${label}.png`;
  const fpath = path.join(SESSION_DIR, 'screenshots', fname);
  await page.screenshot({ path: fpath, fullPage: false });
  console.log(`  Screenshot ${fname}`);
  return `screenshots/${fname}`;
}

async function fullScreenshot(page, label) {
  ssIdx++;
  const fname = `${String(ssIdx).padStart(3, '0')}_${label}.png`;
  const fpath = path.join(SESSION_DIR, 'screenshots', fname);
  await page.screenshot({ path: fpath, fullPage: true });
  console.log(`  Screenshot ${fname}`);
  return `screenshots/${fname}`;
}

// ── Network capture state ─────────────────────────────────────────────────
// fhirLog: filled by context.route() — catches ALL frames including about:srcdoc
// allRequests: filled by context.on('request') — non-FHIR summary counts
const fhirLog    = [];
const allRequests = [];

let currentPhase = 'login';

function tagUrl(url) {
  const tags = ['canvas_api'];
  if (url.includes('Observation'))        tags.push('observation');
  if (url.includes('Patient'))            tags.push('patient');
  if (url.includes('Condition'))          tags.push('condition');
  if (url.includes('Medication'))         tags.push('medication');
  if (url.includes('MedicationRequest'))  tags.push('medication_request');
  if (url.includes('AllergyIntolerance')) tags.push('allergy');
  if (url.includes('DiagnosticReport'))   tags.push('diagnostic_report');
  if (url.includes('Immunization'))       tags.push('immunization');
  if (url.includes('Immunization'))       tags.push('immunization');
  if (url.includes('Interview'))          tags.push('interview');
  if (url.includes('NoteMetadata'))       tags.push('note');
  if (url.includes('FamilyHistory'))      tags.push('family_history');
  if (url.includes('InpatientStay'))      tags.push('inpatient');
  if (url.includes('graphql'))            tags.push('graphql');
  return tags;
}

// ── Main ──────────────────────────────────────────────────────────────────
async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page    = await context.newPage();

  // ── FHIR interception via context.route() ─────────────────────────────────
  // Must be registered before any navigation. Intercepts ALL frames (main,
  // iframes, about:srcdoc) at the Playwright proxy layer — not patchable by JS.
  // Canvas uses /api/<Resource>/ (Django REST), not /api/r4/ (FHIR R4)
  // Use URL predicate so we only intercept the Canvas host, not third-party /api/ calls
  await context.route(
    url => url.hostname === env.CANVAS_HOST && url.pathname.startsWith('/api/'),
    async (route, request) => {
    const t0 = Date.now();
    let response;
    try {
      response = await route.fetch();
    } catch (e) {
      fhirLog.push({
        id: `fhir_${String(fhirLog.length).padStart(3, '0')}`,
        phase: currentPhase,
        timestamp: new Date().toISOString(),
        method: request.method(),
        url: request.url(),
        status: null,
        duration_ms: Date.now() - t0,
        request_body: request.postData() || null,
        response_body: null,
        error: e.message,
        tags: tagUrl(request.url()),
      });
      return route.abort();
    }

    let body = null;
    try { body = await response.text(); } catch {}

    fhirLog.push({
      id: `fhir_${String(fhirLog.length).padStart(3, '0')}`,
      phase: currentPhase,
      timestamp: new Date().toISOString(),
      method: request.method(),
      url: request.url(),
      status: response.status(),
      duration_ms: Date.now() - t0,
      request_body: request.postData() || null,
      response_body: body ? body.substring(0, 8000) : null,
      response_body_truncated: body ? body.length > 8000 : false,
      error: null,
      tags: tagUrl(request.url()),
    });

    await route.fulfill({ response });
  });

  // Also intercept /graphql on the Canvas host only
  await context.route(
    url => url.hostname === env.CANVAS_HOST && url.pathname === '/graphql',
    async (route, request) => {
    const t0 = Date.now();
    let response;
    try { response = await route.fetch(); } catch (e) {
      fhirLog.push({ id: `api_${String(fhirLog.length).padStart(3, '0')}`, phase: currentPhase,
        timestamp: new Date().toISOString(), method: request.method(), url: request.url(),
        status: null, duration_ms: Date.now() - t0, request_body: request.postData() || null,
        response_body: null, error: e.message, tags: ['canvas_api', 'graphql'] });
      return route.abort();
    }
    let body = null;
    try { body = await response.text(); } catch {}
    fhirLog.push({ id: `api_${String(fhirLog.length).padStart(3, '0')}`, phase: currentPhase,
      timestamp: new Date().toISOString(), method: request.method(), url: request.url(),
      status: response.status(), duration_ms: Date.now() - t0,
      request_body: request.postData() || null,
      response_body: body ? body.substring(0, 8000) : null,
      response_body_truncated: body ? body.length > 8000 : false,
      error: null, tags: ['canvas_api', 'graphql'] });
    await route.fulfill({ response });
  });

  // ── Non-API event listener — other requests summary ────────────────────────
  context.on('request', req => {
    const url = req.url();
    if (!url.includes('/api/') && !url.includes('/graphql') && !url.includes('/fhir/')) {
      allRequests.push({
        timestamp: new Date().toISOString(),
        phase: currentPhase,
        method: req.method(),
        url,
        resource_type: req.resourceType(),
        status: null,
      });
    }
  });
  context.on('response', res => {
    const e = allRequests.find(r => r.url === res.url() && r.status === null);
    if (e) e.status = res.status();
  });
  context.on('requestfailed', req => {
    const e = allRequests.find(r => r.url === req.url() && r.status === null);
    if (e) e.error = req.failure()?.errorText || 'failed';
  });

  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push({
    id: `con_${String(consoleLogs.length).padStart(3, '0')}`,
    timestamp: new Date().toISOString(),
    level: msg.type(),
    message: msg.text(),
    source: msg.location()?.url ? `${msg.location().url}:${msg.location().lineNumber}` : null,
  }));
  page.on('pageerror', e => consoleLogs.push({
    id: `con_${String(consoleLogs.length).padStart(3, '0')}`,
    timestamp: new Date().toISOString(),
    level: 'unhandled_error',
    message: e.message,
    stack_trace: e.stack || null,
  }));

  // ── Step 1: Login ─────────────────────────────────────────────────────
  console.log('\n[1] Logging in as', env.CANVAS_USERNAME);
  currentPhase = 'login';
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
  await page.fill('input[type="text"], input[name="username"]', env.CANVAS_USERNAME);
  await page.fill('input[type="password"]', env.CANVAS_PASSWORD);
  await page.click('button[type="submit"], button:has-text("Login")');
  try { await page.waitForURL(u => !String(u).includes('/login'), { timeout: 15000 }); } catch {}
  await page.waitForLoadState('networkidle').catch(() => {});
  console.log('  Landed:', page.url());

  // ── Step 2: Find Lori Collins ─────────────────────────────────────────
  console.log('\n[2] Searching for Lori Collins');
  currentPhase = 'patient_search';
  await page.goto(`${BASE_URL}/patients`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await screenshot(page, 'patients_list');

  // Try search box
  const searchSel = 'input[placeholder*="Search"], input[type="search"], input[name="q"], input[aria-label*="search" i], input[aria-label*="patient" i]';
  const searchBox = page.locator(searchSel).first();
  if (await searchBox.count() > 0) {
    await searchBox.fill('Lori Collins');
    await page.waitForTimeout(1500);
    await page.waitForLoadState('networkidle').catch(() => {});
    await screenshot(page, 'search_lori_collins');
  }

  // Extract Lori Collins' chart href directly and navigate to it
  const loriHref = await page.evaluate(() => {
    const anchors = [...document.querySelectorAll('a')];
    const match = anchors.find(a => a.textContent.includes('Lori Collins') || a.textContent.includes('Collins'));
    return match ? match.href : null;
  });
  console.log('  Lori Collins href:', loriHref);

  if (loriHref) {
    await page.goto(loriHref, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
  } else {
    // Fallback: click and wait for URL change
    const patientLink = page.getByText('Lori Collins', { exact: false }).first();
    if (await patientLink.count() > 0) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {}),
        patientLink.click(),
      ]);
    } else {
      console.log('  WARNING: Could not find Lori Collins');
    }
  }

  await page.waitForTimeout(2000);
  const patientUrl = page.url();
  console.log('  Patient URL:', patientUrl);

  // ── Step 3: Navigate to chart and capture FHIR on load ────────────────
  console.log('\n[3] Loading patient chart — capturing FHIR calls');
  currentPhase = 'chart_load';

  // If we're not on the chart yet, look for a Chart tab link
  if (!patientUrl.includes('/chart')) {
    const chartLink = page.locator('a:has-text("Chart"), a[href*="chart"], [role="tab"]:has-text("Chart")').first();
    if (await chartLink.count() > 0) {
      const chartHref = await chartLink.getAttribute('href');
      console.log('  Navigating to chart tab:', chartHref);
      if (chartHref) {
        await page.goto(BASE_URL + chartHref, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
      } else {
        await chartLink.click();
        await page.waitForLoadState('networkidle').catch(() => {});
      }
    }
  }

  await page.waitForTimeout(4000);
  const chartUrl = page.url();
  console.log('  Chart URL:', chartUrl);
  await screenshot(page, 'chart_loaded');
  await fullScreenshot(page, 'chart_full');

  const chartFhir = fhirLog.filter(r => r.phase === 'chart_load');
  console.log(`  FHIR calls during chart load: ${chartFhir.length}`);
  chartFhir.forEach(r => console.log(`    ${r.method} ${r.url.substring(0, 100)} → ${r.status}`));

  // ── Step 4: Find and click cardiometabolic tracker in Vital Signs ──────
  console.log('\n[4] Looking for cardiometabolic tracker button');
  currentPhase = 'plugin_trigger';

  // Look for "Vital Signs" section first
  const vitalSection = page.getByText('Vital Signs', { exact: false }).first();
  if (await vitalSection.count() > 0) {
    console.log('  Found Vital Signs section');
    await vitalSection.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
  }

  // Scroll down to find Vital Signs section
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('*')].find(e => e.textContent.trim() === 'Vital Signs' || e.textContent.includes('Vital Signs'));
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  await page.waitForTimeout(1000);

  // Screenshot to see current chart state before button search
  await screenshot(page, 'chart_vital_signs_area');

  // Look for the cardiometabolic tracker button (various possible names)
  const btnSelectors = [
    'button:has-text("Cardiometabolic")',
    'button:has-text("cardiometabolic")',
    'button:has-text("Tracker")',
    '[data-testid*="cardiometabolic"]',
    '[data-key*="cardiometabolic"]',
    'button:has-text("Weight Tracker")',
    'button:has-text("Weight")',
    'button:has-text("BMI")',
    'button:has-text("TBWL")',
    'button:has-text("View Chart")',
    'button:has-text("chart")',
  ];

  let trackerBtn = null;
  let trackerBtnText = null;
  for (const sel of btnSelectors) {
    const btn = page.locator(sel).first();
    if (await btn.count() > 0) {
      trackerBtnText = await btn.textContent();
      console.log(`  Found button: "${trackerBtnText?.trim()}" via selector: ${sel}`);
      trackerBtn = btn;
      break;
    }
  }

  // If not found, log all visible buttons to help debug
  if (!trackerBtn) {
    console.log('  Cardiometabolic button not found. Visible buttons:');
    const allBtns = await page.evaluate(() =>
      [...document.querySelectorAll('button,[role="button"]')]
        .filter(b => b.offsetParent !== null)
        .map(b => b.textContent?.trim().substring(0, 60))
        .filter(t => t)
    );
    allBtns.forEach(t => console.log('   -', t));
  }

  let modalScreenshot = null;
  let visualAssertions = null;
  const pluginFhirBefore = fhirLog.length;

  if (trackerBtn) {
    console.log('  Clicking tracker button...');
    await trackerBtn.click();
    await page.waitForTimeout(4000); // wait for modal + FHIR calls
    await page.waitForLoadState('networkidle').catch(() => {});

    // Screenshot of modal
    modalScreenshot = await screenshot(page, 'cardiometabolic_modal');
    await fullScreenshot(page, 'cardiometabolic_modal_full');
    console.log('  Modal screenshot taken');

    // FHIR calls triggered by button click
    const pluginFhir = fhirLog.filter(r => r.phase === 'plugin_trigger');
    console.log(`  FHIR calls from button click: ${pluginFhir.length}`);
    pluginFhir.forEach(r => console.log(`    ${r.method} ${r.url.substring(0, 120)} → ${r.status}`));

    // ── Step 5: evaluate_script visual assertions (search all frames) ────
    console.log('\n[5] Running visual assertions across all frames');

    // Wait up to 5s for circles to appear in any frame
    let frameWithChart = null;
    for (let attempt = 0; attempt < 10; attempt++) {
      for (const frame of page.frames()) {
        try {
          const hasCircles = await frame.evaluate(() =>
            document.querySelectorAll('svg circle, circle').length > 0
          ).catch(() => false);
          if (hasCircles) { frameWithChart = frame; break; }
        } catch {}
      }
      if (frameWithChart) break;
      await page.waitForTimeout(500);
    }

    const targetFrame = frameWithChart || page.mainFrame();
    console.log('  Chart frame URL:', targetFrame.url());

    visualAssertions = await targetFrame.evaluate(() => {
      const svgEls       = [...document.querySelectorAll('svg')];
      const svgPresent   = svgEls.length > 0;
      const circles      = [...document.querySelectorAll('svg circle, circle')];
      const dashedLines  = [...document.querySelectorAll(
        'line[stroke-dasharray], path[stroke-dasharray], [stroke-dasharray]'
      )];
      const allText = [
        ...document.querySelectorAll('svg text, tspan, text')
      ].map(t => t.textContent?.trim()).filter(Boolean);
      const bodyText    = document.body?.innerText || '';
      const tbwlText    = allText.find(t => t.includes('TBWL')) ||
                          (bodyText.includes('TBWL') ? bodyText.match(/[\d.]+%\s*TBWL[^\n]*/)?.[0] : null);
      const pctText     = allText.find(t => /\d+(\.\d+)?%/.test(t));
      const modalEl     = document.querySelector('[role="dialog"], .modal, [class*="modal"]');
      const errorEl     = document.querySelector('[data-error], .error-message');

      const circleDetails = circles.slice(0, 10).map(c => ({
        cx: c.getAttribute('cx'), cy: c.getAttribute('cy'),
        r: c.getAttribute('r'), fill: c.getAttribute('fill') || c.style.fill,
        stroke: c.getAttribute('stroke') || c.style.stroke,
      }));
      const lineDetails = dashedLines.slice(0, 5).map(l => ({
        tag: l.tagName,
        dasharray: l.getAttribute('stroke-dasharray'),
        stroke: l.getAttribute('stroke') || l.style.stroke,
      }));

      return {
        ASSERT_svg_present:        svgPresent,
        ASSERT_circles_gt_0:       circles.length > 0,
        ASSERT_dashed_line_exists: dashedLines.length > 0,
        ASSERT_tbwl_visible:       !!tbwlText,
        circle_count:      circles.length,
        dashed_line_count: dashedLines.length,
        svg_count:         svgEls.length,
        tbwl_text:         tbwlText || null,
        pct_text:          pctText  || null,
        modal_present:     !!modalEl,
        error_state:       !!errorEl,
        error_message:     errorEl?.textContent?.trim()?.substring(0, 200) || null,
        all_svg_text:      allText.slice(0, 60),
        circle_details:    circleDetails,
        line_details:      lineDetails,
        frame_url:         window.location.href,
      };
    });

    const asserts = [
      ['SVG present',       visualAssertions.ASSERT_svg_present],
      ['Circles > 0',       visualAssertions.ASSERT_circles_gt_0],
      ['Dashed line exists', visualAssertions.ASSERT_dashed_line_exists],
      ['TBWL text visible', visualAssertions.ASSERT_tbwl_visible],
    ];
    console.log('\n  Visual assertion results:');
    asserts.forEach(([name, result]) =>
      console.log(`    [${result ? 'PASS' : 'FAIL'}] ${name}`)
    );
    if (visualAssertions.circle_count > 0)
      console.log(`    Circle count: ${visualAssertions.circle_count}`);
    if (visualAssertions.tbwl_text)
      console.log(`    TBWL text: "${visualAssertions.tbwl_text}"`);
    if (visualAssertions.error_state)
      console.log(`    ERROR STATE: ${visualAssertions.error_message}`);
  }

  // ── Step 6: Performance ────────────────────────────────────────────────
  const perfData = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const paints = performance.getEntriesByType('paint');
    const resources = performance.getEntriesByType('resource');
    let lcp = null;
    try { const e = performance.getEntriesByType('largest-contentful-paint'); lcp = e.length ? e[e.length-1].startTime : null; } catch {}
    return {
      TTFB_ms: nav?.responseStart ? parseFloat(nav.responseStart.toFixed(1)) : null,
      FCP_ms:  paints.find(p => p.name === 'first-contentful-paint')?.startTime ? parseFloat(paints.find(p => p.name === 'first-contentful-paint').startTime.toFixed(1)) : null,
      LCP_ms:  lcp ? parseFloat(lcp.toFixed(1)) : null,
      dom_complete_ms:  nav?.domComplete  ? parseFloat(nav.domComplete.toFixed(1))  : null,
      load_complete_ms: nav?.loadEventEnd ? parseFloat(nav.loadEventEnd.toFixed(1)) : null,
      total_resources:  resources.length,
      slow_resources:   resources.filter(r => r.duration > 500).sort((a, b) => b.duration - a.duration).slice(0, 8)
        .map(r => ({ url: r.name.substring(0, 120), duration_ms: Math.round(r.duration), type: r.initiatorType })),
    };
  });

  await browser.close();

  // ── Write artifacts ────────────────────────────────────────────────────
  console.log('\n[7] Writing artifacts');

  const failedAll = allRequests.filter(r => r.error || (r.status && r.status >= 400));
  const fhirByResource = fhirLog.reduce((acc, r) => {
    const m = r.url.match(/\/api\/([A-Za-z]+)/);
    if (m) acc[m[1]] = (acc[m[1]] || 0) + 1;
    return acc;
  }, {});
  const fhirByPhase = ['login', 'patient_search', 'chart_load', 'plugin_trigger'].reduce((acc, p) => {
    acc[p] = fhirLog.filter(r => r.phase === p).length;
    return acc;
  }, {});

  const networkLog = {
    schema_version: '1.0', session_id: SESSION_ID,
    captured_at: new Date().toISOString(),
    capture_method: 'context.route (proxy intercept — all frames including srcdoc iframes); patterns: **/api/** + **/graphql',
    fhir_requests: fhirLog,
    all_requests_summary: allRequests,
    summary: {
      total_fhir_requests: fhirLog.length,
      total_other_requests: allRequests.length,
      failed_requests: failedAll.length,
      errors: failedAll.map(r => ({ url: r.url, status: r.status, error: r.error })),
      fhir_by_resource: fhirByResource,
      fhir_by_phase: fhirByPhase,
    },
  };

  const consoleLog = {
    schema_version: '1.0', session_id: SESSION_ID,
    captured_at: new Date().toISOString(), entries: consoleLogs,
    summary: {
      total:            consoleLogs.length,
      errors:           consoleLogs.filter(l => l.level === 'error' || l.level === 'unhandled_error').length,
      warnings:         consoleLogs.filter(l => l.level === 'warn' || l.level === 'warning').length,
      unhandled_errors: consoleLogs.filter(l => l.level === 'unhandled_error').length,
    },
  };

  // Assertions summary for session.json
  const assertResults = visualAssertions ? [
    { name: 'SVG present',        pass: visualAssertions.ASSERT_svg_present },
    { name: 'Circles > 0',        pass: visualAssertions.ASSERT_circles_gt_0 },
    { name: 'Dashed line exists', pass: visualAssertions.ASSERT_dashed_line_exists },
    { name: 'TBWL text visible',  pass: visualAssertions.ASSERT_tbwl_visible },
  ] : [];
  const passed  = assertResults.filter(a => a.pass).length;
  const failed  = assertResults.filter(a => !a.pass).length;

  const screenshots = [];
  for (let i = 1; i <= ssIdx; i++) {
    const files = fs.readdirSync(path.join(SESSION_DIR, 'screenshots'))
      .filter(f => f.startsWith(String(i).padStart(3, '0')));
    if (files[0]) screenshots.push(`screenshots/${files[0]}`);
  }

  fs.writeFileSync(path.join(SESSION_DIR, 'api-calls', 'network_log.json'),        JSON.stringify(networkLog, null, 2));
  fs.writeFileSync(path.join(SESSION_DIR, 'api-calls', 'console_log.json'),        JSON.stringify(consoleLog, null, 2));
  fs.writeFileSync(path.join(SESSION_DIR, 'snapshots', 'visual_assertions.json'),  JSON.stringify({ session_id: SESSION_ID, assertions: assertResults, detail: visualAssertions }, null, 2));
  fs.writeFileSync(path.join(SESSION_DIR, 'performance', 'core_web_vitals.json'),  JSON.stringify({ schema_version: '1.0', session_id: SESSION_ID, url: chartUrl, raw: perfData }, null, 2));

  const session = {
    schema_version: '1.0', session_id: SESSION_ID,
    mode: ['visual', 'accessibility', 'performance', 'network', 'console'],
    metadata: { created_at: new Date().toISOString(), ended_at: new Date().toISOString(), tool: 'debug-capture-skill', operator: process.env.USER || 'unknown' },
    context: {
      project: 'canvas-sandbox', target_url: BASE_URL, canvas_host: env.CANVAS_HOST,
      patient_name: 'Lori Collins', chart_url: typeof chartUrl !== 'undefined' ? chartUrl : null,
      plugin: 'cardiometabolic_tracker', test_description: 'Patient chart load + cardiometabolic tracker button click',
      auth_method: 'credentials_from_env', auth_user: env.CANVAS_USERNAME,
    },
    results: {
      passed, failed,
      warnings: consoleLog.summary.warnings,
      assertion_results: assertResults,
      errors: [
        ...failedAll.map(r => ({ type: 'network_error', url: r.url, detail: r.error || `HTTP ${r.status}` })),
        ...consoleLogs.filter(l => l.level === 'unhandled_error').map(l => ({ type: 'js_error', message: l.message })),
        ...assertResults.filter(a => !a.pass).map(a => ({ type: 'assertion_failed', name: a.name })),
      ],
      summary: `Assertions: ${passed} pass / ${failed} fail. FHIR: ${fhirLog.length} calls via route intercept (${JSON.stringify(fhirByResource)}). Console: ${consoleLog.summary.errors} errors. Plugin button ${trackerBtn ? 'found and clicked' : 'NOT FOUND'}.`,
    },
    artifacts: {
      screenshots,
      network_log: 'api-calls/network_log.json',
      console_log: 'api-calls/console_log.json',
      visual_assertions: 'snapshots/visual_assertions.json',
      performance: 'performance/core_web_vitals.json',
    },
    figma: { upload_file_key: 'zhU3thHKxOblc5D9dL7hbl', upload_file_url: 'https://www.figma.com/design/zhU3thHKxOblc5D9dL7hbl', reference_file_key: null },
    agent_handoff: { brief: 'agent-handoff/brief.md', ready_for_agent: true,
      suggested_actions: assertResults.filter(a => !a.pass).map(a => `Fix failing assertion: ${a.name}`) },
  };
  fs.writeFileSync(path.join(SESSION_DIR, 'session.json'), JSON.stringify(session, null, 2));

  console.log('\n=== COMPLETE ===');
  console.log(JSON.stringify({
    session_id: SESSION_ID,
    session_dir: SESSION_DIR,
    authenticated: true,
    patient_chart_url: typeof chartUrl !== 'undefined' ? chartUrl : null,
    tracker_button_found: !!trackerBtn,
    tracker_button_text: trackerBtnText?.trim() || null,
    fhir_calls_total: fhirLog.length,
    fhir_calls_chart_load: fhirLog.filter(r => r.phase === 'chart_load').length,
    fhir_calls_plugin_click: fhirLog.filter(r => r.phase === 'plugin_trigger').length,
    fhir_by_resource: fhirByResource,
    assertions: assertResults,
    console_errors: consoleLog.summary.errors,
    screenshots,
  }, null, 2));
}

run().catch(e => { console.error('FATAL:', e.message, e.stack); process.exit(1); });
