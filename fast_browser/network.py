import datetime
import json
import time
import urllib.parse
from collections import deque
from typing import Any

import aiofiles

SENSITIVE_HEADERS: set[str] = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "session-token",
    "x-auth-token",
    "private-token",
    "access-token",
    "secret",
    "password",
}

SENSITIVE_PARAM_KEYS: set[str] = {
    "password",
    "passwd",
    "token",
    "secret",
    "key",
    "apikey",
    "api_key",
    "access_token",
    "auth",
    "client_secret",
}


def redact_header_value(name: str, value: Any) -> str:
    """Mask sensitive header values (tokens, cookies, auth credentials)."""
    val_str = str(value) if value is not None else ""
    lname = name.lower()
    if lname in SENSITIVE_HEADERS:
        if lname in ("authorization", "proxy-authorization"):
            if val_str.lower().startswith("bearer "):
                return "Bearer [REDACTED]"
            elif val_str.lower().startswith("basic "):
                return "Basic [REDACTED]"
        return "[REDACTED]"
    return val_str


def redact_headers(headers: Any) -> Any:
    """Redact headers in either dictionary {name: val} or list [{'name': k, 'value': v}] format."""
    if isinstance(headers, dict):
        return {k: redact_header_value(k, v) for k, v in headers.items()}
    elif isinstance(headers, list):
        out = []
        for h in headers:
            if isinstance(h, dict) and "name" in h:
                out.append(
                    {
                        "name": h["name"],
                        "value": redact_header_value(
                            h["name"], h.get("value", "")
                        ),
                    }
                )
            else:
                out.append(h)
        return out
    return headers


def redact_url_params(url: str | None) -> str:
    """Mask sensitive query parameter values in URLs."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if not parsed.query:
            return url
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        redacted_params = []
        for k, v in params:
            if any(s in k.lower() for s in SENSITIVE_PARAM_KEYS):
                redacted_params.append((k, "[REDACTED]"))
            else:
                redacted_params.append((k, v))
        new_query = urllib.parse.urlencode(redacted_params, safe="[]")
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                new_query,
                parsed.fragment,
            )
        )
    except Exception:
        return url


def redact_post_data(post_data: str | None) -> str | None:
    """Mask sensitive keys in JSON or form-encoded POST bodies."""
    if not post_data:
        return post_data
    # Check if JSON
    try:
        data = json.loads(post_data)
        if isinstance(data, dict):

            def _walk_mask(obj: Any) -> Any:
                if isinstance(obj, dict):
                    res = {}
                    for k, v in obj.items():
                        if any(s in str(k).lower() for s in SENSITIVE_PARAM_KEYS):
                            res[k] = "[REDACTED]"
                        else:
                            res[k] = _walk_mask(v)
                    return res
                elif isinstance(obj, list):
                    return [_walk_mask(item) for item in obj]
                return obj

            return json.dumps(_walk_mask(data), ensure_ascii=False)
    except Exception:
        pass

    # Check if form-urlencoded (e.g. user=alice&password=secret)
    if "=" in post_data and "&" in post_data:
        try:
            params = urllib.parse.parse_qsl(post_data, keep_blank_values=True)
            redacted = []
            for k, v in params:
                if any(s in k.lower() for s in SENSITIVE_PARAM_KEYS):
                    redacted.append((k, "[REDACTED]"))
                else:
                    redacted.append((k, v))
            return urllib.parse.urlencode(redacted, safe="[]")
        except Exception:
            pass

    return post_data


class ConsoleMonitor:
    def __init__(self, max_logs: int = 500):
        self.max_logs = max_logs
        self.logs: deque = deque(maxlen=max_logs)

    def handle_event(self, method: str, params: dict[str, Any]):
        t = time.strftime("%H:%M:%S")

        if method == "Runtime.consoleAPICalled":
            log_type = params.get("type", "log")  # log, error, warning, info, debug
            args = params.get("args", [])
            text_parts = []
            for a in args:
                val = a.get("value")
                if val is not None:
                    text_parts.append(str(val))
                elif a.get("description"):
                    text_parts.append(a.get("description"))
                else:
                    text_parts.append(str(a))

            text = " ".join(text_parts)
            stack = params.get("stackTrace", {}).get("callFrames", [])
            source = stack[0].get("url", "") if stack else ""
            line = stack[0].get("lineNumber", "") if stack else ""

            self.logs.append(
                {
                    "timestamp": t,
                    "type": log_type,
                    "message": text[:2000],
                    "source": f"{source}:{line}" if source else "",
                }
            )

        elif method == "Runtime.exceptionThrown":
            exc = params.get("exceptionDetails", {})
            text = exc.get("text", "")
            desc = exc.get("exception", {}).get("description") or text
            url = exc.get("url", "")
            line = exc.get("lineNumber", "")

            self.logs.append(
                {
                    "timestamp": t,
                    "type": "error",
                    "message": desc[:2000],
                    "source": f"{url}:{line}" if url else "",
                }
            )

    def list_logs(
        self, log_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        results = []
        for log in reversed(self.logs):
            if log_type and log_type.lower() != "all":
                if log.get("type", "").lower() != log_type.lower():
                    continue
            results.append(log)
            if len(results) >= limit:
                break
        return results

    def clear(self):
        self.logs.clear()


class InFlightTracker(dict):
    """Tracks active requests with start timestamps while supporting set-like operations."""

    def add(self, item: str):
        self[item] = time.time()

    def discard(self, item: str):
        self.pop(item, None)


class NetworkMonitor:
    def __init__(self, max_requests: int = 300, max_ws_frames: int = 500):
        self.max_requests = max_requests
        self.max_ws_frames = max_ws_frames
        self.requests: dict[str, dict[str, Any]] = {}
        self.ordered_requests: deque = deque(maxlen=max_requests)
        self.ws_frames: deque = deque(maxlen=max_ws_frames)
        self.ws_connections: dict[str, str] = {}  # requestId -> url
        self.in_flight_requests = InFlightTracker()
        self.last_activity_time: float = time.time()

    def is_network_idle(
        self, idle_time: float = 0.5, timeout_ttl: float = 20.0
    ) -> bool:
        now = time.time()
        if self.in_flight_requests:
            expired = [
                rid
                for rid, start_t in list(self.in_flight_requests.items())
                if (now - start_t) > timeout_ttl
            ]
            for rid in expired:
                self.in_flight_requests.discard(rid)
        return (
            len(self.in_flight_requests) == 0
            and (now - self.last_activity_time) >= idle_time
        )

    def handle_event(self, method: str, params: dict[str, Any]):
        t = time.strftime("%H:%M:%S")
        now_ts = time.time()

        if method == "Network.requestWillBeSent":
            req_id = str(params.get("requestId", ""))
            req = params.get("request", {})
            req_type = params.get("type", "Other")
            if req_id and req_type not in ("EventSource", "WebSocket", "Ping"):
                self.in_flight_requests.add(req_id)
            self.last_activity_time = now_ts
            post_data = req.get("postData")
            if post_data and len(post_data) > 10240:
                post_data = post_data[:10240] + "... [truncated]"

            is_new = req_id not in self.requests
            # Ring buffer eviction: prune requests dict when deque limit is reached for new requests
            if is_new and len(self.ordered_requests) >= self.max_requests:
                oldest_id = self.ordered_requests[0]
                self.requests.pop(oldest_id, None)

            wall_time = params.get("wallTime", now_ts)
            entry = {
                "id": req_id,
                "url": req.get("url"),
                "method": req.get("method"),
                "headers": req.get("headers", {}),
                "postData": post_data,
                "type": req_type,
                "timestamp": t,
                "wallTime": wall_time,
                "startTime": now_ts,
                "endTime": None,
                "status": None,
                "statusText": None,
                "protocol": req.get("protocol", "HTTP/1.1"),
                "responseHeaders": {},
                "mimeType": None,
                "encodedDataLength": 0,
                "timing": None,
            }
            if "redirectResponse" in params:
                entry["redirected_from"] = params["redirectResponse"].get("url")
            self.requests[req_id] = entry
            if is_new:
                self.ordered_requests.append(req_id)

        elif method == "Network.responseReceived":
            self.last_activity_time = now_ts
            req_id = str(params.get("requestId", ""))
            resp = params.get("response", {})
            if req_id in self.requests:
                entry = self.requests[req_id]
                entry["status"] = resp.get("status")
                entry["statusText"] = resp.get("statusText")
                entry["responseHeaders"] = resp.get("headers", {})
                entry["mimeType"] = resp.get("mimeType")
                entry["protocol"] = resp.get("protocol") or entry["protocol"]
                entry["timing"] = resp.get("timing")
                if "encodedDataLength" in resp:
                    entry["encodedDataLength"] = resp.get("encodedDataLength", 0)

        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.last_activity_time = now_ts
            req_id = str(params.get("requestId", ""))
            if req_id:
                self.in_flight_requests.discard(req_id)
                if req_id in self.requests:
                    self.requests[req_id]["endTime"] = now_ts
                    if "encodedDataLength" in params:
                        self.requests[req_id]["encodedDataLength"] = params[
                            "encodedDataLength"
                        ]

        elif method == "Network.webSocketCreated":
            req_id = str(params.get("requestId", ""))
            url = str(params.get("url", ""))
            # Limit ws_connections map to prevent memory leak
            if len(self.ws_connections) > 200:
                self.ws_connections.clear()
            self.ws_connections[req_id] = url
            self.ws_frames.append(
                {
                    "timestamp": t,
                    "type": "connect",
                    "url": url,
                    "direction": "system",
                    "data": f"Connected to {url}",
                }
            )

        elif method == "Network.webSocketFrameSent":
            req_id = str(params.get("requestId", ""))
            resp = params.get("response", {})
            data = resp.get("payloadData", "")
            self.ws_frames.append(
                {
                    "timestamp": t,
                    "type": "frame",
                    "url": self.ws_connections.get(req_id, "unknown"),
                    "direction": "sent",
                    "data": data[:2000],
                }
            )

        elif method == "Network.webSocketFrameReceived":
            req_id = str(params.get("requestId", ""))
            resp = params.get("response", {})
            data = resp.get("payloadData", "")
            self.ws_frames.append(
                {
                    "timestamp": t,
                    "type": "frame",
                    "url": self.ws_connections.get(req_id, "unknown"),
                    "direction": "received",
                    "data": data[:2000],
                }
            )

        elif method == "Network.webSocketClosed":
            req_id = str(params.get("requestId", ""))
            url = self.ws_connections.pop(req_id, "unknown")
            self.ws_frames.append(
                {
                    "timestamp": t,
                    "type": "disconnect",
                    "url": url,
                    "direction": "system",
                    "data": f"WebSocket closed: {url}",
                }
            )

    def list_requests(
        self,
        filter_type: str | None = None,
        url_pattern: str | None = None,
        limit: int = 50,
        redact_sensitive_headers: bool = False,
    ) -> list[dict[str, Any]]:
        results = []
        for req_id in reversed(self.ordered_requests):
            req = self.requests.get(req_id)
            if not req:
                continue
            if filter_type and filter_type.lower() != "all":
                if req.get("type", "").lower() != filter_type.lower():
                    continue
            if url_pattern and url_pattern.lower() not in (
                req.get("url") or ""
            ).lower():
                continue

            raw_url = req.get("url") or ""
            url = (
                redact_url_params(raw_url)
                if redact_sensitive_headers
                else raw_url
            )
            results.append(
                {
                    "id": req["id"],
                    "time": req["timestamp"],
                    "method": req["method"],
                    "type": req["type"],
                    "status": req["status"],
                    "url": url,
                    "has_post_data": bool(req.get("postData")),
                }
            )
            if len(results) >= limit:
                break
        return results

    def get_request_details(
        self, req_id: str, redact_sensitive_headers: bool = False
    ) -> dict[str, Any] | None:
        req = self.requests.get(req_id)
        if not req:
            return None
        if not redact_sensitive_headers:
            return req

        copied = dict(req)
        copied["url"] = redact_url_params(copied.get("url"))
        copied["headers"] = redact_headers(copied.get("headers", {}))
        copied["responseHeaders"] = redact_headers(
            copied.get("responseHeaders", {})
        )
        copied["postData"] = redact_post_data(copied.get("postData"))
        return copied

    def list_ws_frames(
        self, direction: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        results = []
        for frame in reversed(self.ws_frames):
            if direction and frame.get("direction") != direction:
                continue
            results.append(frame)
            if len(results) >= limit:
                break
        return results

    def export_to_dict(
        self, redact_sensitive_headers: bool = False
    ) -> dict[str, Any]:
        reqs = list(self.requests.values())
        if redact_sensitive_headers:
            cleaned_reqs = []
            for r in reqs:
                cr = dict(r)
                cr["url"] = redact_url_params(cr.get("url"))
                cr["headers"] = redact_headers(cr.get("headers", {}))
                cr["responseHeaders"] = redact_headers(
                    cr.get("responseHeaders", {})
                )
                cr["postData"] = redact_post_data(cr.get("postData"))
                cleaned_reqs.append(cr)
            reqs = cleaned_reqs

        return {
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_requests": len(self.requests),
            "total_ws_frames": len(self.ws_frames),
            "requests": reqs,
            "websocket_frames": list(self.ws_frames),
        }

    def export_to_har(
        self, redact_sensitive_headers: bool = True
    ) -> dict[str, Any]:
        """Export captured requests into standards-compliant HAR 1.2 format."""
        har_entries: list[dict[str, Any]] = []

        for req in self.requests.values():
            wall_time = req.get("wallTime") or time.time()
            dt = datetime.datetime.fromtimestamp(
                wall_time, tz=datetime.timezone.utc
            )
            started_date_time = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            start_t = req.get("startTime") or wall_time
            end_t = req.get("endTime") or (start_t + 0.05)
            elapsed_ms = max(0.0, round((end_t - start_t) * 1000, 2))

            raw_url = req.get("url") or ""
            target_url = (
                redact_url_params(raw_url)
                if redact_sensitive_headers
                else raw_url
            )

            # Format request headers
            req_headers_raw = req.get("headers", {})
            req_headers = []
            req_cookies = []
            for k, v in req_headers_raw.items():
                val = (
                    redact_header_value(k, v)
                    if redact_sensitive_headers
                    else str(v)
                )
                req_headers.append({"name": k, "value": val})
                if k.lower() == "cookie":
                    # Parse cookies
                    for cookie_pair in str(v).split(";"):
                        if "=" in cookie_pair:
                            c_name, c_val = cookie_pair.strip().split("=", 1)
                            req_cookies.append(
                                {
                                    "name": c_name.strip(),
                                    "value": "[REDACTED]"
                                    if redact_sensitive_headers
                                    else c_val.strip(),
                                }
                            )

            # Query string params
            query_params = []
            try:
                parsed = urllib.parse.urlsplit(raw_url)
                for qk, qv in urllib.parse.parse_qsl(
                    parsed.query, keep_blank_values=True
                ):
                    qval = (
                        "[REDACTED]"
                        if (
                            redact_sensitive_headers
                            and any(s in qk.lower() for s in SENSITIVE_PARAM_KEYS)
                        )
                        else qv
                    )
                    query_params.append({"name": qk, "value": qval})
            except Exception:
                pass

            # Post data
            post_data_obj = None
            raw_post_data = req.get("postData")
            if raw_post_data:
                p_text = (
                    redact_post_data(raw_post_data)
                    if redact_sensitive_headers
                    else raw_post_data
                )
                content_type = req_headers_raw.get(
                    "Content-Type"
                ) or req_headers_raw.get("content-type")
                post_data_obj = {
                    "mimeType": content_type or "application/octet-stream",
                    "text": p_text,
                }

            # Response headers
            resp_headers_raw = req.get("responseHeaders", {})
            resp_headers = []
            resp_cookies = []
            for k, v in resp_headers_raw.items():
                val = (
                    redact_header_value(k, v)
                    if redact_sensitive_headers
                    else str(v)
                )
                resp_headers.append({"name": k, "value": val})
                if k.lower() == "set-cookie":
                    if "=" in str(v):
                        c_name = str(v).split("=")[0].strip()
                        resp_cookies.append(
                            {
                                "name": c_name,
                                "value": "[REDACTED]"
                                if redact_sensitive_headers
                                else str(v),
                            }
                        )

            resp_status = req.get("status") or 0
            resp_status_text = req.get("statusText") or (
                "OK" if resp_status == 200 else ""
            )
            resp_body_text = req.get("responseBody", "")
            resp_content_size = req.get("encodedDataLength") or len(
                resp_body_text.encode("utf-8", errors="replace")
            )

            entry = {
                "startedDateTime": started_date_time,
                "time": elapsed_ms,
                "request": {
                    "method": req.get("method", "GET"),
                    "url": target_url,
                    "httpVersion": req.get("protocol", "HTTP/1.1"),
                    "cookies": req_cookies,
                    "headers": req_headers,
                    "queryString": query_params,
                    "postData": post_data_obj,
                    "headersSize": -1,
                    "bodySize": len(
                        raw_post_data.encode("utf-8", errors="replace")
                    )
                    if raw_post_data
                    else 0,
                },
                "response": {
                    "status": resp_status,
                    "statusText": resp_status_text,
                    "httpVersion": req.get("protocol", "HTTP/1.1"),
                    "cookies": resp_cookies,
                    "headers": resp_headers,
                    "content": {
                        "size": resp_content_size,
                        "mimeType": req.get("mimeType")
                        or "application/octet-stream",
                        "text": resp_body_text if resp_body_text else None,
                    },
                    "redirectURL": req.get("redirected_from") or "",
                    "headersSize": -1,
                    "bodySize": req.get("encodedDataLength", -1),
                },
                "cache": {},
                "timings": {
                    "blocked": -1,
                    "dns": -1,
                    "connect": -1,
                    "send": 0,
                    "wait": elapsed_ms,
                    "receive": 0,
                },
            }
            har_entries.append(entry)

        return {
            "log": {
                "version": "1.2",
                "creator": {
                    "name": "fast-browser-mcp",
                    "version": "0.11.0",
                },
                "pages": [],
                "entries": har_entries,
            }
        }

    async def export_to_file(
        self,
        file_path: str,
        format: str = "json",
        redact_sensitive_headers: bool = True,
    ):
        is_har = format.lower() == "har" or file_path.lower().endswith(".har")
        if is_har:
            data = self.export_to_har(
                redact_sensitive_headers=redact_sensitive_headers
            )
        else:
            data = self.export_to_dict(
                redact_sensitive_headers=redact_sensitive_headers
            )

        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    def clear(self):
        self.requests.clear()
        self.ordered_requests.clear()
        self.ws_frames.clear()
        self.ws_connections.clear()
        self.in_flight_requests.clear()
