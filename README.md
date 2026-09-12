# ⚡ Fast Browser MCP

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![MCP Version](https://img.shields.io/badge/MCP%20Spec-2024--11--05-orange.svg)](https://modelcontextprotocol.io/)
[![Protocol](https://img.shields.io/badge/CDP-Native%20WebSocket-purple.svg)](https://chromedevtools.github.io/devtools-protocol/)
[![Version](https://img.shields.io/badge/version-0.7.0-blue.svg)](https://github.com/kqlio67/fast-browser-mcp)

Universal, ultra-fast **Model Context Protocol (MCP)** server and command-line interface for browser automation powered directly by the **Chrome DevTools Protocol (CDP)**.

Engineered specifically to eliminate the two biggest bottlenecks in AI web agents: **round-trip LLM inference latency** and **context window token bloat**.

---

## 🚀 Why Fast Browser MCP?

Traditional AI browser tools suffer from severe limitations:
- **Round-trip Latency:** Each individual action (click, type, scroll) requires an entire round-trip to the language model (~3–5 seconds per step). A 5-step form fill can take 25–40 seconds.
- **Context Bloat:** Dumping entire raw HTML trees consumes 10,000–50,000 tokens per step.
- **Blind to Shadow DOM:** Chrome internal pages (`chrome://settings`, `chrome://extensions`) and modern Web Components are invisible to standard `document.querySelector` tools.
- **Anti-Bot Roadblocks:** Headless browsers frequently trigger Cloudflare, Captchas, and bot challenges.

**Fast Browser MCP solves all of this:**

| Feature | Fast Browser MCP | Standard Browser MCPs |
|---|---|---|
| **Multi-Action Batching (`browser_batch`)** | **Local execution in ~500ms** for 5–10 actions | 20–30 seconds (1 LLM turn per action) |
| **Snapshot Context Cost** | **< 150 tokens** via numbered `@ref` tree | 10,000–50,000 tokens (raw HTML/DOM) |
| **Shadow DOM & Web Components** | **Deep recursive traversal** into all `shadowRoot` levels | ❌ Incomplete or completely blind |
| **Chrome System Pages** | Full control over `chrome://settings`, `chrome://extensions`, etc. | ❌ Unsupported |
| **Extension Management** | List, enable, disable, reload, and inspect extensions | ❌ Unsupported |
| **Real Browser Integration** | Attaches to active Chrome session on port 9222 (bypasses Cloudflare) | Often isolated / detected headless |
| **Reverse Engineering & Traffic** | Live WebSocket frames, XHR request/response bodies, cookie extraction | Usually basic console logs only |

---

## 🌟 Core Highlights

### 1. 🏎️ Ultra-Fast Batch Execution (`browser_batch`)
Execute an entire pipeline of actions locally in a single MCP round-trip:
```json
{
  "steps": [
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "fill", "ref": "@1", "text": "agent@example.com"},
    {"action": "fill", "ref": "@2", "text": "secret123"},
    {"action": "click", "ref": "@3"},
    {"action": "wait", "ms": 500},
    {"action": "snapshot"}
  ]
}
```
*Result: Executed entirely over direct local WebSocket in ~600ms total!*

### 2. 🏷️ Token-Efficient Numbered `@ref` Snapshot
Captures a compact accessibility tree with numbered target handles (`@1`, `@2`, ...). Intelligently identifies non-textual UI elements:
- Icons, SVG graphics, and title labels
- CSS `background-image` sprites (e.g. `bg:quest1.png`)
- ARIA roles, input states, and placeholder texts
- Filters out internal presentation noise (`cr-ripple`, `path`, `cr-icon` inside buttons)

```text
=== Page: Extensions ===
URL: chrome://extensions/

--- Interactive Elements (12 found) ---
@1 [button] "Search extensions"
@2 [input] [type=search]
@3 [button] [ checked]
@4 [button] "Load unpacked"
@5 [button] "Pack extension"
@6 [button] "Update"
@7 [menuitem] "My extensions" -> /
@8 [menuitem] "Keyboard shortcuts" -> /shortcuts
@9 [button] "Details"
@10 [button] "Remove"
@11 [button] "Reload"
@12 [button] [ checked]
```

### 3. 🌐 Full Browser Window & System Management
- **Window Bounds:** Retrieve and set window states (`normal`, `minimized`, `maximized`, `fullscreen`) or exact pixel dimensions and coordinates.
- **System Pages:** Direct navigation to `chrome://settings`, `chrome://extensions`, `chrome://downloads`, `chrome://history`, `chrome://flags`, `chrome://version`, and more.
- **Extension Controls:** Query all installed Chrome extensions, enable/disable them, reload extensions, or open options and popup pages.
- **Download Management:** Automatically configure download paths without interactive prompt dialogs.
- **Permissions:** Programmatically grant or reset browser permissions (`clipboardReadWrite`, `notifications`, `geolocation`).

### 4. 🔬 Network & Real-Time WebSocket Inspection
- Inspect intercepted HTTP/XHR/Fetch requests, headers, and POST payloads.
- Fetch raw response bodies (JSON, HTML, binary).
- Real-time **WebSocket frame capture** (`sent` / `received`), critical for game automation, real-time sync, and bot development.
- One-click traffic dump export to structured JSON.

---

## 📦 Installation

### Requirements
- Python 3.10 or newer
- Google Chrome, Chromium, or Brave

```bash
# Clone the repository
git clone https://github.com/kqlio67/fast-browser-mcp.git
cd fast-browser-mcp

# Install dependencies
pip install -r requirements.txt

# (Optional) Install editable package
pip install -e .
```

---

## ⚙️ Quickstart & Setup

### 1. Launch Chrome with Remote Debugging
Start your browser with `--remote-debugging-port=9222`:

**Linux:**
```bash
google-chrome --remote-debugging-port=9222 &
# Or if using Chromium / Helium:
chromium --remote-debugging-port=9222 &
```

**macOS:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &
```

**Windows:**
```cmd
chrome.exe --remote-debugging-port=9222
```

*(Optional: Use `--user-data-dir="/tmp/chrome_dev_session"` to run alongside your personal browser profile without conflicts).*

---

### 2. Connect to Your MCP Client

#### Google Antigravity
```bash
agy mcp add --env PYTHONPATH=/path/to/fast-browser-mcp fast-browser python3 -m fast_browser.server
```

#### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "fast-browser": {
      "command": "python3",
      "args": ["-m", "fast_browser.server"],
      "env": {
        "PYTHONPATH": "/path/to/fast-browser-mcp"
      }
    }
  }
}
```

#### Cursor / Windsurf
Add Fast Browser MCP as an MCP stdio server executing:
- **Command:** `python3`
- **Args:** `["-m", "fast_browser.server"]`
- **Environment:** `PYTHONPATH=/path/to/fast-browser-mcp`

---

## 🛠️ Complete Tool Reference (40+ Tools)

### 📑 Tab & Navigation
| Tool | Description |
|---|---|
| `browser_list_tabs` | List all open browser tabs (ID, title, URL) |
| `browser_select_tab` | Switch active connection to a tab by title or URL query |
| `browser_new_tab` | Open a new tab with a given URL |
| `browser_close_tab` | Close a tab by target ID (or close current tab) |
| `browser_navigate` | Navigate active tab to a URL |
| `browser_reload` | Reload the page (with optional `ignore_cache` option) |
| `browser_back` | Navigate backward in browser history (back button) |
| `browser_forward` | Navigate forward in browser history (forward button) |
| `browser_history` | Retrieve full tab navigation history entries and current position |

### 🎯 Interaction & Actions
| Tool | Description |
|---|---|
| `browser_click` | Click an element by snapshot ref (`@1`, `@2`) or CSS selector |
| `browser_fill` | Type text into an input element by ref or CSS selector |
| `browser_press_key` | Dispatch keyboard key event (`Enter`, `Escape`, `Tab`, `ArrowDown`, etc.) |
| `browser_scroll` | Scroll page by $(\Delta x, \Delta y)$ or scroll element into view |
| `browser_mouse` | Advanced mouse operations: `double_click`, `right_click`, `move`, `drag_and_drop` |
| `browser_find_in_page` | Find text on page (Ctrl+F): count matches, extract snippets, and auto-scroll |
| `browser_clipboard` | Read or write to the system clipboard (`read`, `write`) |
| `browser_upload_file` | Upload files natively into `<input type='file'>` elements via CDP |

### 👁️ Inspection & Snapshots
| Tool | Description |
|---|---|
| `browser_snapshot` | Compact, token-efficient A11y tree with `@ref` markers, Shadow DOM traversal, optional CSS selector scoping, and viewport filtering |
| `browser_get_html` | Extract full document `outerHTML` or save directly to a file |
| `browser_screenshot` | Capture viewport, element clip, or full-page scrollable screenshot (PNG/JPEG) |
| `browser_print_to_pdf` | Print page to PDF file with landscape/background options |
| `browser_eval` | Evaluate arbitrary JavaScript expressions in the page context |

### ⚡ High-Speed Batch Runner & Resilience
| Tool | Description |
|---|---|
| `browser_batch` | **Ultra-fast local batch execution**: runs an array of actions in a single round-trip without model latency. Supports: `navigate`, `click`, `fill`, `press_key`, `scroll`, `hover`, `mouse`, `wait`, `wait_idle`, `block_resources`, `metrics`, `geolocation`, `timezone`, `permissions`, `cleanup_tabs`, `eval`, `extract`, `snapshot`, `screenshot`, `pdf`, `window`, `system_page`, `extensions`, `back`, `forward`, `history`, `stealth`, `throttling`, `theme`, `zoom`, `mute`, `find`, `clipboard`, `indexeddb`, `ssl_ignore`, etc. |
| `browser_wait_for_network_idle` | Wait until all in-flight network requests cease for a stable duration |
| `browser_block_resources` | Block images, video/audio media, web fonts, or tracking scripts/ads for up to 10x page load speedup |
| `browser_cleanup_tabs` | Automatically close blank (`about:blank`), stale, or pattern-matching tabs to free RAM |
| `browser_performance_metrics` | Live memory profiling: JS heap used (MB), DOM nodes, layouts, and task durations |

### 📡 Network, WebSockets & Storage
| Tool | Description |
|---|---|
| `browser_network_requests` | List captured HTTP/XHR/Fetch requests filtered by type or URL pattern |
| `browser_network_get_response` | Inspect headers, POST payload, and retrieve server response bodies |
| `browser_websocket_messages` | Monitor real-time WebSocket frames (`sent` / `received`) |
| `browser_get_cookies` | Retrieve all cookies and authentication tokens for current origin |
| `browser_set_cookie` | Inject cookies into the browser context |
| `browser_get_storage` | Inspect and dump `localStorage` and `sessionStorage` |
| `browser_get_indexeddb` | Inspect all IndexedDB databases, version numbers, and object store names |
| `browser_clear_storage` | Clear browser cache and/or cookies |
| `browser_export_traffic` | Export captured HTTP & WebSocket traffic into a structured JSON file |

### 🖥️ Browser & System Management
| Tool | Description |
|---|---|
| `browser_window` | Inspect or set window bounds (coordinates, width, height) and state (`maximized`, `minimized`, `fullscreen`, `normal`) |
| `browser_open_system_page` | Open or switch to Chrome system pages (`settings`, `extensions`, `downloads`, `history`, `flags`, etc.) |
| `browser_list_extensions` | Query all installed Chrome extensions (IDs, names, versions, enabled status) |
| `browser_extension_action` | Manage extensions: `enable`, `disable`, `reload`, `options`, `popup` |
| `browser_add_preload_script` | Inject custom JavaScript evaluating before page scripts load (hooks / Tampermonkey) |
| `browser_remove_preload_script` | Remove a previously registered preload script by identifier |
| `browser_stealth_mode` | Toggle anti-bot stealth overrides (`navigator.webdriver`, plugins, languages) |
| `browser_network_throttling` | Emulate network profiles (`offline`, `slow3g`, `fast3g`, `4g`, `none`) or custom latency/bandwidth |
| `browser_set_media_theme` | Emulate color scheme on page: `dark`, `light`, `no-preference` |
| `browser_set_page_zoom` | Adjust page zoom scale (e.g. `0.75`, `1.0`, `1.25`, `1.5`) |
| `browser_mute_tab` | Mute or unmute all audio/video media playback on the active tab |
| `browser_set_ignore_certificate_errors` | Bypass or enforce SSL/TLS certificate warnings on HTTPS websites |
| `browser_system_info` | Inspect Chrome version, V8 engine, User-Agent, and memory metrics |
| `browser_set_download_path` | Set download folder and allow downloads without browser dialogs |
| `browser_grant_permissions` | Grant or reset permissions (`clipboardReadWrite`, `notifications`, `geolocation`) |
| `browser_set_geolocation` | Override device GPS coordinates (`latitude`, `longitude`, `accuracy`) |
| `browser_set_timezone` | Emulate local timezone (e.g. `Europe/Kyiv`, `America/New_York`) |
| `browser_console_logs` | View captured console logs (`console.log`, `error`, `warn`, unhandled exceptions) |
| `browser_set_viewport` | Configure viewport dimensions and mobile device emulation |
| `browser_set_user_agent` | Override User-Agent header |
| `browser_set_headers` | Inject custom HTTP headers into all outgoing requests |

---

## 💻 CLI Usage

Fast Browser MCP also includes a complete standalone CLI for manual operations and shell scripting:

```bash
# List open tabs
python3 -m fast_browser.cli list-tabs

# Take a snapshot of a tab
python3 -m fast_browser.cli --tab mmobitva snapshot

# Navigate history (Back & Forward)
python3 -m fast_browser.cli back
python3 -m fast_browser.cli forward
python3 -m fast_browser.cli history

# Activate stealth mode (hide automation markers)
python3 -m fast_browser.cli stealth

# Emulate network conditions (Slow 3G, Offline, or reset)
python3 -m fast_browser.cli throttling slow3g
python3 -m fast_browser.cli throttling none

# Emulate dark mode theme
python3 -m fast_browser.cli theme dark

# Adjust page zoom level (125%)
python3 -m fast_browser.cli zoom 1.25

# Mute tab audio
python3 -m fast_browser.cli mute

# Search text on page (Ctrl+F)
python3 -m fast_browser.cli find "SearchQuery"

# Read/write clipboard
python3 -m fast_browser.cli clipboard --write "Hello from Fast Browser"
python3 -m fast_browser.cli clipboard

# Inspect IndexedDB databases
python3 -m fast_browser.cli indexeddb

# Inspect browser window geometry
python3 -m fast_browser.cli window

# Maximize browser window
python3 -m fast_browser.cli window --state maximized

# Open Chrome Settings or Extensions
python3 -m fast_browser.cli system-page settings
python3 -m fast_browser.cli extensions

# Run high-speed batch actions
python3 -m fast_browser.cli --tab mytab batch '[
  {"action": "stealth", "enabled": True},
  {"action": "theme", "theme": "dark"},
  {"action": "snapshot"},
  {"action": "click", "ref": "@2"},
  {"action": "wait", "ms": 200},
  {"action": "snapshot"}
]'
```

---

## 🧪 Testing

Run the automated test suite against a running Chrome instance on port 9222:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
