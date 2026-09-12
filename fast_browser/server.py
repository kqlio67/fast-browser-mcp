import sys
import json
import asyncio
import logging
from typing import Dict, Any, Optional

from .cdp import CDPClient
from .snapshot import PageSnapshot
from .batch import BatchRunner

# Configure logger to write to stderr so stdout remains clean for JSON-RPC
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("fast_browser.mcp")

TOOLS = [
    {
        "name": "browser_list_tabs",
        "description": "List all open browser pages/tabs with their title, URL, and ID.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_select_tab",
        "description": "Select and connect to an open browser tab by query (matching URL or title).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search in page title or URL (e.g. 'mmobitva.ru', 'github', or 'youtube'). If omitted, selects first available page."
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_new_tab",
        "description": "Open a new browser tab with the specified URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "default": "about:blank",
                    "description": "URL to open in the new tab"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_close_tab",
        "description": "Close a browser tab by target ID, or close current tab if ID is omitted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "string",
                    "description": "Target ID to close (optional)"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_reload",
        "description": "Reload the current page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ignore_cache": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether to ignore cache on reload"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_snapshot",
        "description": "Capture a compact, token-efficient snapshot of the active page showing all interactive elements with numbered references (@1, @2, ...), smart labels (including icons/images), and headings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_batch",
        "description": "ULTRA-FAST MULTI-ACTION BATCH EXECUTION: Execute a sequence of browser actions in a single round-trip without model latency. Supports: 'navigate', 'click' (by ref @1 or selector), 'fill' (by ref @1 or selector), 'press_key' (Enter, Escape, Tab, etc.), 'scroll' (by delta or to ref), 'select_option' (by value or text), 'hover', 'wait' (ms/selector/text), 'eval', 'extract', 'snapshot', 'screenshot', 'reload'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "List of action objects, e.g. [{\"action\": \"click\", \"ref\": \"@1\"}, {\"action\": \"wait\", \"ms\": 300}, {\"action\": \"snapshot\"}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["navigate", "click", "fill", "press_key", "scroll", "select_option", "hover", "wait", "eval", "extract", "snapshot", "screenshot", "reload"]},
                            "url": {"type": "string"},
                            "ref": {"type": "string", "description": "Element reference from snapshot, e.g. '@1', '@2'"},
                            "selector": {"type": "string", "description": "CSS selector"},
                            "text": {"type": "string", "description": "Text to fill or wait for"},
                            "key": {"type": "string", "description": "Key name to press (Enter, Escape, Tab, Backspace, ArrowDown, etc.)"},
                            "delta_y": {"type": "integer", "description": "Vertical scroll delta in pixels"},
                            "value": {"type": "string", "description": "Option value for select_option"},
                            "clear": {"type": "boolean", "description": "Clear input before filling (default: true)"},
                            "ms": {"type": "integer", "description": "Milliseconds to wait"},
                            "script": {"type": "string", "description": "JavaScript to evaluate"},
                            "mode": {"type": "string", "enum": ["text", "html"]},
                            "save_path": {"type": "string"}
                        },
                        "required": ["action"]
                    }
                }
            },
            "required": ["steps"]
        }
    },
    {
        "name": "browser_eval",
        "description": "Evaluate arbitrary JavaScript in the active page context and return the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "JavaScript code to execute in page context"
                }
            },
            "required": ["script"]
        }
    },
    {
        "name": "browser_click",
        "description": "Click an element by its snapshot reference (@1, @2, ...) or CSS selector.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Reference from snapshot (e.g. '@1')"},
                "selector": {"type": "string", "description": "CSS selector if ref is not used"}
            },
            "required": []
        }
    },
    {
        "name": "browser_fill",
        "description": "Fill text into an input element by its snapshot reference (@1, @2, ...) or CSS selector.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Reference from snapshot (e.g. '@1')"},
                "selector": {"type": "string", "description": "CSS selector if ref is not used"},
                "text": {"type": "string", "description": "Text to enter"},
                "clear": {"type": "boolean", "default": True, "description": "Clear before typing"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "browser_press_key",
        "description": "Press a keyboard key (e.g. Enter, Escape, Tab, Backspace, ArrowDown, ArrowUp, Space).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name (Enter, Escape, Tab, Backspace, etc.)"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the page or scroll an element into view.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delta_y": {"type": "integer", "default": 400, "description": "Vertical scroll delta (positive=down, negative=up)"},
                "delta_x": {"type": "integer", "default": 0, "description": "Horizontal scroll delta"},
                "ref": {"type": "string", "description": "Element reference to scroll into view (@1, @2...)"},
                "selector": {"type": "string", "description": "CSS selector to scroll into view"}
            },
            "required": []
        }
    },
    {
        "name": "browser_navigate",
        "description": "Navigate active tab to a URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "browser_network_requests",
        "description": "List captured HTTP/XHR/Fetch/WebSocket network requests for reverse engineering. Filter by type (XHR, Fetch, Document, Script, WebSocket) or URL pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter_type": {
                    "type": "string",
                    "description": "Filter by resource type: 'XHR', 'Fetch', 'WebSocket', 'Document', 'Script', or 'all'"
                },
                "url_pattern": {
                    "type": "string",
                    "description": "Substring to search in request URL"
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "description": "Max requests to return"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_network_get_response",
        "description": "Retrieve full request details (headers, POST payload) and response body (JSON/HTML) for a specific request ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The request ID from browser_network_requests"
                }
            },
            "required": ["request_id"]
        }
    },
    {
        "name": "browser_websocket_messages",
        "description": "List captured WebSocket frames (sent/received messages in real-time). Essential for game battle packets and real-time reverse engineering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["sent", "received"],
                    "description": "Filter by direction: 'sent' or 'received' (optional)"
                },
                "limit": {
                    "type": "integer",
                    "default": 40,
                    "description": "Max messages to return"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_get_cookies",
        "description": "Retrieve all cookies for the current tab (auth tokens, session IDs).",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_screenshot",
        "description": "Capture screenshot of current page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Optional file path to save screenshot"}
            },
            "required": []
        }
    }
]

class MCPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.cdp = CDPClient(host=host, port=port)
        self.snapshot = PageSnapshot(self.cdp)
        self.batch = BatchRunner(self.cdp)

    async def ensure_connected(self, query: Optional[str] = None):
        if not self.cdp.is_connected:
            await self.cdp.connect(query)

    async def handle_call(self, name: str, args: Dict[str, Any]) -> str:
        if name == "browser_list_tabs":
            targets = self.cdp.list_targets()
            pages = [
                {"id": t.get("id"), "title": t.get("title"), "url": t.get("url")}
                for t in targets if t.get("type") == "page"
            ]
            return json.dumps(pages, ensure_ascii=False, indent=2)

        elif name == "browser_select_tab":
            query = args.get("query")
            await self.cdp.connect(query)
            target = self.cdp.find_target(query)
            return f"Connected to tab: {target.get('title')} ({target.get('url')})"

        elif name == "browser_new_tab":
            url = args.get("url", "about:blank")
            res = await self.cdp.new_tab(url)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_close_tab":
            target_id = args.get("target_id")
            closed = await self.cdp.close_tab(target_id)
            return "Tab closed successfully" if closed else "Failed to close tab"

        # For all page interaction tools, ensure connected
        await self.ensure_connected()

        if name == "browser_snapshot":
            return await self.snapshot.capture_formatted()

        elif name == "browser_batch":
            steps = args.get("steps", [])
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_eval":
            script = args.get("script", "")
            val = await self.cdp.evaluate(script)
            return json.dumps(val, ensure_ascii=False, indent=2)

        elif name == "browser_click":
            ref = args.get("ref")
            selector = args.get("selector")
            steps = [{"action": "click", "ref": ref, "selector": selector}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_fill":
            ref = args.get("ref")
            selector = args.get("selector")
            text = args.get("text", "")
            clear = args.get("clear", True)
            steps = [{"action": "fill", "ref": ref, "selector": selector, "text": text, "clear": clear}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_press_key":
            key = args.get("key", "Enter")
            steps = [{"action": "press_key", "key": key}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_scroll":
            delta_y = args.get("delta_y", 400)
            delta_x = args.get("delta_x", 0)
            ref = args.get("ref")
            selector = args.get("selector")
            steps = [{"action": "scroll", "delta_y": delta_y, "delta_x": delta_x, "ref": ref, "selector": selector}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_reload":
            ignore_cache = args.get("ignore_cache", False)
            await self.cdp.reload(ignore_cache=ignore_cache)
            return "Page reloaded successfully"

        elif name == "browser_navigate":
            url = args.get("url", "")
            await self.cdp.navigate(url)
            return f"Navigated to {url}"

        elif name == "browser_network_requests":
            filter_type = args.get("filter_type")
            url_pattern = args.get("url_pattern")
            limit = args.get("limit", 30)
            reqs = self.cdp.network.list_requests(filter_type=filter_type, url_pattern=url_pattern, limit=limit)
            return json.dumps(reqs, ensure_ascii=False, indent=2)

        elif name == "browser_network_get_response":
            req_id = args.get("request_id", "")
            details = self.cdp.network.get_request_details(req_id)
            body_res = await self.cdp.get_response_body(req_id)
            combined = {
                "request": details,
                "response_body": body_res
            }
            return json.dumps(combined, ensure_ascii=False, indent=2)

        elif name == "browser_websocket_messages":
            direction = args.get("direction")
            limit = args.get("limit", 40)
            frames = self.cdp.network.list_ws_frames(direction=direction, limit=limit)
            return json.dumps(frames, ensure_ascii=False, indent=2)

        elif name == "browser_get_cookies":
            cookies = await self.cdp.get_cookies()
            return json.dumps(cookies, ensure_ascii=False, indent=2)

        elif name == "browser_screenshot":
            path = args.get("save_path")
            steps = [{"action": "screenshot", "save_path": path}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        else:
            raise ValueError(f"Unknown tool: {name}")

    async def run_stdio(self):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        logger.info("Fast Browser MCP Server started on stdio.")

        while True:
            line = await reader.readline()
            if not line:
                break
            
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
            except json.JSONDecodeError as e:
                logger.error(f"Malformed JSON received: {e}")
                continue

            msg_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            try:
                if method == "initialize":
                    resp = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {}
                            },
                            "serverInfo": {
                                "name": "fast-browser-mcp",
                                "version": "0.2.0"
                            }
                        }
                    }
                    self._send_response(resp)

                elif method == "notifications/initialized":
                    pass

                elif method == "tools/list":
                    resp = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "tools": TOOLS
                        }
                    }
                    self._send_response(resp)

                elif method == "tools/call":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    try:
                        output_text = await self.handle_call(tool_name, tool_args)
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": output_text}
                                ],
                                "isError": False
                            }
                        }
                    except Exception as err:
                        logger.error(f"Tool {tool_name} failed: {err}")
                        resp = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": f"Error executing {tool_name}: {err}"}
                                ],
                                "isError": True
                            }
                        }
                    self._send_response(resp)

                elif method == "ping":
                    self._send_response({"jsonrpc": "2.0", "id": msg_id, "result": {}})

                else:
                    if msg_id is not None:
                        self._send_response({
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"}
                        })
            except Exception as e:
                logger.error(f"Error handling message {method}: {e}")
                if msg_id is not None:
                    self._send_response({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32603, "message": str(e)}
                    })

    def _send_response(self, resp: Dict[str, Any]):
        out = json.dumps(resp, ensure_ascii=False)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()

def main():
    server = MCPServer()
    try:
        asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
