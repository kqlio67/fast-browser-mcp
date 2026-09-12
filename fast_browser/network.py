import time
from typing import Dict, Any, List, Optional
from collections import deque

class NetworkMonitor:
    def __init__(self, max_requests: int = 300, max_ws_frames: int = 500):
        self.max_requests = max_requests
        self.max_ws_frames = max_ws_frames
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.ordered_requests: deque = deque(maxlen=max_requests)
        self.ws_frames: deque = deque(maxlen=max_ws_frames)
        self.ws_connections: Dict[str, str] = {}  # requestId -> url

    def handle_event(self, method: str, params: Dict[str, Any]):
        t = time.strftime("%H:%M:%S")

        if method == "Network.requestWillBeSent":
            req_id = params.get("requestId")
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
            req_id = params.get("requestId")
            resp = params.get("response", {})
            if req_id in self.requests:
                entry = self.requests[req_id]
                entry["status"] = resp.get("status")
                entry["statusText"] = resp.get("statusText")
                entry["responseHeaders"] = resp.get("headers", {})
                entry["mimeType"] = resp.get("mimeType")

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
            
            # Return compact summary
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

    def clear(self):
        self.requests.clear()
        self.ordered_requests.clear()
        self.ws_frames.clear()
