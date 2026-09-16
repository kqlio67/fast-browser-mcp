import json
from typing import Dict, Any, List, Optional
from .cdp import CDPClient

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
        let t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
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

    def build_snapshot_js(
        self,
        selector: Optional[str] = None,
        in_viewport: bool = False,
        max_elements: Optional[int] = None,
        start_id: int = 1,
        clear_refs: bool = True,
        default_frame_prefix: str = ""
    ) -> str:
        js = SNAPSHOT_JS
        js = js.replace("%ROOT_SELECTOR%", json.dumps(selector))
        js = js.replace("%ONLY_IN_VIEWPORT%", "true" if in_viewport else "false")
        js = js.replace("%MAX_ELEMENTS%", json.dumps(max_elements))
        js = js.replace("%START_ID%", str(int(start_id)))
        js = js.replace("%CLEAR_REFS%", "true" if clear_refs else "false")
        js = js.replace("%DEFAULT_FRAME_PREFIX%", json.dumps(default_frame_prefix))
        return js

    async def capture(self, selector: Optional[str] = None, in_viewport: bool = False, max_elements: Optional[int] = None) -> Dict[str, Any]:
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
            except Exception:
                pass

        self.cdp.ref_session_map.clear()
        js = self.build_snapshot_js(selector=selector, in_viewport=in_viewport, max_elements=max_elements, start_id=1, clear_refs=True, default_frame_prefix="")
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
                "truncated": False
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
                except Exception:
                    host = ""
                frame_name = host or frame_title or "frame"
                frame_prefix = f"(iframe:{frame_name}) "

                rem_elements = (max_elements - len(data["interactive"])) if (max_elements and max_elements > 0) else None
                if max_elements and max_elements > 0 and rem_elements is not None and rem_elements <= 0:
                    data["truncated"] = True
                    break

                child_js = self.build_snapshot_js(
                    selector=None,
                    in_viewport=in_viewport,
                    max_elements=rem_elements,
                    start_id=next_id,
                    clear_refs=True,
                    default_frame_prefix=frame_prefix
                )
                try:
                    child_data = await self.cdp.evaluate(child_js, session_id=session_id)
                    if child_data and isinstance(child_data, dict):
                        for rid in child_data.get("ref_ids", []):
                            self.cdp.ref_session_map[rid] = session_id
                        child_interactive = child_data.get("interactive", [])
                        data["interactive"].extend(child_interactive)
                        for h in child_data.get("headings", []):
                            data["headings"].append(f"({frame_name}) {h}")
                        data["total_count"] = data.get("total_count", 0) + child_data.get("total_count", len(child_interactive))
                        if child_data.get("truncated"):
                            data["truncated"] = True
                        next_id = child_data.get("next_id", next_id + len(child_interactive))
                except Exception:
                    pass

        if max_elements and max_elements > 0 and len(data["interactive"]) > max_elements:
            data["interactive"] = data["interactive"][:max_elements]
            data["truncated"] = True
        data["count"] = len(data["interactive"])

        return data

    async def capture_formatted(self, selector: Optional[str] = None, in_viewport: bool = False, max_elements: Optional[int] = None) -> str:
        data = await self.capture(selector=selector, in_viewport=in_viewport, max_elements=max_elements)
        scope_info = f" [Scope: {data.get('root')}]" if data.get('root') != "document" else ""
        vp_info = " [Viewport only]" if data.get('in_viewport') else ""
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
        count_label = f"{len(interactive)}" if not data.get("truncated") else f"{len(interactive)} of {total_count}"
        lines.append(f"\n--- Interactive Elements ({count_label} found) ---")
        if not interactive:
            lines.append("(No interactive elements found)")
        else:
            lines.extend(interactive)
            if data.get("truncated"):
                lines.append(f"... ({total_count - len(interactive)} more elements omitted; use selector to focus)")

        return "\n".join(lines)
