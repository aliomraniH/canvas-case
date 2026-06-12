# Mode Playbooks

Exact step-by-step instructions for each debug mode.
For `full` mode, run in order: network → console → navigate → visual → accessibility → performance.

---

## `network` mode — capture all API calls + responses

**Run this FIRST, before any page interaction.**

### Why `context.route()` instead of fetch/XHR injection

The previous approach (monkey-patching `window.fetch` / `XMLHttpRequest`) only works in
the main page frame. Canvas plugins render in `about:srcdoc` iframes and communicate with
the host page via `postMessage`; the host page then makes the FHIR calls. Those calls
originate from the host frame, not the script-injection context. Additionally, `evaluate_script`
injections miss requests made before the injection runs.

`context.route()` operates at the Playwright network proxy layer — it intercepts **every**
matching request from **every** frame (main, iframes, srcdoc, workers) regardless of
timing, and gives access to full request + response bodies.

### Canvas API URL structure

**Canvas does NOT use FHIR R4 URLs (`/api/r4/<Resource>`) for browser-level calls.**
The EHR's internal REST API uses `/api/<Resource>/` (Django REST Framework):
- `/api/Patient/<key>` — patient demographics
- `/api/Condition/?patient__key=<key>` — problems/conditions
- `/api/Medication/?patient__key=<key>` — medications
- `/api/Immunization/?patient__key=<key>` — immunizations
- `/api/AllergyIntolerance/?patient__key=<key>` — allergies
- `/api/Interview/?patient__key=<key>` — questionnaires
- `/api/NoteMetadata/?patient__key=<key>` — notes
- `/graphql` — GraphQL (UI state, plugin rendering)

**Plugin data access is server-side.** Canvas SDK plugins (e.g. cardiometabolic tracker)
use `canvas_sdk.v1.data` ORM to query data server-side; the rendered HTML is sent to the
browser via `about:srcdoc`. No browser-level Observation/clinical-data API calls appear
when a plugin button is clicked — only a GraphQL POST for the plugin render event.

**Use a URL predicate (not a glob)** to avoid catching third-party `/api/` calls
(Aptrinsic, Sentry, etc.) that share the same path prefix.

### 1. Register Canvas API route interceptors (before any navigation)

```javascript
// Playwright — set up before browser.newContext() is used
const CANVAS_HOST = 'your-instance.canvasmedical.com'; // from env
const apiLog = [];

// Canvas REST API calls: /api/<Resource>/
await context.route(
  url => url.hostname === CANVAS_HOST && url.pathname.startsWith('/api/'),
  async (route, request) => {
    const t0 = Date.now();
    const response = await route.fetch();           // pass request through
    const duration = Date.now() - t0;

    let body = null;
    try { body = await response.text(); } catch {}

    const u = request.url();
    const tags = ['canvas_api'];
    if (u.includes('Observation'))        tags.push('observation');
    if (u.includes('Patient'))            tags.push('patient');
    if (u.includes('Condition'))          tags.push('condition');
    if (u.includes('Medication'))         tags.push('medication');
    if (u.includes('AllergyIntolerance')) tags.push('allergy');
    if (u.includes('Immunization'))       tags.push('immunization');
    if (u.includes('Interview'))          tags.push('interview');
    if (u.includes('NoteMetadata'))       tags.push('note');

    apiLog.push({
      id:        'api_' + String(apiLog.length).padStart(3, '0'),
      phase:     currentPhase,
      timestamp: new Date().toISOString(),
      method:    request.method(),
      url:       u,
      status:    response.status(),
      duration_ms: duration,
      request_body:            request.postData() || null,
      response_body:           body ? body.substring(0, 8000) : null,
      response_body_truncated: body ? body.length > 8000 : false,
      tags,
    });

    await route.fulfill({ response });
  }
);

// Canvas GraphQL: /graphql
await context.route(
  url => url.hostname === CANVAS_HOST && url.pathname === '/graphql',
  async (route, request) => {
    const t0 = Date.now();
    const response = await route.fetch();
    let body = null;
    try { body = await response.text(); } catch {}
    apiLog.push({
      id: 'api_' + String(apiLog.length).padStart(3, '0'),
      phase: currentPhase, timestamp: new Date().toISOString(),
      method: request.method(), url: request.url(), status: response.status(),
      duration_ms: Date.now() - t0,
      request_body: request.postData() || null,
      response_body: body ? body.substring(0, 8000) : null,
      response_body_truncated: body ? body.length > 8000 : false,
      tags: ['canvas_api', 'graphql'],
    });
    await route.fulfill({ response });
  }
);

// Event listener for everything else (static assets, CDN, analytics)
const allRequests = [];
context.on('request', req => {
  const u = req.url();
  if (!u.includes('/api/') && !u.includes('/graphql'))
    allRequests.push({ phase: currentPhase, method: req.method(), url: u, status: null });
});
context.on('response', res => {
  const e = allRequests.find(r => r.url === res.url() && r.status === null);
  if (e) e.status = res.status();
});
```

### 2. Perform the test actions (navigate, click, interact)

FHIR calls are captured automatically via the route handler — no explicit collection step needed.

### 3. Tag and summarise

```javascript
const byResource = apiLog.reduce((acc, r) => {
  const m = r.url.match(/\/api\/([A-Za-z]+)/);
  if (m) acc[m[1]] = (acc[m[1]] || 0) + 1;
  return acc;
}, {});

const summary = {
  total_api:    apiLog.length,
  by_resource:  byResource,
  by_phase:     Object.fromEntries(
    ['login','chart_load','plugin_trigger'].map(p => [
      p, apiLog.filter(r => r.phase === p).length
    ])
  ),
  failed:       apiLog.filter(r => r.status >= 400).map(r => ({ url: r.url, status: r.status })),
};
```

### 4. Write to `api-calls/network_log.json`

Structure the output with `fhir_requests` (route-intercepted, full bodies) and
`all_requests` (event-based, all resource types) as separate top-level arrays.

---

## `console` mode — capture errors and warnings

**Also run BEFORE page interaction (same session as network).**

```javascript
// evaluate_script
window.__debugCapture = window.__debugCapture || { requests: [], logs: [] };

['log', 'warn', 'error', 'info', 'debug'].forEach(level => {
  const orig = console[level].bind(console);
  console[level] = function(...args) {
    window.__debugCapture.logs.push({
      level,
      timestamp: new Date().toISOString(),
      message: args.map(a => {
        if (a instanceof Error) return a.message + '\n' + a.stack;
        if (typeof a === 'object') { try { return JSON.stringify(a); } catch { return String(a); } }
        return String(a);
      }).join(' ')
    });
    return orig(...args);
  };
});

window.addEventListener('error', e => {
  window.__debugCapture.logs.push({
    level: 'unhandled_error',
    timestamp: new Date().toISOString(),
    message: e.message,
    source: e.filename ? `${e.filename}:${e.lineno}:${e.colno}` : null,
    stack_trace: e.error?.stack || null
  });
});

window.addEventListener('unhandledrejection', e => {
  window.__debugCapture.logs.push({
    level: 'unhandled_promise',
    timestamp: new Date().toISOString(),
    message: String(e.reason)
  });
});

return 'console interceptor installed';
```

Collect after test: `return window.__debugCapture.logs;`

Write to `api-calls/console_log.json`.

### Plugin attribution (REQUIRED before asserting on console errors)

The Canvas host app emits console noise on every page — plugin or not — that
must never fail a plugin check (observed live, v0.2: a CSP report-only warning
plus analytics resource failures `ERR_CONNECTION_REFUSED` /
`ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`).

1. **Classify every captured entry by origin frame**: entries whose source is
   the `about:srcdoc` plugin iframe (or the plugin's own CDN dependencies,
   e.g. the d3 jsdelivr script) vs. entries from the host Canvas app. In
   Playwright, `msg.location().url` gives the source; `about:srcdoc` or the
   plugin's CDN host → plugin. Unhandled `pageerror` exceptions count as
   plugin-relevant from any frame.
2. **Record both counts in `console_log.json`** — add an `origin` field per
   entry: `"plugin" | "host" | "unknown"`.
3. **Assert only on plugin-attributable errors.** Host-app noise is logged
   for context but never fails a check.
4. When the source frame is ambiguous (e.g. errors surfacing on `window`
   before the iframe mounts), classify `unknown` and include it in the
   agent-handoff brief for human judgment rather than auto-failing.

---

## `visual` mode — screenshots + SVG element detection

### 1. Take navigation screenshot
```
navigate_page(url)
take_screenshot() → save as screenshots/001_[page_name].png
```

### 2. Interact (click button, open modal, etc.)
```
click('[data-testid="vitals-button"]') or click by label
take_screenshot() → save as screenshots/002_[modal_name].png
```

### 3. Detect d3/SVG elements via evaluate_script
```javascript
// For cardiometabolic tracker chart modal
const svgPresent = !!document.querySelector('svg');
const circles = document.querySelectorAll('svg circle');
const dashedLines = document.querySelectorAll('line[stroke-dasharray]');
const textEls = [...document.querySelectorAll('svg text, text')]
  .map(t => t.textContent.trim()).filter(Boolean);
const tbwlAnnotation = textEls.find(t => t.includes('TBWL') || t.includes('%'));
const errorModal = document.querySelector('[data-error], .error-message');

return {
  svg_present: svgPresent,
  data_point_count: circles.length,
  baseline_line_present: dashedLines.length > 0,
  baseline_line_color: dashedLines[0]?.getAttribute('stroke') || null,
  tbwl_annotation: tbwlAnnotation || null,
  all_text_labels: textEls,
  error_state: !!errorModal,
  error_message: errorModal?.textContent?.trim() || null
};
```

### 4. Write visual assertions to session.json results

Screenshot naming convention:
```
NNN_[context]_[state].png
001_dashboard_loaded.png
002_chart_modal_lori_collins.png
003_error_modal_jane_will.png
```

---

## `accessibility` mode — WCAG audit

### 1. Take accessibility snapshot
```
take_snapshot()
```

### 2. Extract and validate tree via evaluate_script
```javascript
// Get all interactive elements with their accessible names
const buttons = [...document.querySelectorAll('button, [role="button"]')]
  .map(b => ({ tag: 'button', text: b.textContent.trim(), ariaLabel: b.getAttribute('aria-label'), visible: b.offsetParent !== null }));

const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')]
  .map(h => ({ level: h.tagName || h.getAttribute('aria-level'), text: h.textContent.trim() }));

const images = [...document.querySelectorAll('img, svg[role="img"], canvas')]
  .map(i => ({ tag: i.tagName, alt: i.getAttribute('alt'), ariaLabel: i.getAttribute('aria-label'), hasLabel: !!(i.getAttribute('alt') || i.getAttribute('aria-label')) }));

const inputs = [...document.querySelectorAll('input, select, textarea')]
  .map(i => ({ type: i.type || i.tagName, label: document.querySelector(`label[for="${i.id}"]`)?.textContent?.trim(), ariaLabel: i.getAttribute('aria-label'), hasLabel: !!(document.querySelector(`label[for="${i.id}"]`) || i.getAttribute('aria-label')) }));

return { buttons, headings, images, inputs };
```

### 3. Check WCAG violations
Flag any:
- Image/SVG without alt text or aria-label
- Button without accessible name
- Input without label
- Heading hierarchy skips (h1 → h3 with no h2)
- Interactive element with `tabindex="-1"` that should be reachable

Write to `snapshots/accessibility_tree.json`.

---

## `performance` mode — Core Web Vitals

### 1. Capture after page is fully loaded
```javascript
const nav = performance.getEntriesByType('navigation')[0];
const paints = performance.getEntriesByType('paint');
const resources = performance.getEntriesByType('resource');

// LCP via PerformanceObserver (if already observed)
let lcp = null;
try {
  const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
  lcp = lcpEntries[lcpEntries.length - 1]?.startTime || null;
} catch {}

return {
  TTFB_ms: nav?.responseStart?.toFixed(1),
  FCP_ms:  paints.find(p => p.name === 'first-contentful-paint')?.startTime?.toFixed(1),
  LCP_ms:  lcp?.toFixed(1),
  dom_interactive_ms: nav?.domInteractive?.toFixed(1),
  dom_complete_ms:    nav?.domComplete?.toFixed(1),
  load_complete_ms:   nav?.loadEventEnd?.toFixed(1),
  total_resources:    resources.length,
  slow_resources:     resources.filter(r => r.duration > 1000).map(r => ({ url: r.name, duration_ms: r.duration.toFixed(0) }))
};
```

### 2. Plugin-specific timing (Canvas EHR)
```javascript
// Measure time from button click to SVG render
const t0 = performance.now();
// ... trigger plugin button ...
// Poll until SVG appears
const waitForChart = () => new Promise(resolve => {
  const check = () => {
    if (document.querySelector('svg circle')) {
      resolve(performance.now() - t0);
    } else {
      requestAnimationFrame(check);
    }
  };
  check();
});
return await waitForChart();
```

Write to `performance/core_web_vitals.json`.

---

## `full` mode — run order

```
1. navigate_page to target URL
2. inject network interceptor (network mode step 1)
3. inject console interceptor (console mode step 1)
4. perform all test interactions
5. collect network results → write network_log.json
6. collect console results → write console_log.json
7. capture accessibility snapshot → write accessibility_tree.json
8. capture performance metrics → write core_web_vitals.json
9. run evaluate_script visual assertions → update session.json results
10. write agent-handoff brief + deploy script
```
