# Fast-Browser MCP: LLM Best Practices & Instructions

Welcome to the `fast-browser-mcp`! This WebMCP server exposes powerful browser automation capabilities to LLMs. To maximize reliability, especially on modern, dynamic websites, LLMs should adhere to the following best practices.

## 1. Handling Dynamic Content

Modern web pages render content asynchronously. Elements may not be immediately present in the DOM after a page load or interaction.

*   **Never assume immediate presence:** After navigating or clicking, the target element might take time to appear.
*   **Observe and verify:** Use tools to observe the DOM state and confirm the desired elements are visible before attempting to interact with them.
*   **Handle layout shifts:** Elements can move as resources load. Wait for the page layout to stabilize.

## 2. Emphasize `wait_for_network_idle`

The most common source of flakiness in browser automation is interacting with a page before it has finished fetching necessary resources.

*   **Use aggressively:** Always use the `wait_for_network_idle` capability (e.g., `browser_wait_for_network_idle`) after calling `browser_navigate`, clicking links, submitting forms, or performing any action that triggers asynchronous data loading.
*   **Why it matters:** This ensures all background XHR/fetch requests, scripts, and stylesheets have settled, significantly reducing race conditions and "element not found" errors.

## 3. Emphasize `browser_fill_form`

When inputting data into forms, prioritize specialized form-filling tools over manual, low-level interactions.

*   **Prefer `browser_fill_form`:** Whenever you need to populate inputs, use `browser_fill_form` instead of chaining multiple `browser_click` and `browser_press_key` commands.
*   **Reliability:** Form-filling capabilities are designed to handle complex logic, such as waiting for input readiness, clearing existing values, and triggering necessary validation events (like `change` or `blur`).

## 4. WebMCP Core Principles

*   **Stateful Execution:** The browser is a stateful application. Be mindful of your active tab, session state, and stored cookies.
*   **Resource Management:** Close tabs when you are done with them to free up memory.
*   **Targeted Extraction:** Execute JavaScript in the page context for precise data extraction, rather than dumping large, unparsed HTML payloads.
*   **Resilience:** Expect failures on the web (e.g., popups, captchas, varying layouts). Build retry logic and fallback strategies into your workflows.
