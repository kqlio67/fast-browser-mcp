import sys
import json
import asyncio
import argparse
import base64
from typing import Optional

from .cdp import CDPClient
from .snapshot import PageSnapshot
from .batch import BatchRunner

async def run_cli():
    parser = argparse.ArgumentParser(description="Fast Browser CDP CLI")
    parser.add_argument("--host", default="127.0.0.1", help="CDP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9222, help="CDP port (default: 9222)")
    parser.add_argument("--tab", default=None, help="Target tab filter (URL or title substring)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list-tabs
    subparsers.add_parser("list-tabs", help="List all open browser tabs")

    # new-tab
    new_tab_p = subparsers.add_parser("new-tab", help="Open a new browser tab")
    new_tab_p.add_argument("url", nargs="?", default="about:blank", help="URL to open")

    # close-tab
    close_tab_p = subparsers.add_parser("close-tab", help="Close a browser tab")
    close_tab_p.add_argument("--id", default=None, help="Target ID to close")

    # reload
    reload_p = subparsers.add_parser("reload", help="Reload the current page")
    reload_p.add_argument("--ignore-cache", action="store_true", help="Ignore cache")

    # snapshot
    subparsers.add_parser("snapshot", help="Take a token-efficient numbered snapshot of page elements")

    # html
    html_p = subparsers.add_parser("html", help="Extract full HTML of page")
    html_p.add_argument("--out", help="Optional output file path")

    # pdf
    pdf_p = subparsers.add_parser("pdf", help="Print page to PDF")
    pdf_p.add_argument("--out", default="page.pdf", help="Output PDF file path")
    pdf_p.add_argument("--landscape", action="store_true", help="Landscape orientation")

    # eval
    eval_p = subparsers.add_parser("eval", help="Evaluate JavaScript expression")
    eval_p.add_argument("script", help="JavaScript code to evaluate")

    # batch
    batch_p = subparsers.add_parser("batch", help="Run a batch of actions from JSON string or file")
    batch_p.add_argument("steps", help="JSON string or file path containing array of action objects")

    # click
    click_p = subparsers.add_parser("click", help="Click an element")
    click_p.add_argument("--ref", help="Element reference (e.g. @1)")
    click_p.add_argument("--selector", help="CSS selector")

    # fill
    fill_p = subparsers.add_parser("fill", help="Fill text into input")
    fill_p.add_argument("--ref", help="Element reference (e.g. @1)")
    fill_p.add_argument("--selector", help="CSS selector")
    fill_p.add_argument("--text", required=True, help="Text to fill")

    # press-key
    key_p = subparsers.add_parser("press-key", help="Press a keyboard key")
    key_p.add_argument("key", help="Key name (Enter, Escape, Tab, Backspace, etc.)")

    # scroll
    scroll_p = subparsers.add_parser("scroll", help="Scroll the page")
    scroll_p.add_argument("--delta-y", type=int, default=400, help="Vertical scroll pixels")
    scroll_p.add_argument("--ref", help="Element reference to scroll to")
    scroll_p.add_argument("--selector", help="CSS selector to scroll to")

    # mouse
    mouse_p = subparsers.add_parser("mouse", help="Mouse actions")
    mouse_p.add_argument("action", choices=["right_click", "double_click", "move", "drag_and_drop"])
    mouse_p.add_argument("--x", type=float)
    mouse_p.add_argument("--y", type=float)
    mouse_p.add_argument("--from-ref")
    mouse_p.add_argument("--to-ref")
    mouse_p.add_argument("--ref")
    mouse_p.add_argument("--selector")

    # console
    console_p = subparsers.add_parser("console", help="View captured JavaScript console logs")
    console_p.add_argument("--type", help="Filter by type (log, error, warning, info)")
    console_p.add_argument("--limit", type=int, default=30, help="Max entries")

    # storage
    subparsers.add_parser("storage", help="Dump localStorage and sessionStorage")

    # export-traffic
    exp_p = subparsers.add_parser("export-traffic", help="Export traffic dump to JSON file")
    exp_p.add_argument("output", help="Output JSON file path")

    # viewport
    vp_p = subparsers.add_parser("viewport", help="Set viewport dimensions")
    vp_p.add_argument("--width", type=int, default=1280, help="Width in pixels")
    vp_p.add_argument("--height", type=int, default=800, help="Height in pixels")
    vp_p.add_argument("--mobile", action="store_true", help="Enable mobile emulation")

    # upload
    up_p = subparsers.add_parser("upload", help="Upload file to input")
    up_p.add_argument("--selector", required=True, help="CSS selector of file input")
    up_p.add_argument("files", nargs="+", help="File paths to upload")

    # network requests
    net_p = subparsers.add_parser("requests", help="List captured network requests")
    net_p.add_argument("--type", help="Filter by type (XHR, Fetch, WebSocket, Document)")
    net_p.add_argument("--url", help="Filter by URL pattern")
    net_p.add_argument("--limit", type=int, default=30, help="Max requests")

    # response body
    resp_p = subparsers.add_parser("response", help="Get response body for request ID")
    resp_p.add_argument("request_id", help="Request ID from 'requests' command")

    # websocket messages
    ws_p = subparsers.add_parser("ws", help="List captured WebSocket frames")
    ws_p.add_argument("--direction", choices=["sent", "received"], help="Filter by direction")
    ws_p.add_argument("--limit", type=int, default=30, help="Max frames")

    # cookies
    subparsers.add_parser("cookies", help="List cookies for tab")

    # set-cookie
    sc_p = subparsers.add_parser("set-cookie", help="Set cookie")
    sc_p.add_argument("name", help="Cookie name")
    sc_p.add_argument("value", help="Cookie value")
    sc_p.add_argument("--domain", help="Cookie domain")
    sc_p.add_argument("--path", default="/", help="Cookie path")

    # clear
    clear_p = subparsers.add_parser("clear", help="Clear cache and/or cookies")
    clear_p.add_argument("--no-cache", action="store_true")
    clear_p.add_argument("--no-cookies", action="store_true")

    # screenshot
    ss_p = subparsers.add_parser("screenshot", help="Capture screenshot")
    ss_p.add_argument("--out", default="screenshot.png", help="Output file path")
    ss_p.add_argument("--full-page", action="store_true", help="Capture entire scrollable page")
    ss_p.add_argument("--selector", help="Capture specific element")

    # window
    win_p = subparsers.add_parser("window", help="Manage browser window bounds and state")
    win_p.add_argument("--state", choices=["normal", "minimized", "maximized", "fullscreen"], help="Window state")
    win_p.add_argument("--width", type=int, help="Width in pixels")
    win_p.add_argument("--height", type=int, help="Height in pixels")
    win_p.add_argument("--left", type=int, help="Left position")
    win_p.add_argument("--top", type=int, help="Top position")

    # system-page
    sys_p = subparsers.add_parser("system-page", help="Open or switch to a system page (settings, extensions, downloads, flags, etc.)")
    sys_p.add_argument("page", help="System page name (e.g. settings, extensions, downloads, history, flags)")

    # extensions
    subparsers.add_parser("extensions", help="List all installed extensions")

    # extension-action
    ext_act_p = subparsers.add_parser("extension-action", help="Perform action on an extension")
    ext_act_p.add_argument("id", help="Extension ID")
    ext_act_p.add_argument("action", choices=["enable", "disable", "reload", "options", "popup"], help="Action to perform")

    # system-info
    subparsers.add_parser("system-info", help="Display browser and CDP protocol version info")

    # download-path
    dl_p = subparsers.add_parser("download-path", help="Set browser download directory")
    dl_p.add_argument("path", help="Download directory path")
    dl_p.add_argument("--behavior", choices=["allow", "deny", "default"], default="allow", help="Download behavior")

    # permissions
    perm_p = subparsers.add_parser("permissions", help="Grant or reset browser permissions")
    perm_p.add_argument("permissions", nargs="*", default=[], help="Permissions to grant (e.g. clipboardReadWrite notifications)")
    perm_p.add_argument("--origin", help="Target origin")
    perm_p.add_argument("--reset", action="store_true", help="Reset all permissions")

    # back
    back_p = subparsers.add_parser("back", help="Navigate backward in history")
    back_p.add_argument("--delta", type=int, default=1, help="Steps backward")

    # forward
    fwd_p = subparsers.add_parser("forward", help="Navigate forward in history")
    fwd_p.add_argument("--delta", type=int, default=1, help="Steps forward")

    # history
    subparsers.add_parser("history", help="Show tab navigation history entries")

    # stealth
    stealth_p = subparsers.add_parser("stealth", help="Toggle anti-bot stealth mode")
    stealth_p.add_argument("--disable", action="store_true", help="Disable stealth mode")

    # throttling
    throt_p = subparsers.add_parser("throttling", help="Emulate network conditions")
    throt_p.add_argument("profile", choices=["offline", "slow3g", "fast3g", "4g", "none"], help="Network profile")

    # theme
    theme_p = subparsers.add_parser("theme", help="Emulate color scheme (dark, light)")
    theme_p.add_argument("theme", choices=["dark", "light", "no-preference"], help="Theme choice")

    # zoom
    zoom_p = subparsers.add_parser("zoom", help="Adjust page zoom scale")
    zoom_p.add_argument("scale", type=float, help="Scale factor (e.g. 0.75, 1.0, 1.25, 1.5)")

    # mute
    mute_p = subparsers.add_parser("mute", help="Mute or unmute tab audio")
    mute_p.add_argument("--unmute", action="store_true", help="Unmute audio")

    # find
    find_p = subparsers.add_parser("find", help="Find text on page (Ctrl+F)")
    find_p.add_argument("query", help="Text to search")

    # clipboard
    clip_p = subparsers.add_parser("clipboard", help="Read or write clipboard")
    clip_p.add_argument("--write", help="Text to write to clipboard")

    # indexeddb
    subparsers.add_parser("indexeddb", help="Inspect IndexedDB databases")

    # ssl-ignore
    ssl_p = subparsers.add_parser("ssl-ignore", help="Bypass SSL certificate errors")
    ssl_p.add_argument("--enforce", action="store_true", help="Do not ignore SSL errors")

    args = parser.parse_args()

    cdp = CDPClient(host=args.host, port=args.port)

    if args.command == "list-tabs":
        targets = cdp.list_targets()
        pages = [
            {"id": t.get("id"), "title": t.get("title"), "url": t.get("url")}
            for t in targets if t.get("type") == "page"
        ]
        print(json.dumps(pages, ensure_ascii=False, indent=2))
        return

    elif args.command == "new-tab":
        target = await cdp.new_tab(args.url)
        print(json.dumps(target, ensure_ascii=False, indent=2))
        return

    elif args.command == "close-tab":
        res = await cdp.close_tab(args.id)
        print("Closed" if res else "Failed to close")
        return

    elif args.command == "window":
        if args.state or any(v is not None for v in [args.width, args.height, args.left, args.top]):
            await cdp.set_window_bounds(state=args.state, width=args.width, height=args.height, left=args.left, top=args.top)
            bounds = await cdp.get_window_bounds()
            print(f"Window bounds updated: {json.dumps(bounds.get('bounds'), ensure_ascii=False)}")
        else:
            bounds = await cdp.get_window_bounds()
            print(json.dumps(bounds, ensure_ascii=False, indent=2))
        return

    elif args.command == "system-page":
        res = await cdp.open_system_page(args.page)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    elif args.command == "extensions":
        exts = await cdp.list_extensions()
        print(json.dumps(exts, ensure_ascii=False, indent=2))
        return

    elif args.command == "extension-action":
        res = await cdp.extension_action(args.id, args.action)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    elif args.command == "system-info":
        ver = cdp.get_browser_version()
        print(json.dumps(ver, ensure_ascii=False, indent=2))
        return

    elif args.command == "download-path":
        await cdp.set_download_path(args.path, behavior=args.behavior)
        print(f"Download path configured: {args.path} (behavior={args.behavior})")
        return

    elif args.command == "permissions":
        if args.reset:
            await cdp.reset_permissions()
            print("All browser permissions reset")
        else:
            await cdp.grant_permissions(args.permissions, origin=args.origin)
            print(f"Granted permissions: {args.permissions}")
        return

    # For other commands, connect to tab
    await cdp.connect(args.tab)

    if args.command == "reload":
        await cdp.reload(ignore_cache=args.ignore_cache)
        print("Page reloaded")

    elif args.command == "snapshot":
        snap = PageSnapshot(cdp)
        print(await snap.capture_formatted())

    elif args.command == "html":
        html = await cdp.get_html()
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"HTML saved to {args.out} ({len(html)} chars)")
        else:
            print(html[:5000])

    elif args.command == "pdf":
        b64 = await cdp.print_to_pdf(landscape=args.landscape)
        with open(args.out, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"PDF saved to {args.out}")

    elif args.command == "eval":
        res = await cdp.evaluate(args.script)
        if isinstance(res, (dict, list)):
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(res)

    elif args.command == "batch":
        steps_raw = args.steps.strip()
        if steps_raw.startswith("[") or steps_raw.startswith("{"):
            steps = json.loads(steps_raw)
        else:
            with open(steps_raw, "r", encoding="utf-8") as f:
                steps = json.load(f)
        if isinstance(steps, dict) and "steps" in steps:
            steps = steps["steps"]
        
        batch = BatchRunner(cdp)
        res = await batch.execute(steps)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "click":
        batch = BatchRunner(cdp)
        res = await batch.execute([{"action": "click", "ref": args.ref, "selector": args.selector}])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "fill":
        batch = BatchRunner(cdp)
        res = await batch.execute([{"action": "fill", "ref": args.ref, "selector": args.selector, "text": args.text}])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "press-key":
        batch = BatchRunner(cdp)
        res = await batch.execute([{"action": "press_key", "key": args.key}])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "scroll":
        batch = BatchRunner(cdp)
        res = await batch.execute([{"action": "scroll", "delta_y": args.delta_y, "ref": args.ref, "selector": args.selector}])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "mouse":
        step = {
            "action": args.action,
            "x": args.x, "y": args.y,
            "ref": args.ref, "selector": args.selector,
            "from_ref": args.from_ref, "to_ref": args.to_ref
        }
        batch = BatchRunner(cdp)
        res = await batch.execute([step])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "console":
        logs = cdp.console.list_logs(log_type=args.type, limit=args.limit)
        print(json.dumps(logs, ensure_ascii=False, indent=2))

    elif args.command == "storage":
        data = await cdp.get_storage()
        print(json.dumps(data, ensure_ascii=False, indent=2))

    elif args.command == "export-traffic":
        cdp.network.export_to_file(args.output)
        print(f"Exported traffic to {args.output}")

    elif args.command == "viewport":
        await cdp.set_viewport(width=args.width, height=args.height, mobile=args.mobile)
        print(f"Viewport set to {args.width}x{args.height} (mobile={args.mobile})")

    elif args.command == "upload":
        await cdp.upload_file(args.selector, args.files)
        print(f"Uploaded {len(args.files)} files to {args.selector}")

    elif args.command == "requests":
        reqs = cdp.network.list_requests(filter_type=args.type, url_pattern=args.url, limit=args.limit)
        print(json.dumps(reqs, ensure_ascii=False, indent=2))

    elif args.command == "response":
        details = cdp.network.get_request_details(args.request_id)
        body = await cdp.get_response_body(args.request_id)
        print(json.dumps({"request": details, "response_body": body}, ensure_ascii=False, indent=2))

    elif args.command == "ws":
        frames = cdp.network.list_ws_frames(direction=args.direction, limit=args.limit)
        print(json.dumps(frames, ensure_ascii=False, indent=2))

    elif args.command == "cookies":
        cookies = await cdp.get_cookies()
        print(json.dumps(cookies, ensure_ascii=False, indent=2))

    elif args.command == "set-cookie":
        res = await cdp.set_cookie(args.name, args.value, domain=args.domain, path=args.path)
        print("Cookie set successfully" if res else "Failed to set cookie")

    elif args.command == "clear":
        if not args.no_cache:
            await cdp.clear_cache()
        if not args.no_cookies:
            await cdp.clear_cookies()
        print("Cleared cache and/or cookies")

    elif args.command == "screenshot":
        batch = BatchRunner(cdp)
        res = await batch.execute([{
            "action": "screenshot",
            "save_path": args.out,
            "full_page": args.full_page,
            "selector": args.selector
        }])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "back":
        res = await cdp.go_back(delta=args.delta)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "forward":
        res = await cdp.go_forward(delta=args.delta)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "history":
        hist = await cdp.get_navigation_history()
        print(json.dumps(hist, ensure_ascii=False, indent=2))

    elif args.command == "stealth":
        res = await cdp.set_stealth_mode(enabled=not args.disable)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "throttling":
        res = await cdp.set_network_throttling(profile=args.profile)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "theme":
        res = await cdp.set_media_theme(theme=args.theme)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "zoom":
        res = await cdp.set_page_zoom(scale=args.scale)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "mute":
        res = await cdp.set_audio_muted(muted=not args.unmute)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "find":
        res = await cdp.find_in_page(query=args.query)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    elif args.command == "clipboard":
        if args.write is not None:
            await cdp.set_clipboard_text(args.write)
            print(f"Copied to clipboard: {args.write[:50]}")
        else:
            text = await cdp.get_clipboard_text()
            print(text)

    elif args.command == "indexeddb":
        idb = await cdp.get_indexeddb_data()
        print(json.dumps(idb, ensure_ascii=False, indent=2))

    elif args.command == "ssl-ignore":
        res = await cdp.set_ignore_certificate_errors(ignore=not args.enforce)
        print(json.dumps(res, ensure_ascii=False, indent=2))

    await cdp.close()

def main():
    asyncio.run(run_cli())

if __name__ == "__main__":
    main()
