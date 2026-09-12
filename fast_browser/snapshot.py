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
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function isInViewport(rect) {
        const h = window.innerHeight || document.documentElement.clientHeight;
        const w = window.innerWidth || document.documentElement.clientWidth;
        return rect.top < h && rect.bottom > 0 && rect.left < w && rect.right > 0;
    }

    function extractElementText(el) {
        // Direct text
        let t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
        if (t) return t;

        // Attributes
        t = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt');
        if (t) return t.trim();

        // Check child image
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

        // Check child svg
        const svg = el.querySelector('svg');
        if (svg) {
            const svgTitle = svg.querySelector('title');
            if (svgTitle && svgTitle.textContent) return svgTitle.textContent.trim();
            const svgLabel = svg.getAttribute('aria-label');
            if (svgLabel) return svgLabel.trim();
            return 'icon:svg';
        }

        // Check CSS background-image
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

        // Check meaningful class names as last resort
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim();
            if (cls && cls.length < 50) return `cls:${cls}`;
        }

        return '';
    }

    function getElementDescriptor(el) {
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
        } else if (tag === 'button' || role === 'button') {
            extra = text ? ` "${text}"` : '';
        } else if (tag === 'a') {
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
            desc: `@${id} [${role}]${extra}${vpFlag}`
        };
    }

    // Collect interactive elements
    const interactiveSelectors = [
        'button', 'a[href]', 'a[onclick]', 'input', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="tab"]',
        '[role="menuitem"]', '[onclick]', '[tabindex]:not([tabindex="-1"])'
    ];

    const rawElements = Array.from(document.querySelectorAll(interactiveSelectors.join(',')))
        .filter(isVisible);

    // Filter redundant parent/child matches if both have onclick
    const elements = [];
    for (let i = 0; i < rawElements.length; i++) {
        const curr = rawElements[i];
        // If curr is a div/table/tr and has a direct child button/input/a that is also interactive, prefer child
        const hasInteractiveChild = rawElements.some(other => other !== curr && curr.contains(other) && ['button', 'a', 'input', 'select'].includes(other.tagName.toLowerCase()));
        if (!hasInteractiveChild || ['button', 'a', 'input', 'select'].includes(curr.tagName.toLowerCase())) {
            elements.push(curr);
        }
    }

    const descriptors = elements.map(getElementDescriptor);

    // Collect headings
    const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
        .filter(isVisible)
        .map(h => `${h.tagName}: ${h.innerText.trim()}`);

    return {
        title: document.title,
        url: window.location.href,
        headings: headings,
        interactive: descriptors.map(d => d.desc),
        count: descriptors.length
    };
})()"""

class PageSnapshot:
    def __init__(self, cdp: CDPClient):
        self.cdp = cdp

    async def capture(self) -> Dict[str, Any]:
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
