---
name: fast-browser
description: Ultra-fast browser automation, web scraping, multi-step form completion, and network inspection using Fast Browser MCP. Prioritizes local batching (browser_batch) to eliminate LLM round-trip latency, token-efficient @ref snapshots (<150 tokens), trusted hardware input, and stealth anti-bot bypass.
---

# Fast Browser MCP Skill

This skill guides AI agents on orchestrating **Fast Browser MCP** for high-speed, token-efficient, and stealthy web automation.

---

## ⚡ The 5 Golden Rules of Fast Browser

### 1. Batch First (`browser_batch`)
**Never execute sequential actions in separate LLM round-trips.**
Each individual action (navigate, wait, click, type) costs 3–5 seconds of LLM latency. Use `browser_batch` to execute entire interaction pipelines locally in ~500ms over direct WebSocket.

```json
{
  "steps": [
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "wait_idle", "timeout": 5},
    {"action": "fill", "selector": "#username", "text": "agent@example.com"},
    {"action": "fill", "selector": "#password", "text": "secret123"},
    {"action": "click", "selector": "#submit-btn", "trusted": true},
    {"action": "wait_idle"},
    {"action": "snapshot"}
  ]
}
```

### 2. Snapshot Instead of Raw HTML (`browser_snapshot`)
**Never request full HTML dumps unless explicitly writing a parser.**
- Full HTML pages consume 10,000 to 50,000 context tokens.
- `browser_snapshot` captures a compact accessibility tree with numbered target handles (`@1`, `@2`, `@3`) in **under 200 tokens**.
- Identifies icons, ARIA roles, input states, and recurses deeply into **Shadow DOM** and Web Components.
- Use the `@ref` handle directly in follow-up actions: `browser_click(ref="@2")`, `browser_fill(ref="@1", text="...")`.

### 3. High-Fidelity & Stealth Input (`trusted: true`, `paste: true`)
When interacting with modern frameworks or anti-bot protected sites (Cloudflare Turnstile, reCAPTCHA, Datadome):
- **Clicks:** Use `trusted: true` (e.g. `browser_click(ref="@1", trusted=true)`). This dispatches real hardware-level mouse events (`Input.dispatchMouseEvent`) with `isTrusted === true`.
- **Text Entry:** Use `paste: true` in `browser_fill` or the `"paste"` action in `browser_batch`. This uses `Input.insertText` to correctly trigger native `beforeinput` and `input` events that React 16+, Vue, and ContentEditable fields depend on.

### 4. Dynamic Connection Switching (`browser_connect`)
You are not locked into a single browser port:
- Connect to user's active Chrome/Helium: `browser_connect(port=9222)`.
- Connect to Electron apps / Antigravity IDE GUI: `browser_connect(port=<devtools_port>)`.
- Launch an isolated browser on demand: `browser_launch(headless=True)`.

### 5. Always Settle Network State (`browser_wait_for_network_idle`)
Web applications load data asynchronously via Fetch/XHR. Always call `browser_wait_for_network_idle` (or include `{"action": "wait_idle"}` in your batch) after navigation or button clicks before attempting to interact with elements.

---

## 🛠️ Tool Quick Reference

| Task | Primary Tool | Batch Action |
|---|---|---|
| Multi-action pipeline | `browser_batch(steps=[...])` | — |
| Compact page inspect | `browser_snapshot(in_viewport=...)` | `{"action": "snapshot"}` |
| Hardware mouse click | `browser_click(ref="@1", trusted=True)` | `{"action": "click", "ref": "@1", "trusted": true}` |
| Fast input / form fill | `browser_fill_form(elements=[...])` | `{"action": "fill_form", "elements": [...]}` |
| Instant paste text | `browser_fill(ref="@1", text="...", paste=True)` | `{"action": "paste", "ref": "@1", "text": "..."}` |
| Full visual screenshot | `browser_screenshot(full_page=...)` | `{"action": "screenshot"}` |
| Wait for network calm | `browser_wait_for_network_idle()` | `{"action": "wait_idle"}` |
| Save / Restore session | `browser_export_session()`, `browser_import_session()` | `{"action": "export_session"}` |
| Wait for downloaded file | `browser_wait_for_download(directory=...)` | `{"action": "wait_download"}` |
| API / Traffic analysis | `browser_network_requests()`, `browser_websocket_messages()` | `{"action": "network_requests"}` |
| Inspect CSS / Events | `browser_get_css_styles(ref="@1")` | `{"action": "css_styles"}` |
| Reconnect to port | `browser_connect(port=...)` | — |
| Launch standalone Chrome | `browser_launch(headless=True)` | — |

---

## 📋 Recommended Agent Workflow

1. **Verify Connection:** Call `browser_list_tabs`. If no browser is reachable, call `browser_launch(headless=True)`.
2. **Navigate & Inspect:**
   - Execute a batch: `[{"action": "navigate", "url": "..."}, {"action": "wait_idle"}, {"action": "snapshot"}]`.
   - Read the returned numbered elements (`@1`, `@2`, `@3`...).
3. **Execute Interactions:**
   - Use `browser_batch` or `browser_fill_form` with the `@ref` identifiers from step 2.
   - For buttons, specify `"trusted": true`.
4. **Verify Result:** Check the resulting snapshot or call `browser_screenshot` for visual validation.
5. **Clean Up:** Call `browser_close_tab` or `browser_cleanup_tabs` when finished.
