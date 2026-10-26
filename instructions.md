# Fast-Browser MCP: LLM Best Practices & Instructions

Welcome to **Fast Browser MCP**! This high-performance Model Context Protocol (MCP) server gives LLMs direct, ultra-low latency browser automation powered by the **Chrome DevTools Protocol (CDP)** over native WebSockets.

To maximize execution speed, minimize token burn, and maintain bulletproof reliability on complex modern web applications, adhere strictly to these core principles and operational workflows.

---

## ⚡ 1. The Cardinal Rule: Batch First (`browser_batch`)

**Never execute sequential actions in separate LLM round-trips.**
Each individual MCP action (`navigate`, `wait`, `click`, `fill`) costs 3–5 seconds of LLM inference latency. A 5-step form fill in separate tool calls takes 25–40 seconds. `browser_batch` executes entire multi-step interaction pipelines locally in **~500ms** over direct WebSocket.

### When to Batch:
- Form completions (navigate ➔ wait ➔ fill fields ➔ click submit ➔ wait idle ➔ snapshot).
- Multi-step page interactions (click tab ➔ wait for element ➔ scroll ➔ snapshot).
- Routine setups (set viewport ➔ enable stealth ➔ navigate ➔ wait idle).

### Batching Example:
```json
{
  "steps": [
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "wait_idle", "timeout": 5},
    {"action": "fill", "ref": "@1", "text": "user@example.com"},
    {"action": "fill", "ref": "@2", "text": "secretPassword"},
    {"action": "click", "ref": "@3", "trusted": true},
    {"action": "wait_idle"},
    {"action": "snapshot"}
  ]
}
```

*Note: All 81 MCP tools have direct 1:1 action aliases supported in `browser_batch`.*

---

## 🎯 2. Token-Efficient Snapshots over Raw HTML

**Never dump full HTML unless explicitly writing an offline parser.**
- Dumping full HTML (`browser_get_html`) consumes **10,000 to 50,000 tokens** per page, exhausting context windows and confusing reasoning.
- `browser_snapshot` captures a compact accessibility tree with numbered target handles (`@1`, `@2`, `@3` or `@e1`, `@e2`) in **under 200 tokens**.
- Identifies element roles, button texts, input states, and **penetrates deeply into nested Shadow DOM** and Web Components (including `chrome://` system pages).
- Use the `@ref` handle directly in follow-up actions: `browser_click(ref="@2")`, `browser_fill(ref="@1", text="...")`.

---

## 🖱️ 3. High-Fidelity & Trusted Hardware Input

Modern single-page applications (React 16+, Vue 3, Angular) and anti-bot systems (Cloudflare Turnstile, reCAPTCHA, Datadome) ignore or block synthetic JavaScript events (`element.click()`, `input.value = ...`).

*   **Trusted Mouse Clicks:** Use `trusted: true` in `browser_click` or batch actions. This dispatches hardware-level mouse events (`Input.dispatchMouseEvent`) with `isTrusted === true`.
*   **Coordinate-Based Clicks:** When ref or CSS selectors are obstructed (e.g. custom canvases, overlays), pass coordinates: `browser_mouse(action="click", x=100, y=200)` or in batch: `{"action": "click", "x": 100, "y": 200}`.
*   **Native Text Insertion (`paste: true`):** Use `paste: true` in `browser_fill` or `"paste"` in `browser_batch`. This triggers native `Input.insertText`, firing `beforeinput` and `input` events that ContentEditable and modern frameworks require.
*   **Submit with Enter (`press_enter: true`):** When filling search boxes or single-field forms, set `press_enter: true` in `browser_fill` to submit immediately without a separate click step.

---

## ⏳ 4. Dynamic Content & Network Stabilization

The #1 source of automation flakiness is interacting with elements before asynchronous network requests or JavaScript rendering have finished.

*   **Settle Network Traffic:** Always call `browser_wait_for_network_idle` (or `{"action": "wait_idle"}` in batch) after navigating or submitting forms.
*   **Wait for Specific Elements:** When an element appears after an animation or background API call, use `browser_wait_for` (or `{"action": "wait_for", "selector": "#target"}`).
*   **Dismiss Annoying Overlays:** If cookie banners or GDPR popups block clicks, call `browser_dismiss_banners` or include `{"action": "dismiss_banners"}` in your batch.

---

## 📋 5. Form Automation: Atomic & Clean

When populating web forms:
*   **Prefer `browser_fill_form`:** Accepts an array of elements `[{"ref": "@1", "value": "..."}, {"ref": "@2", "value": "..."}]` and fills them atomically in one operation.
*   **Auto-ContentEditable Detection:** `browser_fill` automatically detects `contenteditable="true"` elements and uses native text insertion rather than standard input assignment.

---

## 💾 6. Session Persistence & Dynamic Connectivity

*   **Persistent Profiles:** To avoid repeating multi-factor authentication or logins across sessions, use a persistent profile: `browser_launch(profile_name="agent_work")` or CLI `--profile agent_work`.
*   **Session Export & Import:** Use `browser_export_session` to backup cookies, `localStorage`, `sessionStorage`, and current URL to disk. Restore anytime with `browser_import_session`.
*   **Dynamic Reconnection:** Fast Browser MCP is not locked to port 9222. Switch dynamically to any DevTools port (e.g. Electron apps, VS Code webviews, mobile emulators) using `browser_connect(port=<target_port>)`.

---

## 👁️ 7. Multimodal Vision Verification

When interacting with visually complex pages, charts, or maps:
*   Call `browser_screenshot` without `save_path` to receive an inline MCP image content block (`{"type": "image", "data": "<base64>", "mimeType": "image/png"}`).
*   Multimodal LLMs can inspect the screenshot visually to verify layout, render state, or solve visual challenges.

---

## 📦 8. MCP Resources & Prompts

Fast Browser MCP exposes real-time state via standard MCP Resources:
*   `browser://tabs`: Check currently open tabs and active targets.
*   `browser://active/snapshot`: Instant accessibility snapshot of the current page as clean text.
*   `browser://active/dom`: Raw HTML when source parsing is required.
*   `browser://console`: Captured console logs and errors.
*   `browser://network`: In-flight and completed HTTP/WebSocket traffic summary.

Use the built-in MCP Prompts (`web-research`, `form-automation`, `network-debugger`) for guided, resilient execution.

---

## 🔬 9. Web Reverse Engineering & Deep Inspection (REA Superpowers)

Fast Browser MCP incorporates advanced runtime reverse-engineering capabilities inspired by the **REA** (Reverse Engineer Anything) architecture:

*   **Native Event Listeners (`browser_get_event_listeners`):**
    Before clicking an unresponsive button or submit element, inspect its actual registered listeners via CDP `DOMDebugger`:
    ```json
    {"action": "get_event_listeners", "ref": "@1"}
    ```
    Returns callback function names, script URLs, line numbers, and registration flags (`passive`, `once`, `useCapture`).
*   **Standards-Compliant HAR 1.2 Export (`browser_export_traffic`):**
    Export captured sessions directly as standard HTTP Archive files:
    ```json
    {"file_path": "traffic.har", "format": "har", "redact_sensitive_headers": true}
    ```
    Open directly in Chrome DevTools (*Network -> Import HAR*), Postman, Fiddler, or REA offline reconstructors.
*   **Automatic Secrets Redaction:**
    `Authorization`, `Cookie`, `Set-Cookie`, `x-api-key`, passwords, and token query parameters are automatically redacted (`[REDACTED]`) to prevent accidental credential leakage in logs and archives.
*   **V8 Precise Code Coverage (`browser_observe_coverage`):**
    Discover exactly which JavaScript functions execute during interaction pipelines (e.g. Turnstile bypasses, client-side encryption, validation logic):
    ```json
    {
      "steps": [
        {"action": "start_coverage"},
        {"action": "click", "ref": "@2"},
        {"action": "stop_coverage"}
      ]
    }
    ```
*   **Deterministic Screenshot Comparison (`browser_compare_screenshots`):**
    Verify visual UI reactions without spending thousands of vision LLM inference tokens:
    ```json
    {"image1": "before.png", "image2": "after.png", "channel_threshold": 16}
    ```
    Returns status (`identical`, `different`), changed pixel percentage, and exact bounding box.
*   **CacheStorage & Service Worker Inspection (`browser_get_cache_storage`):**
    Inspect client-side Cache API storage, PWA cached assets, and offline responses. Also accessible via `browser_get_storage(storage_type="cache")`.
