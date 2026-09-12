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

                elif action == "double_click":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    x = step.get("x")
                    y = step.get("y")
                    if ref or selector:
                        js = f"""(() => {{
                            const el = {f'window.__fb_refs[{int(str(ref).replace("@", ""))}]' if ref else f'document.querySelector({json.dumps(selector)})'};
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
                        }})()"""
                        coords = await self.cdp.evaluate(js)
                        if not coords:
                            raise RuntimeError("Element not found for double_click")
                        x, y = coords["x"], coords["y"]
                    if x is None or y is None:
                        raise ValueError("double_click requires (x, y) or ref/selector")
                    await self.cdp.double_click(x, y)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Double clicked at ({x}, {y})"

                elif action == "right_click":
                    ref = step.get("ref")
                    selector = step.get("selector")
                    x = step.get("x")
                    y = step.get("y")
                    if ref or selector:
                        js = f"""(() => {{
                            const el = {f'window.__fb_refs[{int(str(ref).replace("@", ""))}]' if ref else f'document.querySelector({json.dumps(selector)})'};
                            if (!el) return null;
                            const r = el.getBoundingClientRect();
                            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
                        }})()"""
                        coords = await self.cdp.evaluate(js)
                        if not coords:
                            raise RuntimeError("Element not found for right_click")
                        x, y = coords["x"], coords["y"]
                    if x is None or y is None:
                        raise ValueError("right_click requires (x, y) or ref/selector")
                    await self.cdp.right_click(x, y)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Right clicked at ({x}, {y})"

                elif action == "mouse_move":
                    x = step.get("x", 0)
                    y = step.get("y", 0)
                    await self.cdp.mouse_move(x, y)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Moved mouse to ({x}, {y})"

                elif action == "drag_and_drop":
                    start_x = step.get("start_x")
                    start_y = step.get("start_y")
                    end_x = step.get("end_x")
                    end_y = step.get("end_y")
                    from_ref = step.get("from_ref")
                    to_ref = step.get("to_ref")

                    if from_ref and to_ref:
                        js = f"""(() => {{
                            const el1 = window.__fb_refs && window.__fb_refs[{int(str(from_ref).replace("@", ""))}];
                            const el2 = window.__fb_refs && window.__fb_refs[{int(str(to_ref).replace("@", ""))}];
                            if (!el1 || !el2) return null;
                            const r1 = el1.getBoundingClientRect();
                            const r2 = el2.getBoundingClientRect();
                            return {{
                                start_x: r1.x + r1.width/2, start_y: r1.y + r1.height/2,
                                end_x: r2.x + r2.width/2, end_y: r2.y + r2.height/2
                            }};
                        }})()"""
                        coords = await self.cdp.evaluate(js)
                        if not coords:
                            raise RuntimeError("Elements not found for drag_and_drop")
                        start_x, start_y = coords["start_x"], coords["start_y"]
                        end_x, end_y = coords["end_x"], coords["end_y"]

                    if any(v is None for v in [start_x, start_y, end_x, end_y]):
                        raise ValueError("drag_and_drop requires coordinates or from_ref/to_ref")

                    await self.cdp.drag_and_drop(start_x, start_y, end_x, end_y)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"

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

                elif action == "set_user_agent":
                    ua = step.get("user_agent", "")
                    await self.cdp.set_user_agent(ua)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"User-Agent set to {ua!r}"

                elif action == "set_headers":
                    headers = step.get("headers", {})
                    await self.cdp.set_extra_headers(headers)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Injected {len(headers)} custom headers"

                elif action == "block_urls":
                    urls = step.get("urls", [])
                    await self.cdp.block_urls(urls)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Blocked {len(urls)} URL patterns"

                elif action == "set_geolocation":
                    lat = step.get("latitude", 0.0)
                    lon = step.get("longitude", 0.0)
                    await self.cdp.set_geolocation(lat, lon)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Geolocation set to ({lat}, {lon})"

                elif action == "set_timezone":
                    tz = step.get("timezone", "UTC")
                    await self.cdp.set_timezone(tz)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Timezone set to {tz}"

                elif action == "clear_cache":
                    await self.cdp.clear_cache()
                    step_res["status"] = "ok"
                    step_res["detail"] = "Cleared browser cache"

                elif action == "clear_cookies":
                    await self.cdp.clear_cookies()
                    step_res["status"] = "ok"
                    step_res["detail"] = "Cleared browser cookies"

                elif action == "set_cookie":
                    name = step.get("name")
                    val = step.get("value")
                    await self.cdp.set_cookie(name, val, domain=step.get("domain"), path=step.get("path", "/"))
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Set cookie {name}={val}"

                elif action == "upload_file":
                    selector = step.get("selector")
                    files = step.get("files", [])
                    if not selector or not files:
                        raise ValueError("upload_file requires 'selector' and 'files'")
                    await self.cdp.upload_file(selector, files)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Uploaded {len(files)} files to '{selector}'"

                elif action == "get_html":
                    html = await self.cdp.get_html()
                    step_res["status"] = "ok"
                    path = step.get("save_path")
                    if path:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(html)
                        step_res["detail"] = f"HTML saved to {path} ({len(html)} chars)"
                    else:
                        step_res["html"] = html[:10000]

                elif action == "pdf":
                    path = step.get("save_path", "page.pdf")
                    b64 = await self.cdp.print_to_pdf(landscape=step.get("landscape", False))
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    step_res["status"] = "ok"
                    step_res["detail"] = f"PDF saved to {path}"

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
                    full_page = step.get("full_page", False)
                    clip_selector = step.get("selector")
                    data_b64 = await self.cdp.capture_screenshot(full_page=full_page, clip_selector=clip_selector)
                    path = step.get("save_path")
                    if path:
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(data_b64))
                        step_res["detail"] = f"Screenshot saved to {path} (full_page={full_page})"
                    else:
                        step_res["detail"] = f"Screenshot captured ({len(data_b64)} b64 bytes)"
                    step_res["status"] = "ok"

                elif action == "window":
                    state = step.get("state")
                    width = step.get("width")
                    height = step.get("height")
                    left = step.get("left")
                    top = step.get("top")
                    if any(v is not None for v in [state, width, height, left, top]):
                        await self.cdp.set_window_bounds(state=state, width=width, height=height, left=left, top=top)
                        step_res["detail"] = f"Window updated: state={state}, size={width}x{height}, pos=({left}, {top})"
                    else:
                        win = await self.cdp.get_window_bounds()
                        step_res["window"] = win
                        step_res["detail"] = f"Window bounds: {win.get('bounds')}"
                    step_res["status"] = "ok"

                elif action == "system_page":
                    page = step.get("page") or step.get("url")
                    if not page:
                        raise ValueError("system_page action requires 'page' or 'url'")
                    res = await self.cdp.open_system_page(page)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"System page {page!r}: {res.get('status')}"
                    step_res["target"] = res.get("target")

                elif action == "extensions":
                    exts = await self.cdp.list_extensions()
                    step_res["status"] = "ok"
                    step_res["extensions"] = exts
                    step_res["detail"] = f"Found {len(exts)} extensions"

                elif action == "extension_action":
                    ext_id = step.get("id") or step.get("extension_id")
                    ext_action = step.get("action_type") or step.get("subaction")
                    if not ext_id or not ext_action:
                        raise ValueError("extension_action requires 'id' and 'action_type' ('enable', 'disable', 'reload', 'options', 'popup')")
                    res = await self.cdp.extension_action(ext_id, ext_action)
                    step_res["status"] = "ok"
                    step_res["result"] = res

                elif action == "set_download_path":
                    dl_path = step.get("path")
                    if not dl_path:
                        raise ValueError("set_download_path requires 'path'")
                    behavior = step.get("behavior", "allow")
                    await self.cdp.set_download_path(dl_path, behavior=behavior)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Download path set to {dl_path}"

                elif action == "grant_permissions":
                    perms = step.get("permissions", [])
                    origin = step.get("origin")
                    await self.cdp.grant_permissions(perms, origin=origin)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Granted permissions: {perms}"

                elif action == "system_info":
                    ver = self.cdp.get_browser_version()
                    step_res["status"] = "ok"
                    step_res["browser_version"] = ver

                elif action == "back":
                    delta = step.get("delta", 1)
                    res = await self.cdp.go_back(delta=delta)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Navigated back {delta} step(s): {res.get('url')}"

                elif action == "forward":
                    delta = step.get("delta", 1)
                    res = await self.cdp.go_forward(delta=delta)
                    step_res["status"] = "ok"
                    step_res["detail"] = f"Navigated forward {delta} step(s): {res.get('url')}"

                elif action == "history":
                    hist = await self.cdp.get_navigation_history()
                    step_res["status"] = "ok"
                    step_res["history"] = hist

                elif action == "preload_script":
                    source = step.get("source", "")
                    ident = await self.cdp.add_preload_script(source)
                    step_res["status"] = "ok"
                    step_res["identifier"] = ident
                    step_res["detail"] = f"Added preload script (id={ident})"

                elif action == "stealth":
                    enabled = step.get("enabled", True)
                    res = await self.cdp.set_stealth_mode(enabled=enabled)
                    step_res["status"] = "ok"
                    step_res["stealth"] = res

                elif action == "throttling":
                    prof = step.get("profile", "none")
                    res = await self.cdp.set_network_throttling(
                        profile=prof,
                        offline=step.get("offline"),
                        latency=step.get("latency"),
                        download_throughput=step.get("download_throughput"),
                        upload_throughput=step.get("upload_throughput")
                    )
                    step_res["status"] = "ok"
                    step_res["throttling"] = res

                elif action == "theme":
                    theme = step.get("theme", "dark")
                    res = await self.cdp.set_media_theme(theme=theme)
                    step_res["status"] = "ok"
                    step_res["theme"] = res

                elif action == "zoom":
                    scale = step.get("scale", 1.0)
                    res = await self.cdp.set_page_zoom(scale=scale)
                    step_res["status"] = "ok"
                    step_res["zoom"] = res

                elif action == "mute":
                    muted = step.get("muted", True)
                    res = await self.cdp.set_audio_muted(muted=muted)
                    step_res["status"] = "ok"
                    step_res["muted"] = res

                elif action == "clipboard":
                    subact = step.get("action_type", "read")
                    if subact == "write":
                        text = step.get("text", "")
                        await self.cdp.set_clipboard_text(text)
                        step_res["detail"] = f"Wrote to clipboard: {text[:50]}"
                    else:
                        clip_text = await self.cdp.get_clipboard_text()
                        step_res["clipboard_text"] = clip_text
                    step_res["status"] = "ok"

                elif action == "find":
                    query = step.get("query", "")
                    res = await self.cdp.find_in_page(query=query, scroll_to_first=step.get("scroll", True))
                    step_res["status"] = "ok"
                    step_res["find_result"] = res

                elif action == "indexeddb":
                    idb = await self.cdp.get_indexeddb_data()
                    step_res["status"] = "ok"
                    step_res["indexeddb"] = idb

                elif action == "ssl_ignore":
                    ignore = step.get("ignore", True)
                    res = await self.cdp.set_ignore_certificate_errors(ignore=ignore)
                    step_res["status"] = "ok"
                    step_res["ssl_ignore"] = res

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
