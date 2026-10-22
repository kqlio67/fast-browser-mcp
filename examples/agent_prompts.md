# Fast Browser MCP: Example Agent Prompts

Copy-paste prompt recipes designed to maximize the performance of AI agents using Fast Browser MCP.

---

## 1. High-Speed Research & Content Extraction

**Extract content with minimum token consumption:**
```markdown
Use fast-browser to navigate to https://news.ycombinator.com. 
Take a compact snapshot to find the top 5 stories, then batch-extract the headlines and links using element refs. 
Do not dump raw HTML.
```

**Bypass Cloudflare & Anti-Bot Protection:**
```markdown
Use fast-browser with stealth mode enabled. Navigate to [target URL]. 
Use trusted hardware clicks (trusted: true) to interact with any verification checkboxes. 
Wait for network idle and take a visual screenshot to confirm access.
```

---

## 2. Multi-Step Form Automation

**Fill complex multi-field form locally in a single round-trip:**
```markdown
Navigate to https://example.com/register.
First, take a snapshot to discover input handles.
Then, execute a single browser_batch containing:
1. Paste username into the username field
2. Paste email into the email field
3. Paste password into the password field
4. Trusted click on the submit button
5. Wait for network idle
6. Return the resulting page snapshot
```

---

## 3. Reverse Engineering & Network Analysis

**Map hidden API endpoints and WebSocket streams:**
```markdown
Connect fast-browser to my active Chrome session on port 9222.
Navigate to [target web app].
Perform a test interaction, then inspect browser_network_requests for POST/GraphQL calls.
Fetch the JSON response body using browser_network_get_response and check browser_websocket_messages for live packet frames.
```

---

## 4. Electron / Antigravity IDE Automation

**Control and inspect the running Electron application:**
```markdown
Find the active DevTools port for Antigravity (or use browser_connect to port 41039).
List open windows with browser_list_tabs.
Capture a compact snapshot of the IDE interface and inspect the active editor or conversation state.
```

---

## 5. Session State Persistence

**Save and restore login sessions across runs:**
```markdown
Log in to [web service].
Once authentication is complete, use browser_export_session to export cookies and local storage to "auth_session.json".
When starting a new session, use browser_import_session with "auth_session.json" to restore the authenticated state without logging in again.
```
