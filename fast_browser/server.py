import sys
import json
import asyncio
import logging
import base64
from typing import Dict, Any, Optional

from .cdp import CDPClient
from .snapshot import PageSnapshot
from .batch import BatchRunner

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
        "description": "Capture a compact, token-efficient snapshot of the active page showing interactive elements with numbered references (@1, @2, ...), smart labels (icons/images/CSS backgrounds), headings, and accessible iframes. Supports scoping to a CSS selector and viewport-only filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to scope snapshot to a specific DOM container"
                },
                "in_viewport": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, only include elements currently visible in viewport"
                },
                "max_elements": {
                    "type": "integer",
                    "description": "Maximum interactive elements to include (truncates remainder to save tokens)"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_batch",
        "description": "ULTRA-FAST MULTI-ACTION BATCH EXECUTION: Execute a sequence of browser actions in a single round-trip without model latency. Supports: 'navigate', 'click', 'double_click', 'right_click', 'drag_and_drop', 'mouse_move', 'fill', 'press_key', 'scroll', 'select_option', 'hover', 'wait', 'eval', 'extract', 'snapshot', 'screenshot' (with full_page and clip selector support), 'pdf', 'get_html', 'set_viewport', 'set_user_agent', 'set_headers', 'block_urls', 'set_geolocation', 'set_timezone', 'get_storage', 'clear_cache', 'clear_cookies', 'set_cookie', 'export_traffic', 'console_logs', 'upload_file', 'window', 'system_page', 'extensions', 'extension_action', 'set_download_path', 'grant_permissions', 'system_info'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "List of action objects",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "url": {"type": "string"},
                            "ref": {"type": "string"},
                            "selector": {"type": "string"},
                            "text": {"type": "string"},
                            "key": {"type": "string"},
                            "delta_y": {"type": "integer"},
                            "value": {"type": "string"},
                            "clear": {"type": "boolean"},
                            "ms": {"type": "integer"},
                            "script": {"type": "string"},
                            "mode": {"type": "string"},
                            "save_path": {"type": "string"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                            "mobile": {"type": "boolean"},
                            "full_page": {"type": "boolean"},
                            "files": {"type": "array", "items": {"type": "string"}}
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
        "name": "browser_mouse",
        "description": "Advanced mouse operations: right-click, double-click, move, or drag-and-drop.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["right_click", "double_click", "move", "drag_and_drop"]},
                "ref": {"type": "string", "description": "Target element ref (@1, @2) for click/dblclick/right-click"},
                "selector": {"type": "string", "description": "Target CSS selector"},
                "from_ref": {"type": "string", "description": "Source element ref for drag_and_drop"},
                "to_ref": {"type": "string", "description": "Target element ref for drag_and_drop"},
                "x": {"type": "number"},
                "y": {"type": "number"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "browser_get_html",
        "description": "Extract full outerHTML of the entire document or save to file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Optional file path to save HTML"}
            },
            "required": []
        }
    },
    {
        "name": "browser_print_to_pdf",
        "description": "Print the current page to a PDF file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "default": "page.pdf", "description": "File path to save PDF"},
                "landscape": {"type": "boolean", "default": False}
            },
            "required": ["save_path"]
        }
    },
    {
        "name": "browser_set_headers",
        "description": "Inject custom HTTP headers into all outgoing requests from the browser.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "headers": {"type": "object", "description": "Key-value map of HTTP headers"}
            },
            "required": ["headers"]
        }
    },
    {
        "name": "browser_set_user_agent",
        "description": "Override User-Agent string for the browser tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_agent": {"type": "string", "description": "New User-Agent string"}
            },
            "required": ["user_agent"]
        }
    },
    {
        "name": "browser_block_urls",
        "description": "Block specific URL patterns (e.g. *.png, *analytics*, *ads*) to speed up page loading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patterns": {"type": "array", "items": {"type": "string"}, "description": "Wildcard URL patterns to block"}
            },
            "required": ["patterns"]
        }
    },
    {
        "name": "browser_set_cookie",
        "description": "Set a cookie in the browser.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
                "domain": {"type": "string"},
                "path": {"type": "string", "default": "/"}
            },
            "required": ["name", "value"]
        }
    },
    {
        "name": "browser_clear_storage",
        "description": "Clear browser cache and/or cookies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "clear_cache": {"type": "boolean", "default": True},
                "clear_cookies": {"type": "boolean", "default": True}
            },
            "required": []
        }
    },
    {
        "name": "browser_emulate_environment",
        "description": "Emulate geolocation coordinates and/or timezone.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "timezone_id": {"type": "string", "description": "e.g. 'Europe/Kyiv', 'America/New_York'"}
            },
            "required": []
        }
    },
    {
        "name": "browser_console_logs",
        "description": "View captured JavaScript console logs (console.log, console.error, console.warn) and unhandled page exceptions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_type": {
                    "type": "string",
                    "description": "Filter by type: 'log', 'error', 'warning', 'info', or 'all'"
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "description": "Max log entries to return"
                }
            },
            "required": []
        }
    },
    {
        "name": "browser_get_storage",
        "description": "Inspect and dump all items from localStorage and sessionStorage for the current origin.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_export_traffic",
        "description": "Export all captured network requests, responses, headers, POST data, and WebSocket frames to a structured JSON file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "default": "traffic_dump.json",
                    "description": "Absolute or relative file path to save traffic dump"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "browser_set_viewport",
        "description": "Set browser viewport dimensions and mobile device emulation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "default": 1280, "description": "Viewport width in pixels"},
                "height": {"type": "integer", "default": 800, "description": "Viewport height in pixels"},
                "mobile": {"type": "boolean", "default": False, "description": "Enable mobile emulation"},
                "device_scale_factor": {"type": "number", "default": 1.0, "description": "Device scale factor (DPI)"}
            },
            "required": ["width", "height"]
        }
    },
    {
        "name": "browser_upload_file",
        "description": "Upload one or more files to an <input type='file'> element via CDP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the file input"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of absolute file paths to upload"
                }
            },
            "required": ["selector", "files"]
        }
    },
    {
        "name": "browser_network_requests",
        "description": "List captured HTTP/XHR/Fetch/WebSocket network requests for reverse engineering. Filter by type or URL pattern.",
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
        "name": "browser_screenshot",
        "description": "Capture screenshot of current page, entire scrollable page, or a specific element.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "save_path": {"type": "string", "description": "Optional file path to save screenshot"},
                "full_page": {"type": "boolean", "default": False, "description": "Capture full scrollable page"},
                "selector": {"type": "string", "description": "CSS selector to capture only this element"}
            },
            "required": []
        }
    },
    {
        "name": "browser_window",
        "description": "Manage browser window: inspect bounds or set state ('normal', 'minimized', 'maximized', 'fullscreen') and dimensions/position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set"], "default": "get", "description": "Action: 'get' or 'set'"},
                "state": {"type": "string", "enum": ["normal", "minimized", "maximized", "fullscreen"], "description": "Window state"},
                "width": {"type": "integer", "description": "Window width in pixels"},
                "height": {"type": "integer", "description": "Window height in pixels"},
                "left": {"type": "integer", "description": "Window left coordinate"},
                "top": {"type": "integer", "description": "Window top coordinate"}
            },
            "required": []
        }
    },
    {
        "name": "browser_open_system_page",
        "description": "Open or switch to a Chrome system page: 'settings', 'extensions', 'downloads', 'history', 'bookmarks', 'flags', 'version', 'gpu', 'net-internals'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "description": "System page name (e.g. 'settings', 'extensions', 'downloads', 'history', 'flags') or custom chrome:// URL"
                }
            },
            "required": ["page"]
        }
    },
    {
        "name": "browser_list_extensions",
        "description": "List all installed Chrome extensions with their IDs, names, versions, enabled status, and options URLs.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_extension_action",
        "description": "Perform management action on a Chrome extension: enable, disable, reload, open options, or open popup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "extension_id": {"type": "string", "description": "The extension ID (from browser_list_extensions)"},
                "action": {"type": "string", "enum": ["enable", "disable", "reload", "options", "popup"], "description": "Action to perform"}
            },
            "required": ["extension_id", "action"]
        }
    },
    {
        "name": "browser_system_info",
        "description": "Get comprehensive browser information: Chrome version, V8 version, User-Agent, protocol version, and memory performance metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_set_download_path",
        "description": "Set browser download directory and behavior (automatically allow downloads without popup prompt).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "download_path": {"type": "string", "description": "Absolute filesystem directory for downloads"},
                "behavior": {"type": "string", "enum": ["allow", "deny", "default"], "default": "allow"}
            },
            "required": ["download_path"]
        }
    },
    {
        "name": "browser_grant_permissions",
        "description": "Grant or reset browser permissions (e.g. notifications, clipboardReadWrite, geolocation) for an origin.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "permissions": {"type": "array", "items": {"type": "string"}, "description": "List of permissions to grant (e.g. ['clipboardReadWrite', 'notifications'])"},
                "origin": {"type": "string", "description": "Target origin (optional)"},
                "reset": {"type": "boolean", "default": False, "description": "Reset all granted permissions"}
            },
            "required": []
        }
    },
    {
        "name": "browser_back",
        "description": "Navigate backward in browser history (back button).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delta": {"type": "integer", "default": 1, "description": "Number of steps backward"}
            },
            "required": []
        }
    },
    {
        "name": "browser_forward",
        "description": "Navigate forward in browser history (forward button).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "delta": {"type": "integer", "default": 1, "description": "Number of steps forward"}
            },
            "required": []
        }
    },
    {
        "name": "browser_history",
        "description": "Retrieve tab navigation history entries and current index.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_add_preload_script",
        "description": "Inject custom JavaScript to run on every new document before page scripts load (hooks / Tampermonkey).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "JavaScript source code to evaluate"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "browser_remove_preload_script",
        "description": "Remove a previously registered preload script by its identifier.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "identifier": {"type": "string", "description": "Script identifier returned by browser_add_preload_script"}
            },
            "required": ["identifier"]
        }
    },
    {
        "name": "browser_stealth_mode",
        "description": "Enable or disable comprehensive anti-detection stealth overrides (masks navigator.webdriver, plugins, languages).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": True, "description": "Enable or disable stealth mode"}
            },
            "required": []
        }
    },
    {
        "name": "browser_network_throttling",
        "description": "Emulate network profiles ('offline', 'slow3g', 'fast3g', '4g', 'none') or custom bandwidth and latency.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string", "enum": ["offline", "slow3g", "fast3g", "4g", "none"], "default": "none"},
                "offline": {"type": "boolean"},
                "latency": {"type": "integer", "description": "Latency in milliseconds"},
                "download_throughput": {"type": "integer", "description": "Bytes per second"},
                "upload_throughput": {"type": "integer", "description": "Bytes per second"}
            },
            "required": []
        }
    },
    {
        "name": "browser_set_media_theme",
        "description": "Emulate system color scheme on page: 'dark', 'light', or 'no-preference'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "theme": {"type": "string", "enum": ["dark", "light", "no-preference"], "default": "dark"}
            },
            "required": ["theme"]
        }
    },
    {
        "name": "browser_set_page_zoom",
        "description": "Adjust page zoom level (e.g. 0.5 for 50%, 1.0 for 100%, 1.5 for 150%).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scale": {"type": "number", "default": 1.0, "description": "Zoom scale factor"}
            },
            "required": ["scale"]
        }
    },
    {
        "name": "browser_mute_tab",
        "description": "Mute or unmute all media audio playback in the active tab.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "muted": {"type": "boolean", "default": True, "description": "Whether to mute audio"}
            },
            "required": []
        }
    },
    {
        "name": "browser_find_in_page",
        "description": "Find text on page (Ctrl+F): count matches, extract context snippets, and scroll to first match.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "scroll_to_first": {"type": "boolean", "default": True, "description": "Scroll to first match"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "browser_clipboard",
        "description": "Read or write to the system clipboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write"], "default": "read"},
                "text": {"type": "string", "description": "Text to copy (for write action)"}
            },
            "required": []
        }
    },
    {
        "name": "browser_get_indexeddb",
        "description": "Inspect all IndexedDB databases and object stores for current origin.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_set_ignore_certificate_errors",
        "description": "Bypass or enforce SSL/TLS certificate warnings on HTTPS websites.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ignore": {"type": "boolean", "default": True, "description": "Ignore certificate errors"}
            },
            "required": []
        }
    },
    {
        "name": "browser_wait_for_network_idle",
        "description": "Wait until network is completely idle (no active in-flight requests) for the specified duration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "idle_time": {"type": "number", "default": 0.5, "description": "Continuous idle time required in seconds"},
                "timeout": {"type": "number", "default": 10.0, "description": "Maximum time to wait in seconds"}
            },
            "required": []
        }
    },
    {
        "name": "browser_block_resources",
        "description": "Block heavy resources (images, video/audio media, web fonts, tracking scripts/ads) or custom URLs to dramatically accelerate page load speed (up to 10x).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "blocked_urls": {"type": "array", "items": {"type": "string"}, "description": "Custom URL glob patterns to block"},
                "block_images": {"type": "boolean", "default": False, "description": "Block all PNG/JPG/WEBP/GIF/SVG images"},
                "block_media": {"type": "boolean", "default": False, "description": "Block all MP4/WEBM/OGG/MP3 video and audio"},
                "block_fonts": {"type": "boolean", "default": False, "description": "Block all WOFF/TTF/OTF web fonts"},
                "block_ads": {"type": "boolean", "default": False, "description": "Block Google Analytics, GTM, DoubleClick, Facebook, and common trackers"}
            },
            "required": []
        }
    },
    {
        "name": "browser_cleanup_tabs",
        "description": "Automatically close stale, blank (about:blank), or pattern-matching tabs to free browser memory and maintain cleanliness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keep_current": {"type": "boolean", "default": True, "description": "Do not close the currently active tab"},
                "close_blank": {"type": "boolean", "default": True, "description": "Close all blank or empty new tabs"},
                "url_patterns": {"type": "array", "items": {"type": "string"}, "description": "List of URL substrings/patterns to close"}
            },
            "required": []
        }
    },
    {
        "name": "browser_performance_metrics",
        "description": "Retrieve real-time browser performance metrics: JS heap memory usage (MB), DOM node count, layout count, and task duration.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_set_geolocation",
        "description": "Override device GPS geolocation coordinates (latitude, longitude, accuracy).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude coordinate"},
                "longitude": {"type": "number", "description": "Longitude coordinate"},
                "accuracy": {"type": "number", "default": 1.0, "description": "Accuracy in meters"}
            },
            "required": ["latitude", "longitude"]
        }
    },
    {
        "name": "browser_set_timezone",
        "description": "Override browser timezone (e.g. 'America/New_York', 'Europe/Kyiv', 'UTC').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "Timezone identifier"}
            },
            "required": ["timezone"]
        }
    },
    {
        "name": "browser_grant_permissions",
        "description": "Grant browser permissions (e.g. ['geolocation', 'notifications', 'clipboardReadWrite']) to current origin.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "permissions": {"type": "array", "items": {"type": "string"}, "description": "List of permission names"},
                "origin": {"type": "string", "description": "Target origin (defaults to current page origin)"}
            },
            "required": ["permissions"]
        }
    },
    {
        "name": "browser_cdp_send",
        "description": "UNIVERSAL RAW CDP (GOD MODE): Send any raw Chrome DevTools Protocol command directly with custom parameters (e.g. 'DOM.getBoxModel', 'CSS.enable', 'Memory.getDOMCounters', 'Tracing.start', 'Fetch.enable').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "CDP method name (e.g. 'DOM.getBoxModel', 'Page.printToPDF')"},
                "params": {"type": "object", "description": "Optional parameters dictionary for the CDP command"},
                "timeout": {"type": "number", "default": 10.0, "description": "Command timeout in seconds"}
            },
            "required": ["method"]
        }
    },
    {
        "name": "browser_get_css_styles",
        "description": "Inspect element computed CSS styles and matched stylesheet rules by selector or @ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of element"},
                "ref": {"type": "string", "description": "Element reference from snapshot (e.g. '@1')"}
            },
            "required": []
        }
    },
    {
        "name": "browser_new_isolated_tab",
        "description": "Open a new tab in a fresh, completely isolated browser context (incognito mode: zero shared cookies, clean session storage).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "default": "about:blank", "description": "URL to open"}
            },
            "required": []
        }
    },
    {
        "name": "browser_set_cpu_throttling",
        "description": "Emulate slower CPU speeds (1.0 = normal, 2.0 = 2x slowdown, 4.0 = 4x slowdown).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rate": {"type": "number", "default": 1.0, "description": "CPU slowdown multiplier"}
            },
            "required": ["rate"]
        }
    },
    {
        "name": "browser_handle_dialog",
        "description": "Handle or configure behavior for JavaScript dialogs (alert, confirm, prompt) with custom action and prompt text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["accept", "dismiss"], "default": "accept", "description": "Whether to accept or dismiss dialog"},
                "prompt_text": {"type": "string", "description": "Optional text to enter for window.prompt"}
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

        # Ensure connected for all page interactions
        await self.ensure_connected()

        if name == "browser_snapshot":
            selector = args.get("selector")
            in_viewport = args.get("in_viewport", False)
            max_elements = args.get("max_elements")
            return await self.snapshot.capture_formatted(selector=selector, in_viewport=in_viewport, max_elements=max_elements)

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

        elif name == "browser_mouse":
            action = args.get("action")
            step = {"action": action, **args}
            res = await self.batch.execute([step])
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_get_html":
            path = args.get("save_path")
            html = await self.cdp.get_html()
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                return f"HTML saved to {path} ({len(html)} chars)"
            return html[:20000]

        elif name == "browser_print_to_pdf":
            path = args.get("save_path", "page.pdf")
            b64 = await self.cdp.print_to_pdf(landscape=args.get("landscape", False))
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            return f"PDF saved successfully to {path}"

        elif name == "browser_set_headers":
            headers = args.get("headers", {})
            await self.cdp.set_extra_headers(headers)
            return f"Injected {len(headers)} custom headers"

        elif name == "browser_set_user_agent":
            ua = args.get("user_agent", "")
            await self.cdp.set_user_agent(ua)
            return f"User-Agent updated to {ua!r}"

        elif name == "browser_block_urls":
            patterns = args.get("patterns", [])
            await self.cdp.block_urls(patterns)
            return f"Blocked {len(patterns)} URL patterns"

        elif name == "browser_set_cookie":
            res = await self.cdp.set_cookie(
                name=args["name"],
                value=args["value"],
                domain=args.get("domain"),
                path=args.get("path", "/")
            )
            return "Cookie set successfully" if res else "Failed to set cookie"

        elif name == "browser_clear_storage":
            if args.get("clear_cache", True):
                await self.cdp.clear_cache()
            if args.get("clear_cookies", True):
                await self.cdp.clear_cookies()
            return "Storage/cache cleared successfully"

        elif name == "browser_emulate_environment":
            if "latitude" in args and "longitude" in args:
                await self.cdp.set_geolocation(args["latitude"], args["longitude"])
            if "timezone_id" in args:
                await self.cdp.set_timezone(args["timezone_id"])
            return "Environment emulated successfully"

        elif name == "browser_console_logs":
            log_type = args.get("log_type")
            limit = args.get("limit", 30)
            logs = self.cdp.console.list_logs(log_type=log_type, limit=limit)
            return json.dumps(logs, ensure_ascii=False, indent=2)

        elif name == "browser_get_storage":
            data = await self.cdp.get_storage()
            return json.dumps(data, ensure_ascii=False, indent=2)

        elif name == "browser_export_traffic":
            path = args.get("file_path", "traffic_dump.json")
            self.cdp.network.export_to_file(path)
            return f"Traffic dump exported successfully to {path}"

        elif name == "browser_set_viewport":
            w = args.get("width", 1280)
            h = args.get("height", 800)
            mob = args.get("mobile", False)
            scale = args.get("device_scale_factor", 1.0)
            await self.cdp.set_viewport(width=w, height=h, mobile=mob, device_scale_factor=scale)
            return f"Viewport set to {w}x{h} (mobile={mob})"

        elif name == "browser_upload_file":
            selector = args.get("selector", "")
            files = args.get("files", [])
            await self.cdp.upload_file(selector, files)
            return f"Uploaded {len(files)} files to {selector}"

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
            full_page = args.get("full_page", False)
            selector = args.get("selector")
            steps = [{"action": "screenshot", "save_path": path, "full_page": full_page, "selector": selector}]
            res = await self.batch.execute(steps)
            return json.dumps(res, ensure_ascii=False)

        elif name == "browser_window":
            action = args.get("action", "get")
            state = args.get("state")
            width = args.get("width")
            height = args.get("height")
            left = args.get("left")
            top = args.get("top")
            if action == "set" or any(v is not None for v in [state, width, height, left, top]):
                await self.cdp.set_window_bounds(state=state, width=width, height=height, left=left, top=top)
                bounds = await self.cdp.get_window_bounds()
                return f"Window bounds updated: {json.dumps(bounds.get('bounds'), ensure_ascii=False)}"
            else:
                bounds = await self.cdp.get_window_bounds()
                return json.dumps(bounds, ensure_ascii=False, indent=2)

        elif name == "browser_open_system_page":
            page = args.get("page", "settings")
            res = await self.cdp.open_system_page(page)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_list_extensions":
            exts = await self.cdp.list_extensions()
            return json.dumps(exts, ensure_ascii=False, indent=2)

        elif name == "browser_extension_action":
            ext_id = args.get("extension_id")
            act = args.get("action")
            res = await self.cdp.extension_action(ext_id, act)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_system_info":
            ver = self.cdp.get_browser_version()
            metrics = {}
            try:
                metrics = await self.cdp.get_performance_metrics()
            except Exception:
                pass
            info = {
                "browser_version": ver,
                "metrics": metrics,
                "targets_count": len(self.cdp.list_targets())
            }
            return json.dumps(info, ensure_ascii=False, indent=2)

        elif name == "browser_set_download_path":
            dl_path = args.get("download_path")
            behavior = args.get("behavior", "allow")
            await self.cdp.set_download_path(dl_path, behavior=behavior)
            return f"Download path configured: {dl_path} (behavior={behavior})"

        elif name == "browser_grant_permissions":
            if args.get("reset"):
                await self.cdp.reset_permissions()
                return "All browser permissions reset"
            perms = args.get("permissions", [])
            origin = args.get("origin")
            await self.cdp.grant_permissions(perms, origin=origin)
            return f"Granted permissions: {perms}"

        elif name == "browser_back":
            delta = args.get("delta", 1)
            res = await self.cdp.go_back(delta=delta)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_forward":
            delta = args.get("delta", 1)
            res = await self.cdp.go_forward(delta=delta)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_history":
            hist = await self.cdp.get_navigation_history()
            return json.dumps(hist, ensure_ascii=False, indent=2)

        elif name == "browser_add_preload_script":
            source = args.get("source", "")
            ident = await self.cdp.add_preload_script(source)
            return f"Preload script registered (identifier={ident})"

        elif name == "browser_remove_preload_script":
            ident = args.get("identifier", "")
            await self.cdp.remove_preload_script(ident)
            return f"Preload script removed (identifier={ident})"

        elif name == "browser_stealth_mode":
            enabled = args.get("enabled", True)
            res = await self.cdp.set_stealth_mode(enabled=enabled)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_network_throttling":
            prof = args.get("profile", "none")
            res = await self.cdp.set_network_throttling(
                profile=prof,
                offline=args.get("offline"),
                latency=args.get("latency"),
                download_throughput=args.get("download_throughput"),
                upload_throughput=args.get("upload_throughput")
            )
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_set_media_theme":
            theme = args.get("theme", "dark")
            res = await self.cdp.set_media_theme(theme=theme)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_set_page_zoom":
            scale = args.get("scale", 1.0)
            res = await self.cdp.set_page_zoom(scale=scale)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_mute_tab":
            muted = args.get("muted", True)
            res = await self.cdp.set_audio_muted(muted=muted)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_find_in_page":
            query = args.get("query", "")
            scroll = args.get("scroll_to_first", True)
            res = await self.cdp.find_in_page(query=query, scroll_to_first=scroll)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_clipboard":
            action = args.get("action", "read")
            if action == "write":
                text = args.get("text", "")
                await self.cdp.set_clipboard_text(text)
                return f"Clipboard updated: {text[:60]}"
            else:
                clip_text = await self.cdp.get_clipboard_text()
                return clip_text

        elif name == "browser_get_indexeddb":
            idb = await self.cdp.get_indexeddb_data()
            return json.dumps(idb, ensure_ascii=False, indent=2)

        elif name == "browser_set_ignore_certificate_errors":
            ignore = args.get("ignore", True)
            res = await self.cdp.set_ignore_certificate_errors(ignore=ignore)
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_wait_for_network_idle":
            idle_time = args.get("idle_time", 0.5)
            timeout = args.get("timeout", 10.0)
            ok = await self.cdp.wait_for_network_idle(idle_time=idle_time, timeout=timeout)
            return json.dumps({"idle": ok, "idle_time": idle_time, "timeout": timeout}, indent=2)

        elif name == "browser_block_resources":
            res = await self.cdp.block_resources(
                blocked_urls=args.get("blocked_urls"),
                block_images=args.get("block_images", False),
                block_media=args.get("block_media", False),
                block_fonts=args.get("block_fonts", False),
                block_ads=args.get("block_ads", False)
            )
            return json.dumps(res, indent=2)

        elif name == "browser_cleanup_tabs":
            res = self.cdp.cleanup_tabs(
                keep_current=args.get("keep_current", True),
                close_blank=args.get("close_blank", True),
                url_patterns=args.get("url_patterns")
            )
            return json.dumps(res, indent=2)

        elif name == "browser_performance_metrics":
            res = await self.cdp.get_performance_metrics()
            return json.dumps(res, indent=2)

        elif name == "browser_set_geolocation":
            res = await self.cdp.set_geolocation(
                latitude=args.get("latitude", 0.0),
                longitude=args.get("longitude", 0.0),
                accuracy=args.get("accuracy", 1.0)
            )
            return json.dumps(res, indent=2)

        elif name == "browser_set_timezone":
            res = await self.cdp.set_timezone(timezone_id=args.get("timezone", "UTC"))
            return json.dumps(res, indent=2)

        elif name == "browser_grant_permissions":
            res = await self.cdp.grant_permissions(
                permissions=args.get("permissions", []),
                origin=args.get("origin")
            )
            return json.dumps(res, indent=2)

        elif name == "browser_cdp_send":
            res = await self.cdp.send_cdp(
                method=args["method"],
                params=args.get("params"),
                timeout=args.get("timeout", 10.0)
            )
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_get_css_styles":
            res = await self.cdp.get_css_styles(
                selector=args.get("selector"),
                ref=args.get("ref")
            )
            return json.dumps(res, ensure_ascii=False, indent=2)

        elif name == "browser_new_isolated_tab":
            res = await self.cdp.new_isolated_tab(url=args.get("url", "about:blank"))
            return json.dumps(res, indent=2)

        elif name == "browser_set_cpu_throttling":
            res = await self.cdp.set_cpu_throttling(rate=args.get("rate", 1.0))
            return json.dumps(res, indent=2)

        elif name == "browser_handle_dialog":
            res = await self.cdp.handle_dialog(
                action=args.get("action", "accept"),
                prompt_text=args.get("prompt_text")
            )
            return json.dumps(res, indent=2)

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
                                "version": "0.8.0"
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
