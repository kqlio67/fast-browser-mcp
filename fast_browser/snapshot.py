import json
import logging
from typing import Any

from .cdp import CDPClient

logger = logging.getLogger("fast_browser.snapshot")

SNAPSHOT_JS = r"""(() => {
    window.__fb_refs = window.__fb_refs || {};
    const refs = %CLEAR_REFS% ? {} : window.__fb_refs;
    window.__fb_refs = refs;
    let nextId = %START_ID%;

    function isVisible(el) {
        if (!el) return false;
        try {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        } catch(e) {
            return false;
        }
    }

    function isInViewport(rect) {
        const h = window.innerHeight || document.documentElement.clientHeight;
        const w = window.innerWidth || document.documentElement.clientWidth;
        return rect.top < h && rect.bottom > 0 && rect.left < w && rect.right > 0;
    }

    function extractElementText(el) {
        let t = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
        if (t) return t;

        t = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt');
        if (t) return t.trim();

        const img = el.querySelector('img');
        if (img) {
            const imgAlt = img.getAttribute('alt');
            if (imgAlt && imgAlt.trim()) return imgAlt.trim();
            const imgSrc = img.getAttribute('src');
            if (imgSrc) {
                const parts = imgSrc.split('/');
                const filename = parts[parts.length - 1].split('?')[0];
                return `img:${filename}`;
            }
        }

        const svg = el.querySelector('svg');
        if (svg) {
            const svgTitle = svg.querySelector('title');
            if (svgTitle && svgTitle.textContent) return svgTitle.textContent.trim();
            const svgLabel = svg.getAttribute('aria-label');
            if (svgLabel) return svgLabel.trim();
            return 'icon:svg';
        }

        try {
            const style = window.getComputedStyle(el);
            const bg = style.backgroundImage;
            if (bg && bg !== 'none' && !bg.includes('data:')) {
                const m = bg.match(/url\(["']?([^"']+)["']?\)/);
                if (m) {
                    const parts = m[1].split('/');
                    const filename = parts[parts.length - 1].split('?')[0];
                    return `bg:${filename}`;
                }
            }
        } catch(e) {}

        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim();
            if (cls && cls.length < 50) return `cls:${cls}`;
        }

        return '';
    }

    function getElementDescriptor(el, framePrefix = '') {
        const tag = el.tagName.toLowerCase();
        let role = el.getAttribute('role') || tag;
        let text = extractElementText(el);
        if (text.length > 70) text = text.substring(0, 67) + '...';

        const id = nextId++;
        refs[id] = el;

        const rect = el.getBoundingClientRect();
        const inVp = isInViewport(rect);
        const vpFlag = inVp ? '' : ' [scroll]';

        let extra = '';
        if (tag === 'input') {
            const type = el.type || 'text';
            const val = el.value ? ` value="${el.value}"` : '';
            const ph = el.placeholder ? ` placeholder="${el.placeholder}"` : '';
            const name = el.name ? ` name="${el.name}"` : '';
            const chk = el.checked ? ' checked' : '';
            extra = ` [type=${type}${name}${ph}${val}${chk}]`;
        } else if (tag === 'cr-toggle' || tag === 'cr-checkbox') {
            const chk = el.checked ? ' checked' : ' unchecked';
            extra = ` [${chk}]`;
        } else if (tag === 'button' || role === 'button' || tag === 'cr-button' || tag === 'cr-icon-button') {
            extra = text ? ` "${text}"` : '';
        } else if (tag === 'a' || role === 'link' || role === 'menuitem') {
            const href = el.getAttribute('href');
            const hrefStr = (href && href !== '#' && !href.startsWith('javascript:')) ? ` -> ${href}` : '';
            extra = text ? ` "${text}"${hrefStr}` : hrefStr;
        } else if (tag === 'select') {
            const selOption = el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
            extra = ` [selected="${selOption}"]`;
        } else if (tag === 'textarea') {
            const ph = el.placeholder ? ` placeholder="${el.placeholder}"` : '';
            extra = `${ph} "${text}"`;
        } else {
            extra = text ? ` "${text}"` : '';
        }

        return {
            id: id,
            ref: `@${id}`,
            tag: tag,
            role: role,
            inViewport: inVp,
            desc: `@${id} ${framePrefix}[${role}]${extra}${vpFlag}`
        };
    }

    const interactiveTags = [
        'button', 'a', 'input', 'select', 'textarea',
        'cr-button', 'cr-toggle', 'cr-checkbox', 'cr-icon-button', 'cr-link-row',
        'paper-toggle-button', 'paper-checkbox', 'paper-button'
    ];

    function isInteractiveElement(el) {
        if (!isVisible(el)) return false;
        const tag = el.tagName.toLowerCase();

        // Skip decorative inner elements of interactive containers
        const parentInteractive = el.parentElement ? el.parentElement.closest('button, a, cr-button, cr-icon-button, cr-toggle, cr-checkbox, [role="button"], [role="menuitem"], [role="tab"]') : null;
        if (parentInteractive) {
            if (['svg', 'path', 'cr-icon', 'cr-ripple', 'span', 'div', 'i'].includes(tag)) {
                return false;
            }
        }

        if (interactiveTags.includes(tag)) return true;
        if (el.getAttribute('href')) return true;
        if (el.getAttribute('onclick')) return true;
        const role = el.getAttribute('role');
        if (['button', 'link', 'checkbox', 'tab', 'menuitem', 'switch', 'radio'].includes(role)) return true;
        const tabIndex = el.getAttribute('tabindex');
        if (tabIndex && tabIndex !== '-1') return true;

        try {
            const style = window.getComputedStyle(el);
            if (style.cursor === 'pointer' && el.children.length === 0) return true;
        } catch(e) {}

        return false;
    }

    function collectFromRoot(root, framePrefix = '') {
        const found = [];
        function walk(node) {
            if (!node) return;
            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
                const el = children[i];
                if (isInteractiveElement(el)) {
                    found.push(getElementDescriptor(el, framePrefix));
                }
                // Traverse Shadow DOM
                if (el.shadowRoot) {
                    walk(el.shadowRoot);
                }
                // Traverse child elements
                if (el.children && el.children.length > 0) {
                    walk(el);
                }
            }
        }
        walk(root);
        return found;
    }

    const rootSelector = %ROOT_SELECTOR%;
    const onlyInViewport = %ONLY_IN_VIEWPORT%;
    const maxElements = %MAX_ELEMENTS%;
    const defaultFramePrefix = %DEFAULT_FRAME_PREFIX%;

    let targetRoot = document;
    if (rootSelector) {
        const found = document.querySelector(rootSelector);
        if (found) {
            targetRoot = found;
        }
    }

    let allDescriptors = collectFromRoot(targetRoot, defaultFramePrefix);

    // Recursively collect from accessible iframes if whole document
    if (!rootSelector) {
        const iframes = Array.from(document.querySelectorAll('iframe'));
        iframes.forEach((iframe, idx) => {
            try {
                const iDoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
                if (iDoc) {
                    const name = iframe.name || iframe.id || `frame_${idx+1}`;
                    const iframeDescriptors = collectFromRoot(iDoc, `(iframe:${name}) `);
                    allDescriptors = allDescriptors.concat(iframeDescriptors);
                }
            } catch(e) {}
        });
    }

    if (onlyInViewport) {
        allDescriptors = allDescriptors.filter(d => d.inViewport);
    }

    const totalFound = allDescriptors.length;
    let truncated = false;
    if (maxElements && maxElements > 0 && allDescriptors.length > maxElements) {
        allDescriptors = allDescriptors.slice(0, maxElements);
        truncated = true;
    }

    const headings = Array.from(targetRoot.querySelectorAll('h1, h2, h3, h4'))
        .filter(isVisible)
        .map(h => `${h.tagName}: ${h.innerText.trim()}`);

    return {
        title: document.title,
        url: window.location.href,
        root: rootSelector || "document",
        in_viewport: onlyInViewport,
        headings: headings,
        interactive: allDescriptors.map(d => d.desc),
        ref_ids: allDescriptors.map(d => d.id),
        next_id: nextId,
        count: allDescriptors.length,
        total_count: totalFound,
        truncated: truncated
    };
})()"""


class PageSnapshot:
    def __init__(self, cdp: CDPClient):
        self.cdp = cdp
        self.last_snapshot_text: str | None = None

    def build_snapshot_js(
        self,
        selector: str | None = None,
        in_viewport: bool = False,
        max_elements: int | None = None,
        start_id: int = 1,
        clear_refs: bool = True,
        default_frame_prefix: str = "",
    ) -> str:
        js = SNAPSHOT_JS
        js = js.replace("%ROOT_SELECTOR%", json.dumps(selector))
        js = js.replace("%ONLY_IN_VIEWPORT%", "true" if in_viewport else "false")
        js = js.replace("%MAX_ELEMENTS%", json.dumps(max_elements))
        js = js.replace("%START_ID%", str(int(start_id)))
        js = js.replace("%CLEAR_REFS%", "true" if clear_refs else "false")
        js = js.replace("%DEFAULT_FRAME_PREFIX%", json.dumps(default_frame_prefix))
        return js

    async def capture_passive(self) -> dict[str, Any]:
        """Capture accessibility tree using native CDP Accessibility domain without executing JavaScript in the page."""
        try:
            await self.cdp.send("Accessibility.enable")
            ax_resp = await self.cdp.send("Accessibility.getFullAXTree")
            nodes = ax_resp.get("nodes", [])
        except Exception as e:
            logger.debug("Accessibility.getFullAXTree failed: %s", e)
            nodes = []

        interactive_roles = {
            "button",
            "link",
            "textbox",
            "checkbox",
            "radio",
            "combobox",
            "searchbox",
            "menuitem",
            "tab",
            "switch",
            "slider",
            "spinbutton",
        }

        interactive: list[str] = []
        headings: list[str] = []
        ref_ids: list[int] = []
        next_id = 1

        self.cdp.ref_session_map.clear()

        for node in nodes:
            if node.get("ignored", False):
                continue
            role_obj = node.get("role", {})
            role = (
                role_obj.get("value", "")
                if isinstance(role_obj, dict)
                else str(role_obj)
            )
            name_obj = node.get("name", {})
            name = (
                name_obj.get("value", "")
                if isinstance(name_obj, dict)
                else str(name_obj)
            )
            name = (name or "").strip()

            if role == "heading" or "heading" in role:
                level = 1
                for prop in node.get("properties", []):
                    if prop.get("name") == "level":
                        level = prop.get("value", {}).get("value", 1)
                headings.append(f"H{level}: {name}" if name else f"H{level}")

            if role in interactive_roles or node.get("backendDOMNodeId"):
                if not name and role not in (
                    "button",
                    "textbox",
                    "searchbox",
                    "link",
                ):
                    continue
                node_id = next_id
                next_id += 1
                ref_ids.append(node_id)
                self.cdp.ref_session_map[node_id] = None

                val_obj = node.get("value", {})
                val = val_obj.get("value", "") if isinstance(val_obj, dict) else ""
                val_str = f' value="{val}"' if val else ""
                line = f"@ref:e{node_id} {role} '{name}'{val_str}"
                interactive.append(line)

        title = ""
        url = ""
        try:
            target = await self.cdp.get_target_by_id_async(
                self.cdp.target_id or ""
            )
            if target:
                title = target.get("title", "")
                url = target.get("url", "")
        except Exception:
            pass

        return {
            "title": title or "Page",
            "url": url or "",
            "root": "document (passive)",
            "in_viewport": False,
            "headings": headings[:15],
            "interactive": interactive,
            "ref_ids": ref_ids,
            "total_count": len(interactive),
            "count": len(interactive),
            "truncated": False,
            "passive": True,
        }

    async def capture(
        self,
        selector: str | None = None,
        in_viewport: bool = False,
        max_elements: int | None = None,
        passive: bool = False,
    ) -> dict[str, Any]:
        if passive:
            return await self.capture_passive()
        url = await self.cdp.evaluate("window.location.href")
        if url and ("chrome://settings" in url or "chrome://extensions" in url):
            ready_js = """(async () => {
                const uiTag = document.querySelector('settings-ui') ? 'settings-ui' : (document.querySelector('extensions-manager') ? 'extensions-manager' : null);
                if (uiTag && window.customElements) {
                    await customElements.whenDefined(uiTag);
                    const el = document.querySelector(uiTag);
                    for (let i = 0; i < 20; i++) {
                        if (el && el.shadowRoot) break;
                        await new Promise(r => setTimeout(r, 100));
                    }
                }
                return true;
            })()"""
            try:
                await self.cdp.evaluate(ready_js, timeout=3.0)
            except Exception as e:
                logger.debug(e)

        self.cdp.ref_session_map.clear()
        js = self.build_snapshot_js(
            selector=selector,
            in_viewport=in_viewport,
            max_elements=max_elements,
            start_id=1,
            clear_refs=True,
            default_frame_prefix="",
        )
        data = await self.cdp.evaluate(js)
        if not data or not isinstance(data, dict):
            return {
                "title": "",
                "url": url or "",
                "root": selector or "document",
                "in_viewport": in_viewport,
                "headings": [],
                "interactive": [],
                "count": 0,
                "total_count": 0,
                "truncated": False,
            }

        for rid in data.get("ref_ids", []):
            self.cdp.ref_session_map[rid] = None

        next_id = data.get("next_id", len(data.get("interactive", [])) + 1)

        # Cross-origin iframe child targets (OOPIF)
        if not selector and getattr(self.cdp, "frame_sessions", None):
            import urllib.parse

            for session_id, target_info in list(self.cdp.frame_sessions.items()):
                if target_info.get("type") != "iframe":
                    continue
                frame_url = target_info.get("url", "")
                frame_title = target_info.get("title", "")
                try:
                    parsed = urllib.parse.urlparse(frame_url)
                    host = parsed.netloc or parsed.path
                except Exception as e:
                    logger.debug(e)
                    host = ""
                frame_name = host or frame_title or "frame"
                frame_prefix = f"(iframe:{frame_name}) "

                rem_elements = (
                    (max_elements - len(data["interactive"]))
                    if (max_elements and max_elements > 0)
                    else None
                )
                if (
                    max_elements
                    and max_elements > 0
                    and rem_elements is not None
                    and rem_elements <= 0
                ):
                    data["truncated"] = True
                    break

                child_js = self.build_snapshot_js(
                    selector=None,
                    in_viewport=in_viewport,
                    max_elements=rem_elements,
                    start_id=next_id,
                    clear_refs=True,
                    default_frame_prefix=frame_prefix,
                )
                try:
                    child_data = await self.cdp.evaluate(
                        child_js, session_id=session_id
                    )
                    if child_data and isinstance(child_data, dict):
                        for rid in child_data.get("ref_ids", []):
                            self.cdp.ref_session_map[rid] = session_id
                        child_interactive = child_data.get("interactive", [])
                        data["interactive"].extend(child_interactive)
                        for h in child_data.get("headings", []):
                            data["headings"].append(f"({frame_name}) {h}")
                        data["total_count"] = data.get(
                            "total_count", 0
                        ) + child_data.get("total_count", len(child_interactive))
                        if child_data.get("truncated"):
                            data["truncated"] = True
                        next_id = child_data.get(
                            "next_id", next_id + len(child_interactive)
                        )
                except Exception as e:
                    logger.debug(e)

        if (
            max_elements
            and max_elements > 0
            and len(data["interactive"]) > max_elements
        ):
            data["interactive"] = data["interactive"][:max_elements]
            data["truncated"] = True
        data["count"] = len(data["interactive"])

        return data

    async def capture_formatted(
        self,
        selector: str | None = None,
        in_viewport: bool = False,
        max_elements: int | None = None,
        passive: bool = False,
    ) -> str:
        data = await self.capture(
            selector=selector,
            in_viewport=in_viewport,
            max_elements=max_elements,
            passive=passive,
        )
        scope_info = (
            f" [Scope: {data.get('root')}]" if data.get("root") != "document" else ""
        )
        vp_info = " [Viewport only]" if data.get("in_viewport") else ""
        lines = [
            f"=== Page: {data.get('title')}{scope_info}{vp_info} ===",
            f"URL: {data.get('url')}",
        ]

        headings = data.get("headings", [])
        if headings:
            lines.append("\n--- Headings ---")
            lines.extend(headings[:10])

        interactive = data.get("interactive", [])
        total_count = data.get("total_count", len(interactive))
        count_label = (
            f"{len(interactive)}"
            if not data.get("truncated")
            else f"{len(interactive)} of {total_count}"
        )
        lines.append(f"\n--- Interactive Elements ({count_label} found) ---")
        if not interactive:
            lines.append("(No interactive elements found)")
        else:
            lines.extend(interactive)
            if data.get("truncated"):
                lines.append(
                    f"... ({total_count - len(interactive)} more elements omitted; use selector to focus)"
                )

        res_str = "\n".join(lines)
        self.last_snapshot_text = res_str
        return res_str

    async def diff(
        self, previous_snapshot: str | None = None, passive: bool = False
    ) -> dict[str, Any]:
        """Compare current snapshot against previous snapshot."""
        # Fast path check: if state seq is unchanged and previous_snapshot was not manually passed,
        # we can verify via zero-cost DOM mutation counter!
        if previous_snapshot is None and self.last_snapshot_text:
            try:
                state = await self.cdp.get_page_state()
                curr_seq = state.get("seq")
                last_seq = getattr(self, "_last_diff_seq", None)
                if (
                    curr_seq is not None
                    and last_seq is not None
                    and curr_seq == last_seq
                ):
                    return {
                        "changed": False,
                        "url_changed": False,
                        "seq": curr_seq,
                        "added_count": 0,
                        "removed_count": 0,
                        "added_elements": [],
                        "removed_elements": [],
                        "text_delta": "",
                        "previous_url": state.get("url", ""),
                        "current_url": state.get("url", ""),
                        "detail": "DOM sequence unchanged (zero-cost mutation cache hit)",
                    }
                self._last_diff_seq = curr_seq
            except Exception:
                pass

        prev = previous_snapshot or self.last_snapshot_text or ""
        curr = await self.capture_formatted(passive=passive)
        res = diff_snapshots(prev, curr)
        try:
            state = await self.cdp.get_page_state()
            self._last_diff_seq = state.get("seq")
        except Exception:
            pass
        return res


def diff_snapshots(prev_text: str, curr_text: str) -> dict[str, Any]:
    """Calculate structural delta between two formatted snapshot outputs."""
    prev_lines = [
        line.strip()
        for line in prev_text.splitlines()
        if line.strip().startswith("@ref:")
    ]
    curr_lines = [
        line.strip()
        for line in curr_text.splitlines()
        if line.strip().startswith("@ref:")
    ]

    def normalize_ref(line: str) -> str:
        parts = line.split(" ", 1)
        return parts[1] if len(parts) > 1 else line

    prev_items = {normalize_ref(item): item for item in prev_lines}
    curr_items = {normalize_ref(item): item for item in curr_lines}

    added = [curr_items[k] for k in curr_items if k not in prev_items]
    removed = [prev_items[k] for k in prev_items if k not in curr_items]

    prev_url = ""
    curr_url = ""
    for text_line in prev_text.splitlines():
        if text_line.startswith("URL:"):
            prev_url = text_line.replace("URL:", "").strip()
            break
    for text_line in curr_text.splitlines():
        if text_line.startswith("URL:"):
            curr_url = text_line.replace("URL:", "").strip()
            break

    url_changed = bool(prev_url and curr_url and prev_url != curr_url)

    summary_parts = []
    if url_changed:
        summary_parts.append(f"URL changed to {curr_url}")
    if added:
        summary_parts.append(f"{len(added)} element(s) added")
    if removed:
        summary_parts.append(f"{len(removed)} element(s) removed")
    if not summary_parts:
        summary_parts.append("No structural changes detected")

    return {
        "status": "success",
        "url_changed": url_changed,
        "previous_url": prev_url,
        "current_url": curr_url,
        "added_count": len(added),
        "removed_count": len(removed),
        "added_elements": added,
        "removed_elements": removed,
        "summary": ", ".join(summary_parts),
    }
