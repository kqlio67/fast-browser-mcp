import time
import json
from typing import Dict, Any, List, Optional
from collections import deque

class ConsoleMonitor:
    def __init__(self, max_logs: int = 500):
        self.max_logs = max_logs
        self.logs: deque = deque(maxlen=max_logs)

    def handle_event(self, method: str, params: Dict[str, Any]):
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

            self.logs.append({
                "timestamp": t,
                "type": log_type,
                "message": text[:2000],
                "source": f"{source}:{line}" if source else ""
            })

        elif method == "Runtime.exceptionThrown":
            exc = params.get("exceptionDetails", {})
            text = exc.get("text", "")
            desc = exc.get("exception", {}).get("description") or text
            url = exc.get("url", "")
            line = exc.get("lineNumber", "")

            self.logs.append({
                "timestamp": t,
                "type": "error",
                "message": desc[:2000],
                "source": f"{url}:{line}" if url else ""
            })

    def list_logs(self, log_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
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


class NetworkMonitor:
    def __init__(self, max_requests: int = 300, max_ws_frames: int = 500):
        self.max_requests = max_requests
        self.max_ws_frames = max_ws_frames
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.ordered_requests: deque = deque(maxlen=max_requests)
        self.ws_frames: deque = deque(maxlen=max_ws_frames)
        self.ws_connections: Dict[str, str] = {}  # requestId -> url
        self.in_flight_requests: set = set()
        self.last_activity_time: float = time.time()

    def is_network_idle(self, idle_time: float = 0.5) -> bool:
        return len(self.in_flight_requests) == 0 and (time.time() - self.last_activity_time) >= idle_time

    def handle_event(self, method: str, params: Dict[str, Any]):
        t = time.strftime("%H:%M:%S")

        if method == "Network.requestWillBeSent":
            req_id = params.get("requestId")
            if req_id:
                self.in_flight_requests.add(req_id)
            self.last_activity_time = time.time()
            req = params.get("request", {})
            entry = {
                "id": req_id,
                "url": req.get("url"),
                "method": req.get("method"),
                "headers": req.get("headers", {}),
                "postData": req.get("postData"),
                "type": params.get("type", "Other"),
                "timestamp": t,
                "status": None,
                "statusText": None,
                "responseHeaders": {},
                "mimeType": None
            }
            self.requests[req_id] = entry
            self.ordered_requests.append(req_id)

        elif method == "Network.responseReceived":
            self.last_activity_time = time.time()
            req_id = params.get("requestId")
            resp = params.get("response", {})
            if req_id in self.requests:
                entry = self.requests[req_id]
                entry["status"] = resp.get("status")
                entry["statusText"] = resp.get("statusText")
                entry["responseHeaders"] = resp.get("headers", {})
                entry["mimeType"] = resp.get("mimeType")

        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            self.last_activity_time = time.time()
            req_id = params.get("requestId")
            if req_id:
                self.in_flight_requests.discard(req_id)

        elif method == "Network.webSocketCreated":
            req_id = params.get("requestId")
            url = params.get("url")
            self.ws_connections[req_id] = url
            self.ws_frames.append({
                "timestamp": t,
                "type": "connect",
                "url": url,
                "direction": "system",
                "data": f"Connected to {url}"
            })

        elif method == "Network.webSocketFrameSent":
            req_id = params.get("requestId")
            resp = params.get("response", {})
            data = resp.get("payloadData", "")
            self.ws_frames.append({
                "timestamp": t,
                "type": "frame",
                "url": self.ws_connections.get(req_id, "unknown"),
                "direction": "sent",
                "data": data[:2000]
            })

        elif method == "Network.webSocketFrameReceived":
            req_id = params.get("requestId")
            resp = params.get("response", {})
            data = resp.get("payloadData", "")
            self.ws_frames.append({
                "timestamp": t,
                "type": "frame",
                "url": self.ws_connections.get(req_id, "unknown"),
                "direction": "received",
                "data": data[:2000]
            })

    def list_requests(self, filter_type: Optional[str] = None, url_pattern: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        results = []
        for req_id in reversed(self.ordered_requests):
            req = self.requests.get(req_id)
            if not req:
                continue
            if filter_type and filter_type.lower() != "all":
                if req.get("type", "").lower() != filter_type.lower():
                    continue
            if url_pattern and url_pattern.lower() not in req.get("url", "").lower():
                continue
            
            results.append({
                "id": req["id"],
                "time": req["timestamp"],
                "method": req["method"],
                "type": req["type"],
                "status": req["status"],
                "url": req["url"],
                "has_post_data": bool(req.get("postData"))
            })
            if len(results) >= limit:
                break
        return results

    def get_request_details(self, req_id: str) -> Optional[Dict[str, Any]]:
        return self.requests.get(req_id)

    def list_ws_frames(self, direction: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        results = []
        for frame in reversed(self.ws_frames):
            if direction and frame.get("direction") != direction:
                continue
            results.append(frame)
            if len(results) >= limit:
                break
        return results

    def export_to_dict(self) -> Dict[str, Any]:
        return {
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_requests": len(self.requests),
            "total_ws_frames": len(self.ws_frames),
            "requests": list(self.requests.values()),
            "websocket_frames": list(self.ws_frames)
        }

    def export_to_file(self, file_path: str):
        data = self.export_to_dict()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear(self):
        self.requests.clear()
        self.ordered_requests.clear()
        self.ws_frames.clear()
