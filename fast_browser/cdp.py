import os
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
    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or os.environ.get("CDP_HOST", "127.0.0.1")
        env_port = os.environ.get("CDP_PORT")
        self.port = int(port if port is not None else (int(env_port) if env_port else 9222))
        self.ws_url: Optional[str] = None
        self.target_id: Optional[str] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._req_id = 0
        self._browser_req_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self.auto_accept_dialogs = True
        self.dialog_action = "accept"
        self.dialog_prompt_text: Optional[str] = None
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

    def get_target_by_id(self, target_id: str) -> Optional[Dict[str, Any]]:
        for t in self.list_targets():
            if t.get("id") == target_id:
                return t
        return None

    async def connect(self, target_query: Optional[str] = None, target_id: Optional[str] = None):
        if target_id:
            target = self.get_target_by_id(target_id)
        else:
            target = self.find_target(target_query)
        if not target:
            raise RuntimeError(f"No matching browser page found (query={target_query!r}, target_id={target_id!r}) on {self.host}:{self.port}")
        
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
                        d_params = {"accept": self.dialog_action == "accept"}
                        if self.dialog_prompt_text is not None:
                            d_params["promptText"] = self.dialog_prompt_text
                        asyncio.create_task(self.send("Page.handleJavaScriptDialog", d_params))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"CDP listen loop terminated: {e}")

    async def send(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        if not self.is_connected:
            if self.target_id:
                try:
                    logger.info(f"CDP socket disconnected. Auto-reconnecting to target {self.target_id}...")
                    await self.connect(target_id=self.target_id)
                except Exception as e:
                    raise RuntimeError(f"CDP WebSocket disconnected and auto-reconnect failed: {e}")
            else:
                raise RuntimeError("CDP WebSocket is not connected.")
        
        self._req_id += 1
        req_id = self._req_id
        payload = {"id": req_id, "method": method, "params": params or {}}
        
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut
        
        try:
            await self._ws.send(json.dumps(payload))
        except (websockets.ConnectionClosed, websockets.ConnectionClosedError):
            if self.target_id:
                logger.info("WebSocket connection dropped during send. Reconnecting...")
                await self.connect(target_id=self.target_id)
                await self._ws.send(json.dumps(payload))
            else:
                raise

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

    def new_tab_sync(self, url: str = "about:blank") -> Dict[str, Any]:
        res = requests.put(f"http://{self.host}:{self.port}/json/new?{url}", timeout=5)
        res.raise_for_status()
        return res.json()

    def close_tab_sync(self, target_id: Optional[str] = None) -> bool:
        tid = target_id or self.target_id
        if not tid:
            return False
        res = requests.get(f"http://{self.host}:{self.port}/json/close/{tid}", timeout=5)
        return res.status_code == 200

    async def new_tab(self, url: str = "about:blank") -> Dict[str, Any]:
        return self.new_tab_sync(url)

    async def close_tab(self, target_id: Optional[str] = None) -> bool:
        return self.close_tab_sync(target_id)

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

    async def wait_for_element_stable(self, selector: str, timeout_ms: int = 3000) -> bool:
        """Wait until element is present, visible, has dimensions > 0, and position is stable (no active animations)."""
        js = f"""(async () => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            try {{
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const r1 = el.getBoundingClientRect();
                if (r1.width === 0 || r1.height === 0) return false;
                await new Promise(r => setTimeout(r, 60));
                const r2 = el.getBoundingClientRect();
                return Math.abs(r1.left - r2.left) < 1 && Math.abs(r1.top - r2.top) < 1;
            }} catch(e) {{
                return false;
            }}
        }})()"""
        t0 = asyncio.get_running_loop().time()
        timeout_sec = timeout_ms / 1000.0
        while (asyncio.get_running_loop().time() - t0) < timeout_sec:
            try:
                ok = await self.evaluate(js)
                if ok:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.05)
        return False

    async def click(self, selector: str, timeout_ms: int = 3000, wait_stable: bool = True) -> bool:
        js = f"""(() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return false;
            el.scrollIntoView({{block: 'center', inline: 'center'}});
            el.click();
            return true;
        }})()"""
        if wait_stable:
            stable = await self.wait_for_element_stable(selector, timeout_ms=timeout_ms)
            if not stable:
                found = await self.wait_for_selector(selector, timeout_ms=500)
                if not found:
                    raise RuntimeError(f"Element '{selector}' not found or not stable within {timeout_ms}ms")
        else:
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

    async def fill(self, selector: str, text: str, clear: bool = True, timeout_ms: int = 3000, wait_stable: bool = True) -> bool:
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
        if wait_stable:
            stable = await self.wait_for_element_stable(selector, timeout_ms=timeout_ms)
            if not stable:
                found = await self.wait_for_selector(selector, timeout_ms=500)
                if not found:
                    raise RuntimeError(f"Element '{selector}' not found or not stable within {timeout_ms}ms")
        else:
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

    # Navigation & History
    async def go_back(self, delta: int = 1) -> Dict[str, Any]:
        """Navigate backward in browser history."""
        hist = await self.send("Page.getNavigationHistory")
        curr_idx = hist.get("currentIndex", 0)
        target_idx = curr_idx - delta
        entries = hist.get("entries", [])
        if target_idx < 0 or target_idx >= len(entries):
            raise IndexError(f"Cannot go back {delta} step(s) (current index is {curr_idx})")
        entry_id = entries[target_idx]["id"]
        await self.send("Page.navigateToHistoryEntry", {"entryId": entry_id})
        await self.wait_for_dom_ready()
        return {"status": "ok", "url": entries[target_idx].get("url"), "title": entries[target_idx].get("title")}

    async def go_forward(self, delta: int = 1) -> Dict[str, Any]:
        """Navigate forward in browser history."""
        hist = await self.send("Page.getNavigationHistory")
        curr_idx = hist.get("currentIndex", 0)
        target_idx = curr_idx + delta
        entries = hist.get("entries", [])
        if target_idx < 0 or target_idx >= len(entries):
            raise IndexError(f"Cannot go forward {delta} step(s) (current index is {curr_idx}, total entries: {len(entries)})")
        entry_id = entries[target_idx]["id"]
        await self.send("Page.navigateToHistoryEntry", {"entryId": entry_id})
        await self.wait_for_dom_ready()
        return {"status": "ok", "url": entries[target_idx].get("url"), "title": entries[target_idx].get("title")}

    async def get_navigation_history(self) -> Dict[str, Any]:
        """Retrieve full navigation history with current index and entries."""
        hist = await self.send("Page.getNavigationHistory")
        return {
            "current_index": hist.get("currentIndex", 0),
            "entries": hist.get("entries", [])
        }

    # Preload Scripts & Stealth
    async def add_preload_script(self, source: str) -> str:
        """Inject a JavaScript snippet to evaluate on every new document before page scripts."""
        res = await self.send("Page.addScriptToEvaluateOnNewDocument", {"source": source})
        return res.get("identifier", "")

    async def remove_preload_script(self, identifier: str) -> bool:
        """Remove a previously registered preload script by its identifier."""
        await self.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": identifier})
        return True

    async def set_stealth_mode(self, enabled: bool = True) -> Dict[str, Any]:
        """Inject comprehensive anti-detection and stealth overrides (navigator.webdriver, plugins, languages)."""
        stealth_js = """(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true });
            window.chrome = window.chrome || {
                app: { isInstalled: false },
                runtime: { PlatformOs: { LINUX: 'linux' }, PlatformArch: { X86_64: 'x86-64' } }
            };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'], configurable: true });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5], configurable: true });
        })()"""
        if enabled:
            ident = await self.add_preload_script(stealth_js)
            await self.evaluate(stealth_js)
            return {"status": "ok", "stealth": True, "identifier": ident}
        return {"status": "ok", "stealth": False}

    # Network Throttling & Security
    async def set_network_throttling(
        self,
        profile: str = "none",
        offline: Optional[bool] = None,
        latency: Optional[int] = None,
        download_throughput: Optional[int] = None,
        upload_throughput: Optional[int] = None
    ) -> Dict[str, Any]:
        """Emulate network conditions ('offline', 'slow3g', 'fast3g', '4g', 'none') or custom bandwidth."""
        profiles = {
            "offline": {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
            "slow3g": {"offline": False, "latency": 400, "downloadThroughput": (500 * 1024) // 8, "uploadThroughput": (500 * 1024) // 8},
            "fast3g": {"offline": False, "latency": 150, "downloadThroughput": (1600 * 1024) // 8, "uploadThroughput": (750 * 1024) // 8},
            "4g": {"offline": False, "latency": 20, "downloadThroughput": 10 * 1024 * 1024, "uploadThroughput": 5 * 1024 * 1024},
            "none": {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1}
        }
        prof_key = profile.lower()
        cfg = profiles.get(prof_key, profiles["none"]).copy()
        if offline is not None:
            cfg["offline"] = offline
        if latency is not None:
            cfg["latency"] = latency
        if download_throughput is not None:
            cfg["downloadThroughput"] = download_throughput
        if upload_throughput is not None:
            cfg["uploadThroughput"] = upload_throughput

        await self.send("Network.emulateNetworkConditions", cfg)
        return {"status": "ok", "profile": prof_key, "conditions": cfg}

    async def set_ignore_certificate_errors(self, ignore: bool = True) -> Dict[str, Any]:
        """Bypass or enforce SSL/TLS certificate warnings on HTTPS websites."""
        await self.send("Security.setIgnoreCertificateErrors", {"ignore": ignore})
        return {"status": "ok", "ignore_certificate_errors": ignore}

    # Media Theme, Zoom & Audio
    async def set_media_theme(self, theme: str = "dark") -> Dict[str, Any]:
        """Emulate color scheme: 'dark', 'light', or 'no-preference'."""
        val = theme.lower()
        await self.send("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-color-scheme", "value": val}]
        })
        return {"status": "ok", "theme": val}

    async def set_page_zoom(self, scale: float = 1.0) -> Dict[str, Any]:
        """Set page zoom scale factor (e.g. 0.5, 0.75, 1.0, 1.25, 1.5)."""
        await self.send("Emulation.setPageScaleFactor", {"pageScaleFactor": scale})
        return {"status": "ok", "scale": scale}

    async def set_audio_muted(self, muted: bool = True) -> Dict[str, Any]:
        """Mute or unmute all media elements on the active page."""
        js = f"""(() => {{
            window.__fb_audio_muted = {json.dumps(muted)};
            document.querySelectorAll('audio, video').forEach(el => {{ el.muted = {json.dumps(muted)}; }});
            if (!window.__fb_audio_hooked) {{
                window.__fb_audio_hooked = true;
                const origPlay = HTMLMediaElement.prototype.play;
                HTMLMediaElement.prototype.play = function() {{
                    if (window.__fb_audio_muted) this.muted = true;
                    return origPlay.apply(this, arguments);
                }};
            }}
            return true;
        }})()"""
        await self.evaluate(js)
        return {"status": "ok", "muted": muted}

    # Clipboard
    async def get_clipboard_text(self) -> str:
        """Read text from clipboard with focus and timeout fallback."""
        try:
            await self.grant_permissions(["clipboardReadWrite"])
        except Exception:
            pass
        js = """(() => {
            return new Promise((resolve) => {
                const timer = setTimeout(() => resolve(''), 800);
                try { window.focus(); } catch(e) {}
                if (!navigator.clipboard || !navigator.clipboard.readText) {
                    clearTimeout(timer);
                    return resolve('');
                }
                navigator.clipboard.readText().then(text => {
                    clearTimeout(timer);
                    resolve(text || '');
                }).catch(() => {
                    clearTimeout(timer);
                    resolve('');
                });
            });
        })()"""
        try:
            return await self.evaluate(js, timeout=2.0) or ""
        except Exception:
            return ""

    async def set_clipboard_text(self, text: str) -> bool:
        """Write text to clipboard with focus and execCommand fallback."""
        try:
            await self.grant_permissions(["clipboardReadWrite"])
        except Exception:
            pass
        js = f"""(() => {{
            return new Promise((resolve) => {{
                const targetText = {json.dumps(text)};
                const timer = setTimeout(() => {{
                    try {{
                        const ta = document.createElement('textarea');
                        ta.value = targetText;
                        ta.style.position = 'fixed';
                        ta.style.opacity = '0';
                        document.body.appendChild(ta);
                        ta.focus();
                        ta.select();
                        const success = document.execCommand('copy');
                        ta.remove();
                        resolve(Boolean(success));
                    }} catch(e) {{ resolve(false); }}
                }}, 800);

                try {{ window.focus(); }} catch(e) {{}}
                if (navigator.clipboard && navigator.clipboard.writeText) {{
                    navigator.clipboard.writeText(targetText).then(() => {{
                        clearTimeout(timer);
                        resolve(true);
                    }}).catch(() => {{}});
                }}
            }});
        }})()"""
        try:
            return bool(await self.evaluate(js, timeout=2.0))
        except Exception:
            return False

    # Find in Page
    async def find_in_page(self, query: str, scroll_to_first: bool = True) -> Dict[str, Any]:
        """Search text in page, returning match count and excerpts, and scroll to first match."""
        js = f"""(() => {{
            const query = {json.dumps(query)};
            if (!query) return {{found: false, count: 0, query: '', matches: []}};
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            const matches = [];
            let node;
            let index = 0;
            const qLower = query.toLowerCase();
            while (node = walker.nextNode()) {{
                const text = node.textContent;
                const tLower = text.toLowerCase();
                let pos = tLower.indexOf(qLower);
                while (pos !== -1) {{
                    index++;
                    const start = Math.max(0, pos - 40);
                    const end = Math.min(text.length, pos + query.length + 40);
                    const snippet = text.substring(start, end).replace(/\\s+/g, ' ').trim();
                    const parent = node.parentElement;
                    matches.push({{
                        index: index,
                        snippet: snippet,
                        tag: parent ? parent.tagName.toLowerCase() : 'text'
                    }});
                    if (index === 1 && {json.dumps(scroll_to_first)} && parent) {{
                        parent.scrollIntoView({{behavior: 'smooth', block: 'center', inline: 'center'}});
                    }}
                    pos = tLower.indexOf(qLower, pos + query.length);
                }}
            }}
            return {{
                found: matches.length > 0,
                count: matches.length,
                query: query,
                matches: matches.slice(0, 30)
            }};
        }})()"""
        return await self.evaluate(js)

    # IndexedDB
    async def get_indexeddb_data(self) -> Dict[str, Any]:
        """Inspect all IndexedDB databases and object stores for current origin."""
        js = """(async () => {
            try {
                if (!window.indexedDB || !window.indexedDB.databases) {
                    return {supported: false, databases: []};
                }
                const dbs = await window.indexedDB.databases();
                const results = [];
                for (const dbInfo of dbs) {
                    const entry = {name: dbInfo.name, version: dbInfo.version, stores: []};
                    try {
                        await new Promise((resolve) => {
                            const req = window.indexedDB.open(dbInfo.name, dbInfo.version);
                            req.onsuccess = () => {
                                const db = req.result;
                                entry.stores = Array.from(db.objectStoreNames);
                                db.close();
                                resolve();
                            };
                            req.onerror = () => resolve();
                        });
                    } catch(e) {}
                    results.push(entry);
                }
                return {supported: true, databases: results};
            } catch (err) {
                return {supported: false, error: String(err), databases: []};
            }
        })()"""
        return await self.evaluate(js)

    # Network Idle
    async def wait_for_network_idle(self, idle_time: float = 0.5, timeout: float = 10.0) -> bool:
        """Wait until there are no active in-flight network requests for at least idle_time seconds."""
        t0 = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - t0) < timeout:
            if self.network.is_network_idle(idle_time):
                return True
            await asyncio.sleep(0.05)
        return False

    # Resource Blocker
    async def block_resources(
        self,
        blocked_urls: Optional[List[str]] = None,
        block_images: bool = False,
        block_media: bool = False,
        block_fonts: bool = False,
        block_ads: bool = False
    ) -> Dict[str, Any]:
        """Block network resources by URL patterns or presets (images, media, fonts, ads)."""
        patterns = list(blocked_urls or [])
        if block_images:
            patterns.extend(["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.ico", "*.svg"])
        if block_media:
            patterns.extend(["*.mp4", "*.webm", "*.ogg", "*.mp3", "*.wav", "*.m3u8"])
        if block_fonts:
            patterns.extend(["*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot"])
        if block_ads:
            patterns.extend([
                "*google-analytics.com*", "*googletagmanager.com*",
                "*doubleclick.net*", "*facebook.net*", "*adnxs.com*",
                "*hotjar.com*", "*clarity.ms*", "*yandex.ru/metrika*"
            ])
        patterns = list(dict.fromkeys(patterns))  # Deduplicate preserving order
        await self.send("Network.setBlockedURLs", {"urls": patterns})
        return {"blocked": True, "count": len(patterns), "patterns": patterns}

    # Tab Cleanup
    def cleanup_tabs(
        self,
        keep_current: bool = True,
        close_blank: bool = True,
        url_patterns: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Automatically close stale, blank, or pattern-matching tabs to free memory."""
        targets = self.list_targets()
        closed = []
        for t in targets:
            if t.get("type") != "page":
                continue
            tid = t.get("id")
            if keep_current and tid == self.target_id:
                continue
            url = t.get("url", "").lower()
            should_close = False
            if close_blank and (url in ("about:blank", "chrome://newtab/", "") or not url):
                should_close = True
            if url_patterns:
                for pat in url_patterns:
                    if pat.lower() in url or pat.lower() in t.get("title", "").lower():
                        should_close = True
                        break
            if should_close and tid:
                try:
                    self.close_tab_sync(tid)
                    closed.append({"id": tid, "url": t.get("url"), "title": t.get("title")})
                except Exception:
                    pass
        return {"closed_count": len(closed), "closed_tabs": closed}

    # Performance & Memory Metrics
    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get browser performance, DOM node count, and JS heap memory metrics."""
        await self.send("Performance.enable")
        raw = await self.send("Performance.getMetrics")
        metrics_dict = {}
        for m in raw.get("metrics", []):
            metrics_dict[m.get("name")] = m.get("value")
        
        heap_used = metrics_dict.get("JSHeapUsedSize", 0)
        heap_total = metrics_dict.get("JSHeapTotalSize", 0)
        return {
            "js_heap_used_mb": round(heap_used / (1024 * 1024), 2),
            "js_heap_total_mb": round(heap_total / (1024 * 1024), 2),
            "dom_nodes": int(metrics_dict.get("Nodes", 0)),
            "documents": int(metrics_dict.get("Documents", 0)),
            "layouts": int(metrics_dict.get("LayoutCount", 0)),
            "task_duration_s": round(metrics_dict.get("TaskDuration", 0), 3),
            "raw_metrics": metrics_dict
        }

    # Geolocation Emulation
    async def set_geolocation(self, latitude: float, longitude: float, accuracy: float = 1.0) -> Dict[str, Any]:
        """Override device geolocation coordinates."""
        await self.send("Emulation.setGeolocationOverride", {
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy
        })
        return {"success": True, "latitude": latitude, "longitude": longitude, "accuracy": accuracy}

    # Timezone Emulation
    async def set_timezone(self, timezone_id: str) -> Dict[str, Any]:
        """Override browser timezone (e.g. 'America/New_York', 'Europe/Kyiv')."""
        await self.send("Emulation.setTimezoneOverride", {"timezoneId": timezone_id})
        return {"success": True, "timezoneId": timezone_id}

    # Permissions
    async def grant_permissions(self, permissions: List[str], origin: Optional[str] = None) -> Dict[str, Any]:
        """Grant browser permissions (e.g. 'geolocation', 'notifications', 'clipboardReadWrite')."""
        if not origin:
            origin = await self.evaluate("window.location.origin")
        params = {"permissions": permissions}
        if origin and origin != "null":
            params["origin"] = origin
        await self.send("Browser.grantPermissions", params)
        return {"success": True, "permissions": permissions, "origin": origin}

    # Universal Raw CDP Method (God Mode)
    async def send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        """Send any raw Chrome DevTools Protocol command directly."""
        return await self.send(method, params or {}, timeout=timeout)

    # CSS Styles Inspection
    async def get_css_styles(self, selector: Optional[str] = None, ref: Optional[str] = None) -> Dict[str, Any]:
        """Inspect computed CSS styles and matched rules for an element."""
        if ref:
            id_num = int(str(ref).replace("@", ""))
            target_el = f"window.__fb_refs && window.__fb_refs[{id_num}]"
        elif selector:
            target_el = f"document.querySelector({json.dumps(selector)})"
        else:
            raise ValueError("Must provide either 'selector' or 'ref'")

        js = f"""(() => {{
            const el = {target_el};
            if (!el) return null;
            const computed = window.getComputedStyle(el);
            const keyProps = [
                'display', 'visibility', 'opacity', 'position', 'top', 'right', 'bottom', 'left',
                'width', 'height', 'box-sizing', 'margin', 'padding', 'border',
                'color', 'background-color', 'background-image',
                'font-family', 'font-size', 'font-weight', 'line-height',
                'flex-direction', 'justify-content', 'align-items',
                'z-index', 'overflow', 'cursor', 'pointer-events', 'transform'
            ];
            const compObj = {{}};
            for (const p of keyProps) {{
                const val = computed.getPropertyValue(p);
                if (val) compObj[p] = val;
            }}
            const matchedRules = [];
            for (const sheet of Array.from(document.styleSheets)) {{
                try {{
                    const rules = sheet.cssRules || sheet.rules;
                    for (const rule of Array.from(rules)) {{
                        if (rule.selectorText && el.matches(rule.selectorText)) {{
                            matchedRules.push({{
                                selector: rule.selectorText,
                                cssText: rule.style.cssText,
                                href: sheet.href || 'inline'
                            }});
                        }}
                    }}
                }} catch(e) {{}}
            }}
            return {{
                tag: el.tagName.toLowerCase(),
                id: el.id,
                className: el.className,
                inlineStyle: el.style.cssText,
                computed: compObj,
                matchedRules: matchedRules.slice(0, 20)
            }};
        }})()"""
        res = await self.evaluate(js)
        if not res:
            raise RuntimeError(f"Element not found for CSS style inspection (selector={selector}, ref={ref})")
        return res

    # Isolated Browser Context (Incognito)
    async def new_isolated_tab(self, url: str = "about:blank") -> Dict[str, Any]:
        """Create a new tab in a fresh, fully isolated browser context (incognito)."""
        ctx = await self.send_browser_cmd("Target.createBrowserContext")
        browser_context_id = ctx.get("browserContextId")
        target = await self.send_browser_cmd("Target.createTarget", {
            "url": url,
            "browserContextId": browser_context_id
        })
        return {
            "target_id": target.get("targetId"),
            "browser_context_id": browser_context_id,
            "url": url,
            "isolated": True
        }

    # CPU Throttling
    async def set_cpu_throttling(self, rate: float = 1.0) -> Dict[str, Any]:
        """Emulate CPU throttling (e.g. 1.0 = normal, 2.0 = 2x slowdown, 4.0 = 4x slowdown)."""
        await self.send("Emulation.setCPUThrottlingRate", {"rate": float(rate)})
        return {"rate": rate, "throttled": rate > 1.0}

    # Dialog Management
    def set_dialog_behavior(self, action: str = "accept", prompt_text: Optional[str] = None):
        """Configure auto-response behavior for future JavaScript dialogs."""
        self.dialog_action = action
        self.dialog_prompt_text = prompt_text

    async def handle_dialog(self, action: str = "accept", prompt_text: Optional[str] = None) -> Dict[str, Any]:
        """Handle active JavaScript dialog with custom action and prompt text."""
        d_params = {"accept": action.lower() == "accept"}
        if prompt_text is not None:
            d_params["promptText"] = prompt_text
        await self.send("Page.handleJavaScriptDialog", d_params)
        return {"action": action, "prompt_text": prompt_text, "handled": True}
