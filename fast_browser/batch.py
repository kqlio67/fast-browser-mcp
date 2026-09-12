import asyncio
import json
import base64
import time
from typing import List, Dict, Any
from .cdp import CDPClient
from .snapshot import PageSnapshot

class BatchRunner:
    def __init__(self, cdp: CDPClient):
        self.cdp = cdp
        self.snapshot_tool = PageSnapshot(cdp)

    async def execute(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        t0 = time.perf_counter()

        for idx, step in enumerate(steps):
            action = step.get("action", "").lower()
            step_t0 = time.perf_counter()
            step_res: Dict[str, Any] = {"step": idx + 1, "action": action}

            try:
                if action == "navigate":
                    url = step.get("url")
                    if not url:
                        raise ValueError("Missing 'url' for navigate action")
                    await self.cdp.navigate(url)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Navigated to {url}"

                elif action == "reload":
                    ignore_cache = step.get("ignore_cache", False)
                    await self.cdp.reload(ignore_cache=ignore_cache)
                    step_res["status"] = "ok"
                    step_res["detail"] = "Page reloaded"

                elif action == "click":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    if ref:
                        id_num = int(str(ref).replace("@", ""))
                        js = f"""(() => {{
                            const el = window.__fb_refs && window.__fb_refs[{id_num}];
                            if (!el) return false;
                            el.scrollIntoView({{block: 'center', inline: 'center'}});
                            el.click();
                            return true;
                        }})()"""
                        success = await self.cdp.evaluate(js)
                        if not success:
                            raise RuntimeError(f"Reference {ref} not found or expired. Run 'snapshot' again.")
                        step_res["detail"] = f"Clicked ref {ref}"
                    elif selector:
                        await self.cdp.click(selector, timeout_ms=step.get("timeout_ms", 3000))
                        step_res["detail"] = f"Clicked selector '{selector}'"
                    else:
                        raise ValueError("Click action requires 'ref' or 'selector'")
                    step_res["status"] = "ok"

                elif action == "fill":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    text = step.get("text", "")
                    clear = step.get("clear", True)

                    if ref:
                        id_num = int(str(ref).replace("@", ""))
                        js = f"""(() => {{
                            const el = window.__fb_refs && window.__fb_refs[{id_num}];
                            if (!el) return false;
                            el.scrollIntoView({{block: 'center', inline: 'center'}});
                            el.focus();
                            if ({json.dumps(clear)}) el.value = '';
                            el.value = {json.dumps(text)};
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return true;
                        }})()"""
                        success = await self.cdp.evaluate(js)
                        if not success:
                            raise RuntimeError(f"Reference {ref} not found or expired. Run 'snapshot' again.")
                        step_res["detail"] = f"Filled ref {ref} with {text!r}"
                    elif selector:
                        await self.cdp.fill(selector, text, clear=clear, timeout_ms=step.get("timeout_ms", 3000))
                        step_res["detail"] = f"Filled selector '{selector}' with {text!r}"
                    else:
                        raise ValueError("Fill action requires 'ref' or 'selector'")
                    step_res["status"] = "ok"

                elif action == "press_key":
                    key = step.get("key")
                    if not key:
                        raise ValueError("Missing 'key' for press_key action")
                    await self.cdp.press_key(key)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Pressed key {key!r}"

                elif action == "scroll":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    delta_y = step.get("delta_y", 400)
                    delta_x = step.get("delta_x", 0)

                    if ref:
                        id_num = int(str(ref).replace("@", ""))
                        js = f"""(() => {{
                            const el = window.__fb_refs && window.__fb_refs[{id_num}];
                            if (!el) return false;
                            el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                            return true;
                        }})()"""
                        await self.cdp.evaluate(js)
                        step_res["detail"] = f"Scrolled to ref {ref}"
                    elif selector:
                        await self.cdp.scroll_to_element(selector)
                        step_res["detail"] = f"Scrolled to selector '{selector}'"
                    else:
                        await self.cdp.scroll(delta_x=delta_x, delta_y=delta_y)
                        step_res["detail"] = f"Scrolled by ({delta_x}, {delta_y})"
                    step_res["status"] = "ok"

                elif action == "select_option":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    value = step.get("value")
                    text = step.get("text")

                    if ref:
                        id_num = int(str(ref).replace("@", ""))
                        js = f"""(() => {{
                            const el = window.__fb_refs && window.__fb_refs[{id_num}];
                            if (!el || el.tagName.toLowerCase() !== 'select') return false;
                            for (let i = 0; i < el.options.length; i++) {{
                                const opt = el.options[i];
                                if ({json.dumps(value)} !== null && opt.value === {json.dumps(value)}) {{
                                    el.selectedIndex = i;
                                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                                if ({json.dumps(text)} !== null && opt.text.trim().toLowerCase() === {json.dumps(text or '')}.toLowerCase()) {{
                                    el.selectedIndex = i;
                                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                    return true;
                                }}
                            }}
                            return false;
                        }})()"""
                        success = await self.cdp.evaluate(js)
                        if not success:
                            raise RuntimeError(f"Could not select option in ref {ref}")
                        step_res["detail"] = f"Selected option in ref {ref}"
                    elif selector:
                        success = await self.cdp.select_option(selector, value=value, text=text)
                        if not success:
                            raise RuntimeError(f"Could not select option in selector '{selector}'")
                        step_res["detail"] = f"Selected option in selector '{selector}'"
                    else:
                        raise ValueError("select_option requires 'ref' or 'selector'")
                    step_res["status"] = "ok"

                elif action == "hover":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    if ref:
                        id_num = int(str(ref).replace("@", ""))
                        js = f"""(() => {{
                            const el = window.__fb_refs && window.__fb_refs[{id_num}];
                            if (!el) return false;
                            el.dispatchEvent(new MouseEvent('mouseover', {{ bubbles: true }}));
                            el.dispatchEvent(new MouseEvent('mouseenter', {{ bubbles: true }}));
                            return true;
                        }})()"""
                        await self.cdp.evaluate(js)
                        step_res["detail"] = f"Hovered ref {ref}"
                    elif selector:
                        js = f"""(() => {{
                            const el = document.querySelector({json.dumps(selector)});
                            if (!el) return false;
                            el.dispatchEvent(new MouseEvent('mouseover', {{ bubbles: true }}));
                            el.dispatchEvent(new MouseEvent('mouseenter', {{ bubbles: true }}));
                            return true;
                        }})()"""
                        await self.cdp.evaluate(js)
                        step_res["detail"] = f"Hovered selector '{selector}'"
                    else:
                        raise ValueError("Hover action requires 'ref' or 'selector'")
                    step_res["status"] = "ok"

                elif action == "set_viewport":
                    w = step.get("width", 1280)
                    h = step.get("height", 800)
                    mobile = step.get("mobile", False)
                    await self.cdp.set_viewport(width=w, height=h, mobile=mobile)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Viewport set to {w}x{h} (mobile={mobile})"

                elif action == "upload_file":
                    selector = step.get("selector")
                    files = step.get("files", [])
                    if not selector or not files:
                        raise ValueError("upload_file requires 'selector' and 'files'")
                    await self.cdp.upload_file(selector, files)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Uploaded {len(files)} files to '{selector}'"

                elif action == "get_storage":
                    data = await self.cdp.get_storage()
                    step_res["status"] = "ok"
                    step_res["storage"] = data

                elif action == "export_traffic":
                    path = step.get("save_path", "traffic_export.json")
                    self.cdp.network.export_to_file(path)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Traffic exported to {path}"

                elif action == "console_logs":
                    limit = step.get("limit", 20)
                    logs = self.cdp.console.list_logs(limit=limit)
                    step_res["status"] = "ok"
                    step_res["console_logs"] = logs

                elif action == "wait":
                    ms = step.get("ms")
                    selector = step.get("selector")
                    text = step.get("text")
                    if ms:
                        await asyncio.sleep(ms / 1000.0)
                        step_res["detail"] = f"Waited {ms}ms"
                    elif selector:
                        found = await self.cdp.wait_for_selector(selector, timeout_ms=step.get("timeout_ms", 5000))
                        step_res["detail"] = f"Waited for selector '{selector}' (found={found})"
                    elif text:
                        found = await self.cdp.wait_for_text(text, timeout_ms=step.get("timeout_ms", 5000))
                        step_res["detail"] = f"Waited for text {text!r} (found={found})"
                    step_res["status"] = "ok"

                elif action == "eval":
                    script = step.get("script")
                    if not script:
                        raise ValueError("Missing 'script' for eval action")
                    val = await self.cdp.evaluate(script)
                    step_res["status"] = "ok"
                    step_res["result"] = val

                elif action == "snapshot":
                    snap = await self.snapshot_tool.capture_formatted()
                    step_res["status"] = "ok"
                    step_res["snapshot"] = snap

                elif action == "extract":
                    selector = step.get("selector")
                    mode = step.get("mode", "text")
                    if not selector:
                        raise ValueError("Missing 'selector' for extract action")
                    js = f"""(() => {{
                        const elements = Array.from(document.querySelectorAll({json.dumps(selector)}));
                        if ({json.dumps(mode)} === 'html') {{
                            return elements.map(e => e.outerHTML);
                        }}
                        return elements.map(e => e.innerText.trim());
                    }})()"""
                    extracted = await self.cdp.evaluate(js)
                    step_res["status"] = "ok"
                    step_res["extracted"] = extracted

                elif action == "network_requests":
                    filter_type = step.get("type")
                    url_pattern = step.get("url")
                    limit = step.get("limit", 20)
                    reqs = self.cdp.network.list_requests(filter_type=filter_type, url_pattern=url_pattern, limit=limit)
                    step_res["status"] = "ok"
                    step_res["requests"] = reqs

                elif action == "ws_messages":
                    direction = step.get("direction")
                    limit = step.get("limit", 20)
                    frames = self.cdp.network.list_ws_frames(direction=direction, limit=limit)
                    step_res["status"] = "ok"
                    step_res["ws_frames"] = frames

                elif action == "screenshot":
                    data_b64 = await self.cdp.capture_screenshot()
                    path = step.get("save_path")
                    if path:
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(data_b64))
                        step_res["detail"] = f"Screenshot saved to {path}"
                    else:
                        step_res["detail"] = f"Screenshot captured ({len(data_b64)} b64 bytes)"
                    step_res["status"] = "ok"

                else:
                    raise ValueError(f"Unknown action: {action!r}")

            except Exception as exc:
                step_res["status"] = "error"
                step_res["error"] = str(exc)
                results.append(step_res)
                break

            step_res["duration_ms"] = round((time.perf_counter() - step_t0) * 1000, 2)
            results.append(step_res)

        total_time_ms = round((time.perf_counter() - t0) * 1000, 2)
        all_ok = all(r.get("status") == "ok" for r in results)

        return {
            "success": all_ok,
            "total_duration_ms": total_time_ms,
            "steps_executed": len(results),
            "results": results
        }
