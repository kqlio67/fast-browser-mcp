import asyncio
import json
import logging
import requests
import websockets
from typing import Dict, Any, Optional, List, Union
from .network import NetworkMonitor, ConsoleMonitor

logger = logging.getLogger("fast_browser.cdp")

KEY_DEFINITIONS = {
    "Enter": {"windowsVirtualKeyCode": 13, "code": "Enter", "key": "Enter", "text": "\r"},
    "Tab": {"windowsVirtualKeyCode": 9, "code": "Tab", "key": "Tab"},
    "Escape": {"windowsVirtualKeyCode": 27, "code": "Escape", "key": "Escape"},
    "Backspace": {"windowsVirtualKeyCode": 8, "code": "Backspace", "key": "Backspace"},
    "ArrowDown": {"windowsVirtualKeyCode": 40, "code": "ArrowDown", "key": "ArrowDown"},
    "ArrowUp": {"windowsVirtualKeyCode": 38, "code": "ArrowUp", "key": "ArrowUp"},
    "ArrowLeft": {"windowsVirtualKeyCode": 37, "code": "ArrowLeft", "key": "ArrowLeft"},
    "ArrowRight": {"windowsVirtualKeyCode": 39, "code": "ArrowRight", "key": "ArrowRight"},
    "Space": {"windowsVirtualKeyCode": 32, "code": "Space", "key": " ", "text": " "},
    "PageDown": {"windowsVirtualKeyCode": 34, "code": "PageDown", "key": "PageDown"},
    "PageUp": {"windowsVirtualKeyCode": 33, "code": "PageUp", "key": "PageUp"}
}

class CDPClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.ws_url: Optional[str] = None
        self.target_id: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._req_id = 0
        self._browser_req_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self.auto_accept_dialogs = True
        self.last_dialog_message: Optional[str] = None
        self.network = NetworkMonitor()
        self.console = ConsoleMonitor()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def list_targets(self) -> List[Dict[str, Any]]:
        url = f"http://{self.host}:{self.port}/json"
        try:
            resp = requests.get(url, timeout=3)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to list CDP targets from {url}: {e}")
            return []

    def find_target(self, query: Optional[str] = None, target_type: str = "page") -> Optional[Dict[str, Any]]:
        targets = self.list_targets()
        pages = [t for t in targets if t.get("type") == target_type]
        if not pages:
            return None
        if not query:
            return pages[0]
        q = query.lower()
        for p in pages:
            if q in p.get("title", "").lower() or q in p.get("url", "").lower() or q == p.get("id", "").lower():
                return p
        return None

    async def connect(self, target_query: Optional[str] = None):
        target = self.find_target(target_query)
        if not target:
            raise RuntimeError(f"No matching browser page found (query={target_query!r}) on {self.host}:{self.port}")
        
        self.target_id = target.get("id")
        self.ws_url = target.get("webSocketDebuggerUrl")
        if not self.ws_url:
            raise RuntimeError(f"Target {self.target_id} has no webSocketDebuggerUrl")

        if self._ws and not self._ws.closed:
            await self.close()

        self._ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        self._listen_task = asyncio.create_task(self._listen_loop())

        # Enable core domains
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("DOM.enable")
        await self.send("Network.enable", {"maxPostDataSize": 65536})

    async def close(self):
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        for fut in self._pending_requests.values():
            if not fut.done():
                fut.cancel()
        self._pending_requests.clear()

    async def _listen_loop(self):
        try:
            async for raw_msg in self._ws:
                msg = json.loads(raw_msg)
                msg_id = msg.get("id")
                
                # Check for responses to sent requests
                if msg_id is not None and msg_id in self._pending_requests:
                    fut = self._pending_requests.pop(msg_id)
                    if not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(f"CDP Error: {msg['error']}"))
                        else:
                            fut.set_result(msg.get("result", {}))
                    continue

                # Handle asynchronous CDP events
                method = msg.get("method", "")
                params = msg.get("params", {})

                # Network traffic monitor
                if method.startswith("Network."):
                    self.network.handle_event(method, params)

                # Console logs monitor
                elif method.startswith("Runtime.console") or method.startswith("Runtime.exception"):
                    self.console.handle_event(method, params)

                # Automatic Dialog handling (alert, confirm, prompt)
                elif method == "Page.javascriptDialogOpening":
                    self.last_dialog_message = params.get("message")
                    logger.warning(f"JavaScript dialog opened: {self.last_dialog_message!r} (type={params.get('type')})")
                    if self.auto_accept_dialogs:
                        asyncio.create_task(self.send("Page.handleJavaScriptDialog", {"accept": True}))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"CDP listen loop terminated: {e}")

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        if not self.is_connected:
            raise RuntimeError("CDP WebSocket is not connected.")
        
        self._req_id += 1
        req_id = self._req_id
        payload = {"id": req_id, "method": method, "params": params or {}}
        
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut
        
        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"CDP command {method} (id={req_id}) timed out after {timeout}s")

    async def evaluate(self, expression: str, await_promise: bool = True, timeout: float = 10.0) -> Any:
        expr = expression.strip()
        if "return " in expr and not (expr.startswith("(") or expr.startswith("function") or expr.startswith("async")):
            expr = f"(() => {{ {expr} }})()"

        params = {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "userGesture": True
        }
        res = await self.send("Runtime.evaluate", params, timeout=timeout)
        result_obj = res.get("result", {})
        if res.get("exceptionDetails"):
            exc = res["exceptionDetails"]
            desc = exc.get("exception", {}).get("description") or exc.get("text")
            raise RuntimeError(f"JavaScript evaluation error: {desc}")
        return result_obj.get("value")

    async def navigate(self, url: str, wait_until_loaded: bool = True, timeout: float = 15.0) -> Dict[str, Any]:
        res = await self.send("Page.navigate", {"url": url}, timeout=timeout)
        if wait_until_loaded:
            await self.wait_for_dom_ready(timeout=timeout)
        return res

    async def reload(self, ignore_cache: bool = False, timeout: float = 15.0) -> Dict[str, Any]:
        res = await self.send("Page.reload", {"ignoreCache": ignore_cache}, timeout=timeout)
        await self.wait_for_dom_ready(timeout=timeout)
        return res

    async def new_tab(self, url: str = "about:blank") -> Dict[str, Any]:
        res = requests.put(f"http://{self.host}:{self.port}/json/new?{url}", timeout=5)
        res.raise_for_status()
        return res.json()

    async def close_tab(self, target_id: Optional[str] = None) -> bool:
        tid = target_id or self.target_id
        if not tid:
            return False
        res = requests.get(f"http://{self.host}:{self.port}/json/close/{tid}", timeout=5)
        return res.status_code == 200

    async def wait_for_dom_ready(self, timeout: float = 10.0):
        t0 = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - t0 < timeout:
            ready_state = await self.evaluate("document.readyState")
            if ready_state in ("interactive", "complete"):
                return True
            await asyncio.sleep(0.05)
        return False

    async def wait_for_selector(self, selector: str, timeout_ms: int = 5000) -> bool:
        t0 = asyncio.get_running_loop().time()
        timeout_sec = timeout_ms / 1000.0
        js = f"Boolean(document.querySelector({json.dumps(selector)}))"
        while (asyncio.get_running_loop().time() - t0) < timeout_sec:
            found = await self.evaluate(js)
            if found:
                return True
            await asyncio.sleep(0.05)
        return False

    async def wait_for_text(self, text: str, timeout_ms: int = 5000) -> bool:
        t0 = asyncio.get_running_loop().time()
        timeout_sec = timeout_ms / 1000.0
        js = f"document.body && document.body.innerText.includes({json.dumps(text)})"
        while (asyncio.get_running_loop().time() - t0) < timeout_sec:
            found = await self.evaluate(js)
            if found:
                return True
            await asyncio.sleep(0.05)
        return False

    async def click(self, selector: str, timeout_ms: int = 3000) -> bool:
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{block: 'center', inline: 'center'}});
            el.click();
            return true;
        }})()"""
        found = await self.wait_for_selector(selector, timeout_ms=timeout_ms)
        if not found:
            raise RuntimeError(f"Element '{selector}' not found for click within {timeout_ms}ms")
        return await self.evaluate(js)

    async def double_click(self, x: float, y: float) -> bool:
        for _ in range(2):
            await self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 2})
            await self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 2})
        return True

    async def right_click(self, x: float, y: float) -> bool:
        await self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "right", "clickCount": 1})
        await self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "right", "clickCount": 1})
        return True

    async def mouse_move(self, x: float, y: float) -> bool:
        await self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        return True

    async def drag_and_drop(self, start_x: float, start_y: float, end_x: float, end_y: float, steps: int = 10) -> bool:
        await self.mouse_move(start_x, start_y)
        await self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start_x, "y": start_y, "button": "left", "clickCount": 1})
        for i in range(1, steps + 1):
            curr_x = start_x + (end_x - start_x) * (i / steps)
            curr_y = start_y + (end_y - start_y) * (i / steps)
            await self.mouse_move(curr_x, curr_y)
            await asyncio.sleep(0.02)
        await self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end_x, "y": end_y, "button": "left", "clickCount": 1})
        return True

    async def fill(self, selector: str, text: str, clear: bool = True, timeout_ms: int = 3000) -> bool:
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{block: 'center', inline: 'center'}});
            el.focus();
            if ({json.dumps(clear)}) {{
                el.value = '';
            }}
            el.value = {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }})()"""
        found = await self.wait_for_selector(selector, timeout_ms=timeout_ms)
        if not found:
            raise RuntimeError(f"Element '{selector}' not found for fill within {timeout_ms}ms")
        return await self.evaluate(js)

    async def press_key(self, key: str) -> bool:
        key_def = KEY_DEFINITIONS.get(key)
        if key_def:
            kd = {"type": "rawKeyDown", **key_def}
            ku = {"type": "keyUp", **key_def}
            await self.send("Input.dispatchKeyEvent", kd)
            if "text" in key_def:
                await self.send("Input.dispatchKeyEvent", {"type": "char", "text": key_def["text"]})
            await self.send("Input.dispatchKeyEvent", ku)
        else:
            for ch in key:
                await self.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": ch, "unmodifiedText": ch})
                await self.send("Input.dispatchKeyEvent", {"type": "keyUp"})
        return True

    async def scroll(self, delta_x: int = 0, delta_y: int = 400) -> bool:
        js = f"window.scrollBy({delta_x}, {delta_y}); return true;"
        return await self.evaluate(js)

    async def scroll_to_element(self, selector: str) -> bool:
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{behavior: 'smooth', block: 'center', inline: 'center'}});
            return true;
        }})()"""
        return await self.evaluate(js)

    async def select_option(self, selector: str, value: Optional[str] = None, text: Optional[str] = None) -> bool:
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el || el.tagName.toLowerCase() !== 'select') return false;
            let targetIdx = -1;
            for (let i = 0; i < el.options.length; i++) {{
                const opt = el.options[i];
                if ({json.dumps(value)} !== null && opt.value === {json.dumps(value)}) {{
                    targetIdx = i;
                    break;
                }}
                if ({json.dumps(text)} !== null && opt.text.trim().toLowerCase() === {json.dumps(text or '')}.toLowerCase()) {{
                    targetIdx = i;
                    break;
                }}
            }}
            if (targetIdx >= 0) {{
                el.selectedIndex = targetIdx;
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})()"""
        return await self.evaluate(js)

    async def get_storage(self) -> Dict[str, Any]:
        js = """(() => {
            const local = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                local[k] = localStorage.getItem(k);
            }
            const session = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                session[k] = sessionStorage.getItem(k);
            }
            return { localStorage: local, sessionStorage: session };
        })()"""
        return await self.evaluate(js)

    async def set_viewport(self, width: int = 1280, height: int = 800, mobile: bool = False, device_scale_factor: float = 1.0) -> bool:
        params = {
            "width": width,
            "height": height,
            "deviceScaleFactor": device_scale_factor,
            "mobile": mobile
        }
        await self.send("Emulation.setDeviceMetricsOverride", params)
        return True

    async def set_geolocation(self, latitude: float, longitude: float, accuracy: float = 100.0) -> bool:
        await self.send("Emulation.setGeolocationOverride", {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy
        })
        return True

    async def set_timezone(self, timezone_id: str) -> bool:
        await self.send("Emulation.setTimezoneOverride", {"timezoneId": timezone_id})
        return True

    async def set_user_agent(self, user_agent: str) -> bool:
        await self.send("Network.setUserAgentOverride", {"userAgent": user_agent})
        return True

    async def set_extra_headers(self, headers: Dict[str, str]) -> bool:
        await self.send("Network.setExtraHTTPHeaders", {"headers": headers})
        return True

    async def block_urls(self, patterns: List[str]) -> bool:
        await self.send("Network.setBlockedURLs", {"urls": patterns})
        return True

    async def upload_file(self, selector: str, files: List[str]) -> bool:
        doc = await self.send("DOM.getDocument")
        node_res = await self.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector})
        node_id = node_res.get("nodeId")
        if not node_id:
            raise RuntimeError(f"File input '{selector}' not found in DOM")
        await self.send("DOM.setFileInputFiles", {"files": files, "nodeId": node_id})
        return True

    async def get_html(self) -> str:
        return await self.evaluate("document.documentElement.outerHTML")

    async def print_to_pdf(self, landscape: bool = False, print_background: bool = True) -> str:
        res = await self.send("Page.printToPDF", {
            "landscape": landscape,
            "printBackground": print_background
        })
        return res.get("data", "")

    async def clear_cache(self) -> bool:
        await self.send("Network.clearBrowserCache")
        return True

    async def clear_cookies(self) -> bool:
        await self.send("Network.clearBrowserCookies")
        return True

    async def set_cookie(self, name: str, value: str, domain: Optional[str] = None, path: str = "/", secure: bool = False, http_only: bool = False) -> bool:
        params = {
            "name": name,
            "value": value,
            "path": path,
            "secure": secure,
            "httpOnly": http_only
        }
        if domain:
            params["domain"] = domain
        else:
            url = await self.evaluate("window.location.href")
            params["url"] = url
        res = await self.send("Network.setCookie", params)
        return res.get("success", False)

    async def get_response_body(self, request_id: str) -> Dict[str, Any]:
        try:
            res = await self.send("Network.getResponseBody", {"requestId": request_id})
            return {
                "body": res.get("body", ""),
                "base64Encoded": res.get("base64Encoded", False)
            }
        except Exception as e:
            return {"error": str(e)}

    async def get_cookies(self, urls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        params = {"urls": urls} if urls else {}
        res = await self.send("Network.getCookies", params)
        return res.get("cookies", [])

    async def capture_screenshot(self, format: str = "png", quality: Optional[int] = None, full_page: bool = False, clip_selector: Optional[str] = None) -> str:
        params: Dict[str, Any] = {"format": format}
        if quality is not None:
            params["quality"] = quality

        if full_page:
            params["captureBeyondViewport"] = True
            # Get full dimensions
            metrics = await self.send("Page.getLayoutMetrics")
            content_size = metrics.get("contentSize", {})
            width = content_size.get("width")
            height = content_size.get("height")
            if width and height:
                params["clip"] = {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}

        elif clip_selector:
            rect = await self.evaluate(f"""(() => {{
                const el = document.querySelector({json.dumps(clip_selector)});
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {{x: r.x, y: r.y, width: r.width, height: r.height, scale: 1}};
            }})()""")
            if rect and rect.get("width") > 0 and rect.get("height") > 0:
                params["clip"] = rect

        res = await self.send("Page.captureScreenshot", params)
        return res.get("data", "")

    async def send_browser_cmd(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        """Send a CDP command directly to the browser-level WebSocket endpoint."""
        ver_url = f"http://{self.host}:{self.port}/json/version"
        resp = requests.get(ver_url, timeout=3)
        resp.raise_for_status()
        browser_ws_url = resp.json().get("webSocketDebuggerUrl")
        if not browser_ws_url:
            raise RuntimeError("No webSocketDebuggerUrl returned by /json/version")
        
        self._browser_req_id += 1
        req_id = self._browser_req_id
        payload = {"id": req_id, "method": method, "params": params or {}}
        
        async with websockets.connect(browser_ws_url, max_size=10 * 1024 * 1024) as ws:
            await ws.send(json.dumps(payload))
            t0 = asyncio.get_running_loop().time()
            while asyncio.get_running_loop().time() - t0 < timeout:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"CDP Browser Error: {msg['error']}")
                    return msg.get("result", {})
            raise TimeoutError(f"Browser command {method} timed out")

    def get_browser_version(self) -> Dict[str, Any]:
        """Get browser and CDP protocol version info."""
        url = f"http://{self.host}:{self.port}/json/version"
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return resp.json()

    async def get_window_bounds(self, target_id: Optional[str] = None) -> Dict[str, Any]:
        """Get browser window bounds and state (normal, minimized, maximized, fullscreen)."""
        tid = target_id or self.target_id
        if not tid:
            targets = self.list_targets()
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                tid = pages[0]["id"]
            else:
                raise RuntimeError("No target page available to get window bounds")
        return await self.send_browser_cmd("Browser.getWindowForTarget", {"targetId": tid})

    async def set_window_bounds(
        self,
        state: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        left: Optional[int] = None,
        top: Optional[int] = None,
        target_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set browser window state (normal, minimized, maximized, fullscreen) or resize/position bounds."""
        win_info = await self.get_window_bounds(target_id)
        window_id = win_info.get("windowId")
        bounds: Dict[str, Any] = {}
        if state:
            bounds["windowState"] = state.lower()
        if width is not None:
            bounds["width"] = width
        if height is not None:
            bounds["height"] = height
        if left is not None:
            bounds["left"] = left
        if top is not None:
            bounds["top"] = top
        return await self.send_browser_cmd("Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds})

    async def set_download_path(self, download_path: str, behavior: str = "allow") -> Dict[str, Any]:
        """Configure browser download behavior and directory."""
        return await self.send_browser_cmd("Browser.setDownloadBehavior", {
            "behavior": behavior,
            "downloadPath": download_path,
            "eventsEnabled": True
        })

    async def grant_permissions(self, permissions: List[str], origin: Optional[str] = None) -> Dict[str, Any]:
        """Grant browser permissions (notifications, clipboardReadWrite, geolocation, etc.)."""
        params: Dict[str, Any] = {"permissions": permissions}
        if origin:
            params["origin"] = origin
        return await self.send_browser_cmd("Browser.grantPermissions", params)

    async def reset_permissions(self) -> Dict[str, Any]:
        """Reset all browser permissions."""
        return await self.send_browser_cmd("Browser.resetPermissions")

    async def open_system_page(self, name_or_url: str) -> Dict[str, Any]:
        """Open or switch to a system page (settings, extensions, downloads, history, bookmarks, flags)."""
        system_map = {
            "settings": "chrome://settings",
            "extensions": "chrome://extensions",
            "downloads": "chrome://downloads",
            "history": "chrome://history",
            "bookmarks": "chrome://bookmarks",
            "flags": "chrome://flags",
            "version": "chrome://version",
            "gpu": "chrome://gpu",
            "net-internals": "chrome://net-internals",
            "experiments": "chrome://flags"
        }
        page_key = name_or_url.strip().lower()
        target_url = system_map.get(page_key, name_or_url)
        if not target_url.startswith("chrome://") and not target_url.startswith("http"):
            target_url = f"chrome://{target_url}"
        
        targets = self.list_targets()
        for t in targets:
            if t.get("type") == "page" and t.get("url", "").rstrip("/") == target_url.rstrip("/"):
                await self.connect(t.get("id"))
                return {"status": "switched", "target": t}
        
        new_tab = await self.new_tab(target_url)
        await asyncio.sleep(0.5)
        await self.connect(new_tab.get("id"))
        return {"status": "opened", "target": new_tab}

    async def list_extensions(self) -> List[Dict[str, Any]]:
        """List all installed extensions with IDs, names, versions, enabled states, and options URLs."""
        temp_tab_id = None
        current_url = ""
        if self.is_connected:
            try:
                current_url = await self.evaluate("window.location.href") or ""
            except Exception:
                current_url = ""

        try:
            if "chrome://extensions" not in current_url:
                tab_res = await self.open_system_page("extensions")
                if tab_res.get("status") == "opened":
                    temp_tab_id = tab_res.get("target", {}).get("id")
                await asyncio.sleep(0.6)

            js = """(async () => {
                if (window.chrome && chrome.developerPrivate && chrome.developerPrivate.getExtensionsInfo) {
                    const list = await chrome.developerPrivate.getExtensionsInfo();
                    return list.map(e => ({
                        id: e.id,
                        name: e.name,
                        version: e.version,
                        description: e.description || '',
                        enabled: e.state === 'ENABLED',
                        incognitoAccess: e.incognitoAccess,
                        fileAccess: e.fileAccess,
                        optionsUrl: (e.optionsPage && e.optionsPage.url) ? e.optionsPage.url : (e.optionsUrl || null),
                        homepageUrl: e.homePageUrl || null
                    }));
                }
                return null;
            })()"""
            exts = await self.evaluate(js)
            if exts:
                return exts
        except Exception as e:
            logger.warning(f"Failed to query chrome.developerPrivate: {e}")
        finally:
            if temp_tab_id:
                try:
                    await self.close_tab(temp_tab_id)
                except Exception:
                    pass

        # Fallback to /json targets inspection
        targets = self.list_targets()
        ext_map = {}
        for t in targets:
            url = t.get("url", "")
            if "chrome-extension://" in url:
                parts = url.split("chrome-extension://")[-1].split("/")
                ext_id = parts[0]
                if ext_id not in ext_map:
                    ext_map[ext_id] = {
                        "id": ext_id,
                        "name": t.get("title") or ext_id,
                        "type": t.get("type"),
                        "url": url,
                        "enabled": True
                    }
        return list(ext_map.values())

    async def extension_action(self, extension_id: str, action: str) -> Dict[str, Any]:
        """Perform action on an extension: 'enable', 'disable', 'reload', 'options', 'popup'."""
        act = action.lower()
        if act in ("options", "popup"):
            page_name = "options.html" if act == "options" else "popup.html"
            url = f"chrome-extension://{extension_id}/{page_name}"
            tab = await self.new_tab(url)
            await asyncio.sleep(0.3)
            await self.connect(tab.get("id"))
            return {"status": "opened", "url": url, "tab": tab}
        
        temp_tab_id = None
        current_url = ""
        if self.is_connected:
            try:
                current_url = await self.evaluate("window.location.href") or ""
            except Exception:
                current_url = ""

        try:
            if "chrome://extensions" not in current_url:
                tab_res = await self.open_system_page("extensions")
                if tab_res.get("status") == "opened":
                    temp_tab_id = tab_res.get("target", {}).get("id")
                await asyncio.sleep(0.6)

            if act == "enable":
                js = f"chrome.developerPrivate.updateExtensionConfiguration({{id: {json.dumps(extension_id)}, state: 1}})"
                await self.evaluate(js)
                return {"status": "ok", "action": "enabled", "id": extension_id}
            elif act == "disable":
                js = f"chrome.developerPrivate.updateExtensionConfiguration({{id: {json.dumps(extension_id)}, state: 0}})"
                await self.evaluate(js)
                return {"status": "ok", "action": "disabled", "id": extension_id}
            elif act == "reload":
                js = f"chrome.developerPrivate.reload({json.dumps(extension_id)})"
                await self.evaluate(js)
                return {"status": "ok", "action": "reloaded", "id": extension_id}
            else:
                raise ValueError(f"Unknown extension action: {action!r}")
        finally:
            if temp_tab_id:
                try:
                    await self.close_tab(temp_tab_id)
                except Exception:
                    pass

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Retrieve browser performance and memory metrics."""
        await self.send("Performance.enable")
        res = await self.send("Performance.getMetrics")
        metrics_list = res.get("metrics", [])
        return {m["name"]: m["value"] for m in metrics_list}
