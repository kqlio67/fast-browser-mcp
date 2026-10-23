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
- `browser_snapshot` captures a compact accessibility tree with numbered target handles (`@1`, `@2`, `@3` or `@e1`, `@e2`) in **under 200 tokens**.
- Identifies icons, ARIA roles, input states, and recurses deeply into **Shadow DOM** and Web Components.
- Use the `@ref` handle directly in follow-up actions: `browser_click(ref="@2")`, `browser_fill(ref="@1", text="...")`.

### 3. High-Fidelity & Stealth Input (`trusted: true`, `paste: true`, `press_enter: true`)
When interacting with modern frameworks or anti-bot protected sites (Cloudflare Turnstile, reCAPTCHA, Datadome):
- **Clicks:** Use `trusted: true` (e.g. `browser_click(ref="@1", trusted=true)`). This dispatches real hardware-level mouse events (`Input.dispatchMouseEvent`) with `isTrusted === true`.
- **Coordinates:** If selectors or refs are unavailable, dispatch coordinate clicks: `browser_mouse(action="click", x=100, y=200)` or batch `{"action": "click", "x": 100, "y": 200}`.
- **Text Entry:** Use `paste: true` in `browser_fill` or the `"paste"` action in `browser_batch`. This uses `Input.insertText` to correctly trigger native `beforeinput` and `input` events that React 16+, Vue, and ContentEditable fields depend on.
- **Immediate Submit:** Use `press_enter: true` in `browser_fill` to submit search fields or single-input forms instantly.

### 4. Dynamic Connection & Session Persistence
You are not locked into a single browser port or transient sessions:
- Connect to user's active Chrome/Helium: `browser_connect(port=9222)`.
- Connect to Electron apps / Antigravity IDE GUI: `browser_connect(port=<devtools_port>)`.
- Launch an isolated browser on demand with persistent profile: `browser_launch(headless=True, profile_name="work_session")`.
- Export/Import complete browser session state: `browser_export_session()` and `browser_import_session()`.

### 5. Settle Network State & Handle Overlays
Web applications load data asynchronously via Fetch/XHR.
- Call `browser_wait_for_network_idle` (or include `{"action": "wait_idle"}` in your batch) after navigation or button clicks before attempting to interact with elements.
- Use `browser_wait_for(selector="...")` to wait for specific dynamic DOM elements.
- Dismiss cookie consent overlays with `browser_dismiss_banners()` or batch `{"action": "dismiss_banners"}`.

---

## 🛠️ Tool Quick Reference

| Task | Primary Tool | Batch Action |
|---|---|---|
| Multi-action pipeline | `browser_batch(steps=[...])` | — |
| Compact page inspect | `browser_snapshot(in_viewport=...)` | `{"action": "snapshot"}` |
| Hardware mouse click | `browser_click(ref="@1", trusted=True)` | `{"action": "click", "ref": "@1", "trusted": true}` |
| Coordinate click / hover | `browser_mouse(action="click", x=..., y=...)` | `{"action": "click", "x": 100, "y": 200}` |
| Fast input / form fill | `browser_fill_form(elements=[...])` | `{"action": "fill_form", "elements": [...]}` |
| Instant paste text | `browser_fill(ref="@1", text="...", paste=True)` | `{"action": "paste", "ref": "@1", "text": "..."}` |
| Fill & press Enter | `browser_fill(ref="@1", text="...", press_enter=True)` | `{"action": "fill", "ref": "@1", "text": "...", "press_enter": true}` |
| Full visual screenshot | `browser_screenshot(full_page=...)` | `{"action": "screenshot"}` |
| Wait for network calm | `browser_wait_for_network_idle()` | `{"action": "wait_idle"}` |
| Wait for element | `browser_wait_for(selector=...)` | `{"action": "wait_for", "selector": "..."}` |
| Dismiss popups/banners | `browser_dismiss_banners()` | `{"action": "dismiss_banners"}` |
| Save / Restore session | `browser_export_session()`, `browser_import_session()` | `{"action": "export_session"}` |
| Wait for downloaded file | `browser_wait_for_download(directory=...)` | `{"action": "wait_download"}` |
| API / Traffic analysis | `browser_network_requests()`, `browser_websocket_messages()` | `{"action": "network_requests"}` |
| Inspect CSS / Events | `browser_get_css_styles(ref="@1")` | `{"action": "css_styles"}` |
| Reconnect to port | `browser_connect(port=...)` | — |
| Launch standalone Chrome | `browser_launch(headless=True, profile_name=...)` | — |
| Close browser process | `browser_close_browser()` | — |

---

## 📦 MCP Resources & Prompts

- **Resources:**
  - `browser://tabs` — List of all open tabs
  - `browser://active/snapshot` — Token-efficient text accessibility snapshot of active page
  - `browser://active/dom` — Full HTML of active page
  - `browser://console` — Captured console logs
  - `browser://network` — Captured HTTP/WebSocket traffic summary
- **Prompts:**
  - `web-research` — Guided systematic browsing and extraction workflow
  - `form-automation` — Guided multi-step form inspection and filling workflow
  - `network-debugger` — Guided reverse engineering of network APIs and WebSocket streams

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
5. **Clean Up:** Call `browser_close_tab`, `browser_cleanup_tabs`, or `browser_close_browser` when finished.
