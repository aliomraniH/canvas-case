# Session JSON Schemas

All schemas below are designed to be readable by Claude Code, Claude.ai,
and future autonomous agents. Field names are explicit and self-describing.
Never omit a field — use `null` for not-yet-captured values.

---

## session.json — master session record

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_full",
  "mode": ["visual", "accessibility", "performance", "network", "console"],
  "metadata": {
    "created_at": "2026-06-09T14:30:00Z",
    "ended_at": null,
    "duration_seconds": null,
    "tool": "debug-capture-skill",
    "claude_surface": "desktop",
    "operator": "<your-username>"
  },
  "context": {
    "project": "cardiometabolic_tracker",
    "plugin_version": "0.1.3",
    "target_url": "https://<instance>.canvasmedical.com/",
    "canvas_host": "<instance>",
    "patient_name": "Lori Collins",
    "patient_key": null,
    "test_description": "Chart modal visual verification",
    "git_branch": "main",
    "git_commit": "eca99ac"
  },
  "results": {
    "passed": 0,
    "failed": 0,
    "warnings": 0,
    "errors": [],
    "summary": null
  },
  "artifacts": {
    "screenshots": [],
    "network_log": null,
    "console_log": null,
    "accessibility_tree": null,
    "performance": null,
    "figma_diff": null
  },
  "figma": {
    "upload_file_key": null,
    "upload_file_url": null,
    "reference_file_key": null,
    "reference_file_name": null,
    "reference_node_id": null,
    "reference_node_name": null,
    "diff_report": null
  },
  "agent_handoff": {
    "brief": "agent-handoff/brief.md",
    "deploy_script": "agent-handoff/test_deploy.sh",
    "rerun_command": null,
    "suggested_actions": [],
    "ready_for_agent": false
  }
}
```

---

## network_log.json — API calls + browser responses

Capture ALL requests made during the test, including FHIR, auth, and static
assets. The `response_body` field is critical for debugging — include it in
full for FHIR/API calls, truncate to 500 chars for static assets.

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_full",
  "captured_at": "2026-06-09T14:30:05Z",
  "capture_method": "evaluate_script|chrome_devtools_network",
  "requests": [
    {
      "id": "req_001",
      "sequence": 1,
      "timestamp": "2026-06-09T14:30:05.123Z",
      "triggered_by": "plugin_button_click",
      "method": "GET",
      "url": "https://<instance>.canvasmedical.com/api/r4/Observation?patient=abc123&category=vital-signs",
      "url_parsed": {
        "host": "<instance>.canvasmedical.com",
        "path": "/api/r4/Observation",
        "params": { "patient": "abc123", "category": "vital-signs" }
      },
      "request_headers": {
        "Authorization": "Bearer [REDACTED]",
        "Content-Type": "application/fhir+json"
      },
      "request_body": null,
      "status": 200,
      "status_text": "OK",
      "duration_ms": 145,
      "response_headers": {
        "Content-Type": "application/fhir+json",
        "X-Request-ID": "abc-123"
      },
      "response_body": {
        "resourceType": "Bundle",
        "total": 6,
        "entry": []
      },
      "response_body_truncated": false,
      "error": null,
      "tags": ["fhir", "observation", "weight"]
    }
  ],
  "summary": {
    "total_requests": 1,
    "fhir_requests": 1,
    "auth_requests": 0,
    "failed_requests": 0,
    "total_duration_ms": 145,
    "avg_duration_ms": 145,
    "slowest_request_id": "req_001",
    "errors": []
  }
}
```

**Capture via evaluate_script:**
```javascript
// Inject network interceptor BEFORE navigating
const requests = [];
const origOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(method, url) {
  this._debugUrl = url;
  this._debugMethod = method;
  this.addEventListener('load', function() {
    requests.push({
      method: this._debugMethod,
      url: this._debugUrl,
      status: this.status,
      response: this.responseText.substring(0, 2000)
    });
  });
  return origOpen.apply(this, arguments);
};

// Also capture fetch
const origFetch = window.fetch;
window.fetch = async function(...args) {
  const res = await origFetch(...args);
  const clone = res.clone();
  const body = await clone.text();
  requests.push({
    method: args[1]?.method || 'GET',
    url: args[0],
    status: res.status,
    response: body.substring(0, 2000)
  });
  return res;
};

return requests;
```

---

## console_log.json — browser console capture

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_full",
  "captured_at": "2026-06-09T14:30:00Z",
  "entries": [
    {
      "id": "con_001",
      "timestamp": "2026-06-09T14:30:05.200Z",
      "level": "error",
      "message": "TypeError: Cannot read properties of undefined (reading 'units')",
      "source": "growth_charts.js:142",
      "stack_trace": "at buildChartData (growth_charts.js:142)\n  at handle (growth_charts.js:87)",
      "related_request_id": "req_001",
      "tags": ["sdk-bug", "units-field"]
    }
  ],
  "summary": {
    "total": 1,
    "errors": 1,
    "warnings": 0,
    "info": 0,
    "debug": 0
  }
}
```

**Capture via evaluate_script:**
```javascript
// Inject before page interaction
const logs = [];
['log','warn','error','info'].forEach(level => {
  const orig = console[level];
  console[level] = function(...args) {
    logs.push({
      level,
      timestamp: new Date().toISOString(),
      message: args.map(a =>
        typeof a === 'object' ? JSON.stringify(a) : String(a)
      ).join(' ')
    });
    return orig.apply(console, args);
  };
});

// Capture unhandled errors
window.addEventListener('error', e => {
  logs.push({
    level: 'unhandled_error',
    timestamp: new Date().toISOString(),
    message: e.message,
    source: `${e.filename}:${e.lineno}`,
    stack_trace: e.error?.stack || null
  });
});

return logs;
```

---

## core_web_vitals.json — performance metrics

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_full",
  "captured_at": "2026-06-09T14:30:10Z",
  "url": "https://<instance>.canvasmedical.com/",
  "metrics": {
    "LCP":  { "value_ms": 1240, "rating": "good",     "threshold_good": 2500, "threshold_poor": 4000 },
    "CLS":  { "value":    0.02,  "rating": "good",     "threshold_good": 0.1,  "threshold_poor": 0.25 },
    "INP":  { "value_ms": 85,    "rating": "good",     "threshold_good": 200,  "threshold_poor": 500  },
    "TBT":  { "value_ms": 120,   "rating": "good",     "threshold_good": 200,  "threshold_poor": 600  },
    "FCP":  { "value_ms": 890,   "rating": "good",     "threshold_good": 1800, "threshold_poor": 3000 },
    "TTFB": { "value_ms": 210,   "rating": "good",     "threshold_good": 800,  "threshold_poor": 1800 }
  },
  "plugin_specific": {
    "modal_open_to_chart_render_ms": null,
    "observation_query_duration_ms": null,
    "d3_render_duration_ms": null
  },
  "summary": {
    "overall_rating": "good",
    "failed_metrics": [],
    "warnings": []
  }
}
```

**Capture via evaluate_script:**
```javascript
const navEntry = performance.getEntriesByType('navigation')[0];
const paintEntries = performance.getEntriesByType('paint');
return {
  TTFB: navEntry?.responseStart,
  FCP: paintEntries.find(e => e.name === 'first-contentful-paint')?.startTime,
  domInteractive: navEntry?.domInteractive,
  domComplete: navEntry?.domComplete,
  loadComplete: navEntry?.loadEventEnd,
  resourceCount: performance.getEntriesByType('resource').length
};
```

---

## accessibility_tree.json — WCAG + element snapshot

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_full",
  "captured_at": "2026-06-09T14:30:08Z",
  "url": "https://<instance>.canvasmedical.com/",
  "wcag_level": "AA",
  "violations": [
    {
      "id": "vio_001",
      "wcag_criterion": "1.1.1",
      "severity": "error",
      "element": "img.chart-svg",
      "description": "Image missing alt text",
      "fix": "Add aria-label or role='img' with aria-label to the SVG element"
    }
  ],
  "tree_snapshot": {
    "interactive_elements": [],
    "headings": [],
    "landmarks": [],
    "images": [],
    "forms": []
  },
  "summary": {
    "total_violations": 0,
    "errors": 0,
    "warnings": 0,
    "passed_checks": 0
  }
}
```

---

## diff_report.json — Figma visual comparison

```json
{
  "schema_version": "1.0",
  "session_id": "2026-06-09T14-30-00Z_figma-reference",
  "compared_at": "2026-06-09T14:35:00Z",
  "reference": {
    "source": "figma",
    "file_key": "abc123",
    "file_name": "Cardiometabolic Tracker Design",
    "node_id": "12:34",
    "node_name": "Chart Modal — Good Responder",
    "screenshot_path": "figma-reference/reference_node.png"
  },
  "actual": {
    "source": "browser",
    "screenshot_path": "screenshots/002_chart_modal.png",
    "url": "https://<instance>.canvasmedical.com/",
    "patient": "Lori Collins"
  },
  "differences": [
    {
      "id": "diff_001",
      "severity": "major",
      "element": "baseline reference line",
      "expected": "dashed horizontal line at y=248lb",
      "actual": "line not visible",
      "likely_cause": "stroke-dasharray not applied",
      "suggested_fix": "Check d3 line generator — add .attr('stroke-dasharray', '6,4')"
    }
  ],
  "summary": {
    "total_differences": 1,
    "major": 1,
    "minor": 0,
    "cosmetic": 0,
    "match_score_pct": 94,
    "verdict": "needs_fix"
  }
}
```
