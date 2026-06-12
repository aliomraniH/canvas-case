// Tier 1 + Tier 2 live validation — cardiometabolic_tracker v0.2.0
// One login, then per-patient: open chart, click "Weight Trajectory",
// locate the plugin frame (content-based: #cm-container — the v0.2 switch to
// RIGHT_CHART_PANE_LARGE may change the frame context vs the old modal), and
// run targeted assertions against DOM + the template's layer _data objects.
//
// Tier 2 per DEBUG_TOOLING.md: no session folder; results JSON + per-patient
// screenshot land next to this script's output dir.
//
// Usage: node tier2_v02_assertions.js [P1 P2 ...]   (default: all targets)

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

const SEEDED = JSON.parse(fs.readFileSync(
  process.env.SEEDED_MANIFEST || path.resolve(__dirname, '..', '..', '..', '.workspace_state', 'debug', 'seeded_patients.json'), 'utf8'));

const OUT_DIR = path.join(__dirname, 'tier2_v02_output');
fs.mkdirSync(OUT_DIR, { recursive: true });

const ARGS = process.argv.slice(2);
// --capture: screenshot the open SCALE popover during the assertion run,
// reusing this run's login + navigation (no second login cycle).
const CAPTURE = ARGS.includes('--capture');
const KEYS = ARGS.filter(a => !a.startsWith('--'));
const TARGETS = KEYS.length ? KEYS : ['P1', 'P2', 'P3', 'P4', 'P8'];

// ── Frame + assertion helpers ────────────────────────────────────────────

async function findPluginFrame(page) {
  // Content-based lookup: works for default_modal (about:srcdoc) AND the new
  // right_chart_pane_large target, whatever frame context it uses.
  for (let attempt = 0; attempt < 20; attempt++) {
    for (const frame of page.frames()) {
      try {
        if (await frame.locator('#cm-container').count() > 0) {
          return { frame, frame_url: frame.url() };
        }
        const body = await frame.locator('body').textContent({ timeout: 300 }).catch(() => '');
        if (body && body.includes('Unable to render weight trajectory')) {
          return { frame, frame_url: frame.url(), error_pane: true };
        }
      } catch { /* frame may detach mid-iteration */ }
    }
    await page.waitForTimeout(500);
  }
  return null;
}

async function inspectChart(frame) {
  // Runs in the plugin frame. Top-level consts in the template script are
  // global lexical bindings, so the layer objects are directly readable.
  return frame.evaluate(() => {
    const svg = document.querySelector('#cm-chart svg');
    const texts = svg ? [...svg.querySelectorAll('text')].map(t => t.textContent.trim()) : [];
    const dashedLines = svg ? svg.querySelectorAll('line[stroke-dasharray]').length : 0;
    const milestoneEls = svg ? svg.querySelectorAll('.cm-layer-milestones .cm-milestone').length : 0;
    const bandPath = svg ? svg.querySelector('.cm-layer-band path.cm-band-fill') : null;
    const circles = svg ? svg.querySelectorAll('.cm-layer-series circle').length : 0;
    const legend = document.getElementById('cm-legend');
    const legendText = document.getElementById('cm-legend-text');
    const velocityEl = document.getElementById('cm-velocity-value');
    const badges = [...document.querySelectorAll('.cm-badge')].map(b => ({
      flag: b.getAttribute('data-flag'), text: b.textContent.trim(),
    }));
    const flagMessages = [...document.querySelectorAll('.cm-flag-message')].map(m => m.textContent.trim());
    const dataNote = document.getElementById('cm-data-note');
    const bandInfo = document.getElementById('cm-band-info');
    const headlineEl = document.getElementById('cm-headline');
    const populationEl = document.getElementById('cm-band-info-population');

    let layerData = {};
    try {
      layerData = {
        milestones: (typeof MilestoneLayer !== 'undefined' && MilestoneLayer._data) || [],
        band_points: ((typeof ExpectedBandLayer !== 'undefined' && ExpectedBandLayer._data) || {}).points || [],
        band_label: ((typeof ExpectedBandLayer !== 'undefined' && ExpectedBandLayer._data) || {}).label || null,
        datapoints: ((typeof DataPointLayer !== 'undefined' && DataPointLayer._data) || [])
          .map(d => ({ value_lbs: +d.value_lbs, tbwl_pct: +d.tbwl_pct })),
        velocity: ((typeof StatsBar !== 'undefined' && StatsBar._data) || {}).velocity_stats || null,
        flags: (((typeof StatsBar !== 'undefined' && StatsBar._data) || {}).flags || []).map(f => f.key),
      };
    } catch (e) {
      layerData = { error: String(e) };
    }

    return {
      svg_present: !!svg,
      circles,
      dashed_line_count: dashedLines,
      milestone_count: milestoneEls,
      // v0.2.5: milestone labels are now "5% — 209 lb" (percent + patient unit).
      milestone_labels: texts.filter(t => /^\d+%\s—\s\d+\s\w+$/.test(t)),
      headline_text: headlineEl ? headlineEl.textContent : null,
      band_info_population: populationEl ? populationEl.textContent : null,
      band_fill_present: !!bandPath,
      legend_visible: legend ? legend.style.display !== 'none' : false,
      legend_text: legendText ? legendText.textContent : null,
      velocity_display: velocityEl ? velocityEl.textContent.trim() : null,
      badges,
      flag_messages: flagMessages,
      data_note: dataNote && dataNote.style.display !== 'none' ? dataNote.textContent : null,
      band_info_text: bandInfo ? bandInfo.textContent : null,
      band_info_has_disclosure: !!(bandInfo && bandInfo.querySelector('.cm-band-info-disclosure')),
      layer_data: layerData,
    };
  });
}

function check(results, name, ok, detail) {
  results.push({ check: name, ok: !!ok, detail });
  console.log(`    ${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

// ── Per-patient expectations ─────────────────────────────────────────────

function assertions(key, s) {
  const r = [];
  const ld = s.layer_data || {};
  const velocityOk = s.velocity_display && /^(—|-?\d+\.\d{2}%\/wk)$/.test(s.velocity_display);

  check(r, 'svg renders', s.svg_present);
  check(r, 'velocity stat parseable', velocityOk, s.velocity_display);

  // v0.2.3 band citation panel (SCALE disclosure patch)
  if (key === 'P1') {
    check(r, 'v0.2.4: legend has no SD/estimated qualifier',
      !(s.legend_text || '').includes('estimated') && !(s.legend_text || '').includes('±'),
      s.legend_text);
    check(r, 'v0.2.3: panel cites STEP 1 (2021;384)', (s.band_info_text || '').includes('2021;384'),
      (s.band_info_text || '').substring(0, 80));
    check(r, 'v0.2.3: no disclosure note on trial-derived band', !s.band_info_has_disclosure);
  }
  if (key === 'P2') {
    check(r, 'v0.2.3: fallback panel cites STEP 1 (2021;384)', (s.band_info_text || '').includes('2021;384'),
      (s.band_info_text || '').substring(0, 80));
  }
  if (key === 'P4') {
    check(r, 'v0.2.4: legend SCALE ±1 SD, not estimated',
      (s.legend_text || '').includes('SCALE, ±1 SD') && !(s.legend_text || '').includes('estimated'),
      s.legend_text);
    check(r, 'v0.2.4: panel cites SCALE (2015;373)', (s.band_info_text || '').includes('2015;373'),
      (s.band_info_text || '').substring(0, 80));
    check(r, 'v0.2.4: disclosure shows −8.0 ± 6.7 + Pi-Sunyer', s.band_info_has_disclosure &&
      (s.band_info_text || '').includes('−8.0 ± 6.7') &&
      (s.band_info_text || '').includes('Pi-Sunyer') &&
      !(s.band_info_text || '').includes('illustrative'),
      (s.band_info_text || '').substring(0, 120));
    check(r, 'v0.2.5: basis says full analysis set, not completer',
      (s.band_info_text || '').includes('full analysis') && !/completer/i.test(s.band_info_text || ''),
      (s.band_info_text || '').substring(0, 120));
    check(r, 'v0.2.5: population line shows 8.4 kg + 18.5 lb',
      /8\.4 kg/.test(s.band_info_population || '') && /18\.5 lb/.test(s.band_info_population || '') &&
      /applied to their own baseline/.test(s.band_info_population || ''),
      s.band_info_population);
  }

  if (key === 'P1') {
    const pcts = (ld.milestones || []).map(m => m.pct).sort((a, b) => a - b);
    const crossed = (ld.milestones || []).filter(m => m.crossed).map(m => m.pct).sort((a, b) => a - b);
    check(r, 'E1: 5% and 10% milestones present+crossed',
      crossed.includes(5) && crossed.includes(10), `pcts=${JSON.stringify(pcts)} crossed=${JSON.stringify(crossed)}`);
    check(r, 'E1: milestone DOM lines match data', s.milestone_count === (ld.milestones || []).length,
      `dom=${s.milestone_count} data=${(ld.milestones || []).length}`);
    check(r, 'E1: labels rendered (v0.2.5 unit form)', s.milestone_labels.length >= 2, JSON.stringify(s.milestone_labels));
    check(r, 'v0.2.5: milestone labels carry lb weight', s.milestone_labels.every(t => / lb$/.test(t)),
      JSON.stringify(s.milestone_labels));
    check(r, 'v0.2.5: headline dual-metric (% + lb absolute)',
      /%\s*TBWL/.test(s.headline_text || '') && / lb from .* lb baseline/.test(s.headline_text || ''),
      s.headline_text);
    check(r, 'E1: dashed lines = baseline + milestones', s.dashed_line_count === s.milestone_count + 1,
      `dashed=${s.dashed_line_count}`);
    check(r, 'E2: band behind patient line (fill present)', s.band_fill_present);
    check(r, 'E2/A3: legend STEP-1 (wegovy detected)', (s.legend_text || '').includes('STEP-1'), s.legend_text);
    check(r, 'E3: no flag badge', s.badges.length === 0, JSON.stringify(s.badges));
    check(r, 'inside/below band at last point',
      ld.datapoints.length && ld.band_points.length &&
      ld.datapoints[ld.datapoints.length - 1].value_lbs <= ld.band_points[ld.band_points.length - 1].lower_lbs,
      `last=${ld.datapoints.slice(-1)[0]?.value_lbs} band_top=${ld.band_points.slice(-1)[0]?.lower_lbs?.toFixed(1)}`);
  }

  if (key === 'P2') {
    check(r, 'E2: band fill present', s.band_fill_present);
    check(r, 'E2/A3: legend STEP-1 (default fallback, no med)', (s.legend_text || '').includes('STEP-1'), s.legend_text);
    check(r, 'E2: patient line above band upper edge at last point',
      ld.datapoints.length && ld.band_points.length &&
      ld.datapoints[ld.datapoints.length - 1].value_lbs > ld.band_points[ld.band_points.length - 1].lower_lbs,
      `last=${ld.datapoints.slice(-1)[0]?.value_lbs} band_top=${ld.band_points.slice(-1)[0]?.lower_lbs?.toFixed(1)}`);
    check(r, 'E1: 5% milestone visible, uncrossed',
      (ld.milestones || []).some(m => m.pct === 5 && !m.crossed),
      JSON.stringify(ld.milestones));
    check(r, 'E3: no flags (slow but steady loss)', s.badges.length === 0, JSON.stringify(s.badges));
  }

  if (key === 'P3') {
    check(r, 'E3: plateau badge', s.badges.some(b => b.flag === 'plateau'), JSON.stringify(s.badges));
    check(r, 'E3: plateau copy descriptive', s.flag_messages.some(m => m.includes('Weight loss has slowed')),
      JSON.stringify(s.flag_messages));
    check(r, 'A3: legend SURMOUNT-1 (zepbound detected)', (s.legend_text || '').includes('SURMOUNT-1'), s.legend_text);
    check(r, 'E3: no rapid/regain', !s.badges.some(b => b.flag !== 'plateau'), JSON.stringify(s.badges));
  }

  if (key === 'P4') {
    check(r, 'E3: rapid-loss badge', s.badges.some(b => b.flag === 'rapid_loss'), JSON.stringify(s.badges));
    check(r, 'A3: legend SCALE (saxenda detected)', (s.legend_text || '').includes('SCALE'), s.legend_text);
    check(r, 'E3: velocity magnitude > 1%/wk', ld.velocity && ld.velocity.velocity_pct_per_week > 1.0,
      JSON.stringify(ld.velocity && ld.velocity.velocity_pct_per_week));
  }

  if (key === 'P5') {
    check(r, 'E3/A5: regain badge (not plateau)', s.badges.some(b => b.flag === 'regain') &&
      !s.badges.some(b => b.flag === 'plateau'), JSON.stringify(s.badges));
    check(r, '5% line re-crossed upward without render errors',
      (ld.milestones || []).some(m => m.pct === 5) && s.svg_present, JSON.stringify(ld.milestones));
  }

  if (key === 'P6') {
    check(r, 'P6: line renders from two points', s.circles === 2, `circles=${s.circles}`);
    check(r, 'P6: band renders', s.band_fill_present);
    check(r, 'P6: interpolated velocity (qualifies, >=14d)', /-0\.2\d%\/wk/.test(s.velocity_display || ''),
      s.velocity_display);
    check(r, 'P6: no flags', s.badges.length === 0, JSON.stringify(s.badges));
    check(r, 'P6: sparse-data note shown', !!s.data_note, s.data_note);
  }

  if (key === 'P7') {
    check(r, 'P7: single point renders', s.circles === 1, `circles=${s.circles}`);
    check(r, 'P7: baseline line only (no milestones)', s.milestone_count === 0 && s.dashed_line_count === 1,
      `milestones=${s.milestone_count} dashed=${s.dashed_line_count}`);
    check(r, 'P7: velocity em-dash', s.velocity_display === '—', s.velocity_display);
    check(r, 'P7: no flags, no band', s.badges.length === 0 && !s.band_fill_present);
    check(r, 'P7: single-measurement note shown', !!s.data_note, s.data_note);
  }

  if (key === 'P9') {
    check(r, 'P9: same-day duplicates collapse (3 points from 4 obs)', s.circles === 3, `circles=${s.circles}`);
    check(r, 'P9: averaged middle point 246.7', ld.datapoints.some(d => Math.abs(d.value_lbs - 246.7) < 0.01),
      JSON.stringify(ld.datapoints.map(d => +d.value_lbs.toFixed(1))));
  }

  if (key === 'P8') {
    const vals = ld.datapoints.map(d => d.value_lbs);
    check(r, 'P8: all values one unit range (200-235 lb)', vals.length === 6 && vals.every(v => v > 200 && v < 235),
      JSON.stringify(vals.map(v => +v.toFixed(1))));
    check(r, 'P8: monotonic downward once normalized',
      vals.every((v, i) => i === 0 || vals[i - 1] > v), JSON.stringify(vals.map(v => +v.toFixed(1))));
    // v0.2.5: headline absolute + milestone labels all in ONE unit (lb), no kg/lb mix.
    check(r, 'v0.2.5: headline + milestone labels single-unit (lb, no kg)',
      / lb from .* lb baseline/.test(s.headline_text || '') && !/kg/.test(s.headline_text || '') &&
      s.milestone_labels.every(t => / lb$/.test(t) && !/kg/.test(t)),
      `headline=${s.headline_text} labels=${JSON.stringify(s.milestone_labels)}`);
  }

  return r;
}

// ── Main ─────────────────────────────────────────────────────────────────

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  const consoleErrors = [];
  // The "no console errors" check is scoped to PLUGIN-relevant errors:
  //  - any unhandled JS exception (pageerror) anywhere
  //  - resource-load failures for the plugin's own dependencies (jsdelivr d3)
  //    or anything inside the srcdoc frame
  // Host-page noise excluded (seen on every EHR page, plugin or not): the CSP
  // report-only warning, and host-page resource failures (analytics endpoints
  // refusing connections, NotSameOrigin-blocked host assets).
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const text = m.text();
    const srcUrl = (m.location() && m.location().url) || '';
    if (/Content Security Policy directive 'upgrade-insecure-requests'/.test(text)) return;
    if (/Failed to load resource/.test(text)) {
      if (srcUrl.includes('jsdelivr') || srcUrl === 'about:srcdoc') {
        consoleErrors.push(`resource: ${srcUrl} — ${text}`);
      }
      return; // host-page resource failure — not plugin output
    }
    consoleErrors.push(text);
  });

  console.log('[login]');
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
  await page.fill('input[type="text"], input[name="username"]', env.CANVAS_USERNAME);
  await page.fill('input[type="password"]', env.CANVAS_PASSWORD);
  await page.click('button[type="submit"], button:has-text("Login")');
  try { await page.waitForURL(u => !String(u).includes('/login'), { timeout: 15000 }); } catch {}
  await page.waitForLoadState('networkidle').catch(() => {});
  console.log('  landed:', page.url());

  const allResults = { run_at: new Date().toISOString(), plugin: 'cardiometabolic_tracker@0.2.0', patients: {} };

  for (const key of TARGETS) {
    const info = SEEDED.patients[key];
    if (!info) { console.log(`\n[${key}] not in seeded manifest — skipping`); continue; }
    console.log(`\n[${key}] ${info.name} — ${info.chart_url}`);
    consoleErrors.length = 0;

    await page.goto(info.chart_url, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(2500);

    // Find + click the action button in the vitals section.
    const btn = page.locator('button:has-text("Weight Trajectory")').first();
    if (await btn.count() === 0) {
      await page.evaluate(() => {
        const el = [...document.querySelectorAll('*')].find(e => e.textContent.trim() === 'Vital Signs');
        el?.scrollIntoView({ block: 'center' });
      });
      await page.waitForTimeout(1000);
    }
    if (await btn.count() === 0) {
      console.log('    FAIL  Weight Trajectory button not found');
      allResults.patients[key] = { error: 'button_not_found' };
      await page.screenshot({ path: path.join(OUT_DIR, `${key}_no_button.png`) });
      continue;
    }
    await btn.scrollIntoViewIfNeeded().catch(() => {});
    await btn.click();

    const found = await findPluginFrame(page);
    if (!found || found.error_pane) {
      console.log(`    ${found ? 'error pane shown' : 'FAIL  plugin frame not found'}`);
      allResults.patients[key] = { frame_url: found?.frame_url, error_pane: !!found?.error_pane };
      await page.screenshot({ path: path.join(OUT_DIR, `${key}_state.png`) });
      continue;
    }
    console.log(`    plugin frame: ${found.frame_url || '(empty url)'}`);
    await page.waitForTimeout(1500); // let the draw-in animation finish

    const state = await inspectChart(found.frame);
    const checks = assertions(key, state);
    check(checks, 'no console errors', consoleErrors.length === 0,
      consoleErrors.slice(0, 3).join(' | ').substring(0, 200));

    await page.screenshot({ path: path.join(OUT_DIR, `${key}_chart.png`) });

    // --capture: open the band-info popover and screenshot it in this same
    // session (deletes the second login cycle prior runs paid for this).
    if (CAPTURE && key === 'P4') {
      try {
        await found.frame.locator('#cm-band-info-btn').click();
        await page.waitForTimeout(400);
        const shot = path.join(OUT_DIR, 'P4_scale_popover_v024.png');
        await page.screenshot({ path: shot });
        console.log(`    captured: ${shot}`);
      } catch (e) {
        console.log(`    capture failed: ${String(e).substring(0, 120)}`);
      }
    }
    allResults.patients[key] = { frame_url: found.frame_url, state, checks };
  }

  fs.writeFileSync(path.join(OUT_DIR, 'results.json'), JSON.stringify(allResults, null, 2));
  const flat = Object.entries(allResults.patients)
    .flatMap(([k, v]) => (v.checks || []).map(c => ({ patient: k, ...c })));
  const failed = flat.filter(c => !c.ok);
  console.log(`\n=== ${flat.length - failed.length}/${flat.length} checks passed ===`);
  failed.forEach(f => console.log(`  FAILED: [${f.patient}] ${f.check} — ${f.detail || ''}`));
  await browser.close();
  process.exit(failed.length || !flat.length ? 1 : 0);
})();
