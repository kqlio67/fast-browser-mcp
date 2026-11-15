"""Smart Semantic Element Finder for AI agents.

Locates interactive elements by natural language intent (e.g. 'checkout button',
'email input field', 'search box') by analyzing text, ARIA attributes, element roles,
and context without relying on brittle CSS classes.
"""

import json
from typing import Any

FINDER_JS = r"""((intentQuery, targetRole, maxResults) => {
    window.__fb_refs = window.__fb_refs || {};
    const refs = window.__fb_refs;
    let nextId = 1;
    while (refs[nextId]) nextId++;

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

    function getRefForElement(el) {
        for (const [k, v] of Object.entries(refs)) {
            if (v === el) return parseInt(k, 10);
        }
        const id = nextId++;
        refs[id] = el;
        return id;
    }

    function generateCssSelector(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
        const role = el.getAttribute('role');
        if (role) return `${el.tagName.toLowerCase()}[role="${CSS.escape(role)}"]`;
        let path = [];
        let curr = el;
        while (curr && curr.nodeType === Node.ELEMENT_NODE && curr !== document.body && curr !== document.documentElement) {
            let selector = curr.tagName.toLowerCase();
            let siblingIndex = 1;
            let sibling = curr.previousElementSibling;
            while (sibling) {
                if (sibling.tagName === curr.tagName) siblingIndex++;
                sibling = sibling.previousElementSibling;
            }
            if (siblingIndex > 1) selector += `:nth-of-type(${siblingIndex})`;
            path.unshift(selector);
            curr = curr.parentElement;
        }
        return path.join(' > ') || el.tagName.toLowerCase();
    }

    const queryTokens = (intentQuery || '').toLowerCase().trim().split(/\s+/).filter(Boolean);
    if (queryTokens.length === 0) return [];

    const candidates = Array.from(document.querySelectorAll('button, a, input, select, textarea, [role], [onclick], [tabindex]'))
        .filter(isVisible);

    const scored = [];

    for (const el of candidates) {
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute('role') || tag).toLowerCase();
        if (targetRole && !role.includes(targetRole.toLowerCase())) continue;

        const text = (el.innerText || el.textContent || '').trim().toLowerCase();
        const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
        const title = (el.getAttribute('title') || '').toLowerCase();
        const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
        const name = (el.getAttribute('name') || '').toLowerCase();
        const idStr = (el.id || '').toLowerCase();
        const val = (el.value || '').toLowerCase();

        const combinedText = [text, ariaLabel, title, placeholder, name, idStr, val].join(' ');

        let matches = 0;
        for (const token of queryTokens) {
            if (combinedText.includes(token)) {
                matches++;
            }
        }

        if (matches === 0) continue;

        let score = matches / queryTokens.length;

        // Exact match bonus
        if (text === intentQuery.toLowerCase() || ariaLabel === intentQuery.toLowerCase()) {
            score += 0.4;
        } else if (text.includes(intentQuery.toLowerCase()) || ariaLabel.includes(intentQuery.toLowerCase())) {
            score += 0.2;
        }

        // Role alignment bonus
        if (queryTokens.includes('button') && (tag === 'button' || role === 'button')) score += 0.15;
        if (queryTokens.includes('input') && (tag === 'input' || role === 'textbox')) score += 0.15;
        if (queryTokens.includes('link') && (tag === 'a' || role === 'link')) score += 0.15;

        const rect = el.getBoundingClientRect();
        const refId = getRefForElement(el);

        scored.push({
            score: Math.min(Math.round(score * 100) / 100, 1.0),
            ref: `@${refId}`,
            ref_id: refId,
            tag: tag,
            role: role,
            text: text.slice(0, 80),
            aria_label: ariaLabel,
            placeholder: placeholder,
            selector: generateCssSelector(el),
            rect: {
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        });
    }

    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, maxResults || 5);
})"""


async def smart_find_elements(
    cdp_client: Any,
    intent: str,
    role: str | None = None,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Find matching DOM elements by semantic intent query."""
    js = f"({FINDER_JS})({json.dumps(intent)}, {json.dumps(role)}, {int(max_results)})"
    try:
        res = await cdp_client.evaluate(js)
        if isinstance(res, list):
            # Record ref mappings in client
            for item in res:
                rid = item.get("ref_id")
                if rid is not None:
                    cdp_client.ref_session_map[rid] = None
            return res
        return []
    except Exception:
        return []
