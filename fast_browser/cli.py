import sys
import json
import asyncio
import argparse
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
    key_p.add_argument("key", help="Key name (Enter, Escape, Tab, Backspace, ArrowDown, etc.)")

    # scroll
    scroll_p = subparsers.add_parser("scroll", help="Scroll the page")
    scroll_p.add_argument("--delta-y", type=int, default=400, help="Vertical scroll pixels")
    scroll_p.add_argument("--ref", help="Element reference to scroll to")
    scroll_p.add_argument("--selector", help="CSS selector to scroll to")

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

    # screenshot
    ss_p = subparsers.add_parser("screenshot", help="Capture screenshot")
    ss_p.add_argument("--out", default="screenshot.png", help="Output file path")

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

    # For other commands, connect to tab
    await cdp.connect(args.tab)

    if args.command == "reload":
        await cdp.reload(ignore_cache=args.ignore_cache)
        print("Page reloaded")

    elif args.command == "snapshot":
        snap = PageSnapshot(cdp)
        print(await snap.capture_formatted())

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

    elif args.command == "screenshot":
        batch = BatchRunner(cdp)
        res = await batch.execute([{"action": "screenshot", "save_path": args.out}])
        print(json.dumps(res, ensure_ascii=False, indent=2))

    await cdp.close()

def main():
    asyncio.run(run_cli())

if __name__ == "__main__":
    main()
