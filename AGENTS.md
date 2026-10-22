# Agent Guidelines: Fast Browser MCP

Welcome, AI coding agent. When modifying, maintaining, or expanding **Fast Browser MCP**, adhere to the instructions, architectural principles, and verification workflows defined below.

---

## 1. Project Overview & Philosophy

**Fast Browser MCP** is a high-performance Model Context Protocol (MCP) server and CLI for browser automation powered directly by the **Chrome DevTools Protocol (CDP)** over native WebSockets.

### Core Value Propositions:
1. **Ultra-Low Latency:** Multi-action batching (`browser_batch`) executes multi-step pipelines locally in ~500ms, eliminating costly per-step LLM inference round-trips.
2. **Token Efficiency:** The `@ref` accessibility snapshot tree (`browser_snapshot`) provides full interactive context in <150–300 tokens, avoiding 10k–50k raw HTML token dumps.
3. **Deep Shadow DOM Support:** Recursive penetration into all `shadowRoot` levels allows full automation of Chrome system pages (`chrome://`) and modern Web Components.
4. **Stealth & High-Fidelity Input:** Hardware-level mouse/keyboard events (`Input.dispatchMouseEvent`, `Input.insertText`) with `isTrusted === true` to bypass Cloudflare Turnstile and anti-bot systems.
5. **Zero Heavyweight Dependencies:** Built strictly on native Python async primitives (`websockets`, `requests`, `aiofiles`). Do NOT introduce Selenium, Playwright, or nodriver.

---

## 2. Environment & Tooling

The project uses Python 3.10+ and `uv` for environment management.

- **Virtual Environment:** `.venv/`
- **Python Executable:** `.venv/bin/python`
- **Test Runner:** `.venv/bin/pytest`
- **Linter & Formatter:** `.venv/bin/ruff`
- **Type Checker:** `.venv/bin/mypy`

### Common Commands:
```bash
# Run the test suite
.venv/bin/pytest -v

# Run fast unit tests only
.venv/bin/pytest tests/test_server.py tests/test_launcher.py

# Run linting check
.venv/bin/ruff check fast_browser tests

# Run static type checking
.venv/bin/mypy fast_browser

# Run CLI verification
PYTHONPATH=. .venv/bin/python -m fast_browser.cli --help
PYTHONPATH=. .venv/bin/python -m fast_browser.cli validate-env
```

---

## 3. Critical MCP Protocol & Stdio Rules

> [!CAUTION]
> **NEVER print to `stdout` from runtime server code or library paths.**
> In MCP stdio mode, `stdout` is strictly reserved for JSON-RPC messages (NDJSON or Content-Length framed). Any accidental `print(...)` or unhandled stdout emission will instantly corrupt the MCP transport and disconnect the client.
> - Use `logging.getLogger("fast_browser.*")` for all server-side logging.
> - Server logging is directed to `sys.stderr` by default.

---

## 4. Architectural Rules & Standards

### Batching Parity
Any new interactive capability or page interaction added to `fast_browser/server.py` **must also be supported as an action in `fast_browser/batch.py`** (`BatchRunner`). Agents should always be able to execute actions in batches.

### Multimodal Image Responses
When returning visual screenshots or media from MCP tools:
- If `save_path` is specified: write to disk and return text confirmation.
- If `save_path` is omitted: return native MCP `{"type": "image", "data": "<base64>", "mimeType": "image/png"}` content blocks inside `_mcp_content`.

### Hardware vs. Synthetic Input
- For clicking: default to `cdp.trusted_click(x, y)` (`Input.dispatchMouseEvent`) when screen coordinates are available (`isTrusted: true`), with graceful fallback to DOM `.click()`.
- For typing: prefer `cdp.insert_text(text)` (`Input.insertText`) to trigger native `beforeinput` and `input` events that React, Vue, and Angular listeners intercept accurately.

### Sandboxing & Path Validation
All tools that accept file paths for reading or writing must validate paths through `server.validate_path(path, for_write=...)` or `batch.validate_path(...)` to strictly enforce `FAST_BROWSER_ALLOWED_DIR` boundaries and prevent path traversal.

### Browser Process Safety
- Do not pass `--disable-gpu` unconditionally; doing so forces SwiftShader software rendering and triggers anti-bot detections (CreepJS/Sannysoft).
- Pass `--no-sandbox` only when running as root or inside Docker/containers (`launcher.sandbox_must_be_disabled()`).

---

## 5. Verification Checklist for Changes

Before submitting or committing any code changes:
1. `All checks passed!` with `.venv/bin/ruff check fast_browser tests`
2. `Success: no issues found` with `.venv/bin/mypy fast_browser`
3. All tests pass with `.venv/bin/pytest`
4. If tools were added or changed: update tool counts and test schemas in `tests/test_server.py`.
5. Keep git commits conventional (`feat: ...`, `fix: ...`, `docs: ...`, `chore: ...`).
