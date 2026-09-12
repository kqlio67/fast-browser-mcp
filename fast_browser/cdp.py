import asyncio
import json
import logging
import requests
import websockets
from typing import Dict, Any, Optional, List, Union
from .network import NetworkMonitor

logger = logging.getLogger("fast_browser.cdp")

# Common key definitions for Input.dispatchKeyEvent
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
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self.auto_accept_dialogs = True
        self.last_dialog_message: Optional[str] = None
        self.network = NetworkMonitor()

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

        # Enable necessary domains
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

                # Automatic Dialog handling (alert, confirm, prompt)
                if method == "Page.javascriptDialogOpening":
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
        target = res.json()
        return target

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
            # Special keys
            kd = {"type": "rawKeyDown", **key_def}
            ku = {"type": "keyUp", **key_def}
            await self.send("Input.dispatchKeyEvent", kd)
            if "text" in key_def:
                await self.send("Input.dispatchKeyEvent", {"type": "char", "text": key_def["text"]})
            await self.send("Input.dispatchKeyEvent", ku)
        else:
            # Regular characters
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

    async def capture_screenshot(self, format: str = "png", quality: Optional[int] = None) -> str:
        params: Dict[str, Any] = {"format": format}
        if quality is not None:
            params["quality"] = quality
        res = await self.send("Page.captureScreenshot", params)
        return res.get("data", "")
