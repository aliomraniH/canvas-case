# Figma Integration Reference

Two distinct uses of Figma in this skill:
1. **Storage** — upload session screenshots into a Figma file for review
2. **Reference** — use a Figma design as source of truth, compare live screenshots against it

---

## Figma as Storage (upload mode)

Run after any debug session to package screenshots into a Figma file.

### Step 1 — Ask new vs existing
> "Upload screenshots to Figma? Options: `new file` / `existing file [paste URL]` / `skip`"

**New file:**
```
create_new_file(
  editorType = "design",
  fileName   = "Debug Session — {session_id}",
  planKey    = <from whoami>
)
```
Show returned URL to user: "Created: {url}"

**Existing file:** extract `fileKey` from pasted URL.
Show file name back: "Adding to: **{file_name}**"

### Step 2 — Upload screenshots in batches of 5
```
upload_assets(fileKey, count=min(5, remaining), batchCommit=true)
```
POST each PNG:
```bash
curl -X POST "{uploadUrl}" -H "Content-Type: image/png" --data-binary @"{path}"
```
Call `commitUrl` once after all POSTs in batch.

### Step 3 — Label and arrange with use_figma
```javascript
const page = figma.currentPage;
const frames = page.children.filter(n => n.type === 'FRAME');
const names = {SCREENSHOT_NAMES};  // pass from session context

const COLS = 3, GAP = 32, W = 800, H = 520;
frames.forEach((f, i) => {
  f.name = names[i] || f.name;
  f.x = (i % COLS) * (W + GAP);
  f.y = Math.floor(i / COLS) * (H + 56 + GAP);
  f.resize(W, H);

  // Add filename label above frame
  const label = figma.createText();
  await figma.loadFontAsync({ family: 'Inter', style: 'Regular' });
  label.characters = names[i] || 'screenshot';
  label.fontSize = 13;
  label.x = f.x;
  label.y = f.y - 24;
  page.appendChild(label);
});
```

### Step 4 — Add session summary sticky note
```javascript
const note = figma.createSticky();
note.text.characters = `Session: {session_id}\nMode: {mode}\nPassed: {passed} / Failed: {failed}\n\nFailed tests:\n{failures_list}`;
note.x = -480;
note.y = 0;
```

### Step 5 — Update session.json
```json
"figma": {
  "upload_file_key": "abc123",
  "upload_file_url": "https://figma.com/design/abc123/Debug-Session-..."
}
```

---

## Figma as Reference (comparison mode)

Use when you want to verify that the live browser output matches
the intended design. The Figma file is the source of truth.

### Specifying the reference — 3 methods

**Method A — Paste a URL (any Figma node)**
User provides: `https://figma.com/design/abc123/MyFile?node-id=12-34`
Extract: `fileKey=abc123`, `nodeId=12:34`

**Method B — Named frame**
User says: "use the frame called 'Chart Modal — Good Responder'"
Search the file:
```javascript
// use_figma to search for the frame
const frames = figma.currentPage.findAll(n =>
  n.type === 'FRAME' && n.name.includes('Chart Modal')
);
return frames.map(f => ({ id: f.id, name: f.name }));
```
Show results and ask user to confirm which one.

**Method C — Auto-detect**
Match current test context to Figma frame names.
Steps:
1. Get session context: `context.test_description`, `context.patient_name`
2. Search Figma file for frames with similar names:
   ```javascript
   figma.currentPage.findAll(n =>
     n.type === 'FRAME' &&
     (n.name.toLowerCase().includes('chart') ||
      n.name.toLowerCase().includes('modal') ||
      n.name.toLowerCase().includes('tracker'))
   ).map(f => ({ id: f.id, name: f.name }))
   ```
3. Show top 3 matches and let user confirm, or auto-select highest match.

### Generating tests from Figma reference

When `figma-reference` mode is selected BEFORE a test run
(not after), the Figma design drives what to test:

1. Get `get_screenshot` of the reference node
2. Analyze the reference screenshot:
   ```
   "Describe every UI element visible in this Figma design.
    List: headings, buttons, chart elements, labels, colors, layout.
    Output as a structured JSON list of assertions."
   ```
3. Generate assertions from the analysis:
   ```json
   [
     { "element": "modal heading", "assertion": "text equals 'Weight Trajectory'", "selector": "[role='heading']" },
     { "element": "chart SVG",     "assertion": "svg is present",                   "selector": "svg" },
     { "element": "baseline line", "assertion": "dashed line stroke is visible",    "js": "document.querySelectorAll('line[stroke-dasharray]').length > 0" },
     { "element": "TBWL label",    "assertion": "text contains '%' and 'TBWL'",     "js": "document.querySelector('svg').textContent.includes('TBWL')" }
   ]
   ```
4. Write assertions to `figma-reference/generated_assertions.json`
5. Run the actual test against these assertions
6. Compare live screenshots to Figma reference screenshot
7. Write diff to `figma-reference/diff_report.json`

### Running the visual comparison

After both reference (Figma) and actual (browser) screenshots exist:

Pass both images to Claude vision:
```
"I have two screenshots:
 REFERENCE: [figma_reference_node.png]
 ACTUAL: [browser_screenshot.png]

 Compare them and list every visual difference.
 For each difference output:
 - element name
 - severity: major | minor | cosmetic
 - what is different
 - likely cause in code
 - suggested fix"
```

Parse Claude's response into `diff_report.json` structure.
Update `session.json` with diff summary.

---

## Finding sessions to upload later

Agents can find all sessions without a Figma upload:
```python
import os, json, glob

for path in glob.glob('.workspace_state/debug/*/session.json'):
    with open(path) as f:
        s = json.load(f)
    if not s['figma']['upload_file_key']:
        print(s['session_id'], '— not yet uploaded to Figma')
```
