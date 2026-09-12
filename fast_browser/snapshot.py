import json
from typing import Dict, Any, List
from .cdp import CDPClient

SNAPSHOT_JS = """(() => {
    window.__fb_refs = window.__fb_refs || {};
    const refs = {};
    window.__fb_refs = refs;
    let nextId = 1;

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

    let allDescriptors = collectFromRoot(document);

    // Recursively collect from accessible iframes
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

    const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
        .filter(isVisible)
        .map(h => `${h.tagName}: ${h.innerText.trim()}`);

    return {
        title: document.title,
        url: window.location.href,
        headings: headings,
        interactive: allDescriptors.map(d => d.desc),
        count: allDescriptors.length
    };
})()"""

class PageSnapshot:
    def __init__(self, cdp: CDPClient):
        self.cdp = cdp

    async def capture(self) -> Dict[str, Any]:
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
        data = await self.cdp.evaluate(SNAPSHOT_JS)
        return data

    async def capture_formatted(self) -> str:
        data = await self.capture()
        lines = [
            f"=== Page: {data.get('title')} ===",
            f"URL: {data.get('url')}",
        ]
        
        headings = data.get("headings", [])
        if headings:
            lines.append("\n--- Headings ---")
            lines.extend(headings[:10])

        interactive = data.get("interactive", [])
        lines.append(f"\n--- Interactive Elements ({len(interactive)} found) ---")
        if not interactive:
            lines.append("(No interactive elements found)")
        else:
            lines.extend(interactive)

        return "\n".join(lines)
