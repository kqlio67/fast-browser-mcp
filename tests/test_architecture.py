import unittest
import asyncio
import time
from fast_browser.network import NetworkMonitor, InFlightTracker
from fast_browser.batch import BatchRunner
from fast_browser.cdp import CDPClient
try:
    from .base import BaseBrowserTest
except ImportError:
    from base import BaseBrowserTest

class TestArchitecture(BaseBrowserTest):
    def test_async_non_blocking_cdp_methods(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            
            # test list_targets_async
            targets = await self.cdp.list_targets_async()
            self.assertIsInstance(targets, list)
            self.assertGreater(len(targets), 0)

            # test find_target_async
            t = await self.cdp.find_target_async(target_type="page")
            self.assertIsNotNone(t)

            # test get_target_by_id_async
            by_id = await self.cdp.get_target_by_id_async(self.tab_id)
            self.assertIsNotNone(by_id)
            self.assertEqual(by_id["id"], self.tab_id)

            # test get_browser_version_async
            ver = await self.cdp.get_browser_version_async()
            self.assertIn("Browser", ver)

            await self.cdp.close()

        asyncio.run(run())

    def test_batch_validation_preflight(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            runner = BatchRunner(self.cdp)

            # Test unknown action
            res = await runner.execute([{"action": "unknown_action_xyz"}])
            self.assertFalse(res["success"])
            self.assertIn("unknown action", res["error"])

            # Test missing required field (navigate without url)
            res2 = await runner.execute([{"action": "navigate"}])
            self.assertFalse(res2["success"])
            self.assertIn("missing required 'url'", res2["error"])

            # Test missing target (fill without ref/selector)
            res3 = await runner.execute([{"action": "fill", "text": "hello"}])
            self.assertFalse(res3["success"])
            self.assertIn("requires 'ref' or 'selector'", res3["error"])

            # Test valid execution passes validation
            res4 = await runner.execute([
                {"action": "eval", "expression": "10 * 10"},
                {"action": "wait", "ms": 10}
            ])
            self.assertTrue(res4["success"])
            self.assertEqual(res4["results"][0]["result"], 100)

            await self.cdp.close()

        asyncio.run(run())

    def test_network_monitor_memory_bounding(self):
        monitor = NetworkMonitor(max_requests=10, max_ws_frames=20)

        # 1. Pump 30 requests into monitor with max_requests=10
        for i in range(30):
            monitor.handle_event("Network.requestWillBeSent", {
                "requestId": f"req_{i}",
                "request": {
                    "url": f"https://example.com/item/{i}",
                    "method": "POST",
                    "postData": "A" * 20000
                },
                "type": "XHR"
            })

        # Check that requests dict is strictly bounded to max_requests
        self.assertEqual(len(monitor.ordered_requests), 10)
        self.assertEqual(len(monitor.requests), 10)
        self.assertNotIn("req_0", monitor.requests)  # Evicted
        self.assertIn("req_29", monitor.requests)    # Kept

        # Check that postData was safely truncated
        last_req = monitor.requests["req_29"]
        self.assertTrue(last_req["postData"].endswith("... [truncated]"))
        self.assertLessEqual(len(last_req["postData"]), 10300)

        # 2. Test WebSocket closed event & cleanup
        monitor.handle_event("Network.webSocketCreated", {
            "requestId": "ws_1",
            "url": "wss://example.com/socket"
        })
        self.assertIn("ws_1", monitor.ws_connections)

        monitor.handle_event("Network.webSocketClosed", {
            "requestId": "ws_1"
        })
        self.assertNotIn("ws_1", monitor.ws_connections)
        self.assertEqual(monitor.ws_frames[-1]["type"], "disconnect")

        # 3. Test clear()
        monitor.clear()
        self.assertEqual(len(monitor.requests), 0)
        self.assertEqual(len(monitor.ordered_requests), 0)
        self.assertEqual(len(monitor.ws_frames), 0)
        self.assertEqual(len(monitor.ws_connections), 0)
        self.assertEqual(len(monitor.in_flight_requests), 0)

    def test_batch_block_urls_and_system_info(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            runner = BatchRunner(self.cdp)

            # 1. Test block_urls accepts 'patterns'
            res1 = await runner.execute([
                {"action": "block_urls", "patterns": ["*.analytics.com", "*.tracker.org"]}
            ])
            self.assertTrue(res1["success"], res1.get("error"))
            self.assertIn("Blocked 2 URL patterns", res1["results"][0]["detail"])

            # 2. Test block_urls also accepts 'urls'
            res2 = await runner.execute([
                {"action": "block_urls", "urls": ["*.ads.com"]}
            ])
            self.assertTrue(res2["success"], res2.get("error"))
            self.assertIn("Blocked 1 URL patterns", res2["results"][0]["detail"])

            # 3. Test system_info works asynchronously and returns browser_version
            res3 = await runner.execute([
                {"action": "system_info"}
            ])
            self.assertTrue(res3["success"], res3.get("error"))
            self.assertIn("browser_version", res3["results"][0])
            self.assertIn("Browser", res3["results"][0]["browser_version"])

            await self.cdp.close()

        asyncio.run(run())

    def test_network_monitor_streaming_and_redirects(self):
        monitor = NetworkMonitor(max_requests=5)

        # 1. Streaming requests (EventSource, WebSocket, Ping) should NOT be added to in_flight_requests
        monitor.handle_event("Network.requestWillBeSent", {
            "requestId": "sse_1",
            "request": {"url": "https://example.com/events", "method": "GET"},
            "type": "EventSource"
        })
        self.assertNotIn("sse_1", monitor.in_flight_requests)

        monitor.handle_event("Network.requestWillBeSent", {
            "requestId": "ws_req",
            "request": {"url": "wss://example.com/stream", "method": "GET"},
            "type": "WebSocket"
        })
        self.assertNotIn("ws_req", monitor.in_flight_requests)

        # Standard XHR request SHOULD be in in_flight_requests
        monitor.handle_event("Network.requestWillBeSent", {
            "requestId": "xhr_1",
            "request": {"url": "https://example.com/api", "method": "POST"},
            "type": "XHR"
        })
        self.assertIn("xhr_1", monitor.in_flight_requests)

        # 2. Test InFlightTracker TTL expiration in is_network_idle
        tracker = InFlightTracker()
        tracker.add("stalled_req")
        tracker["stalled_req"] = time.time() - 30.0  # simulated old timestamp
        monitor.in_flight_requests = tracker
        monitor.last_activity_time = time.time() - 1.0

        # is_network_idle with timeout_ttl=20 should expire stalled_req and report True
        self.assertTrue(monitor.is_network_idle(idle_time=0.5, timeout_ttl=20.0))
        self.assertNotIn("stalled_req", monitor.in_flight_requests)

        # 3. Test HTTP redirect handling without duplicate ring buffer eviction
        monitor.clear()
        monitor.handle_event("Network.requestWillBeSent", {
            "requestId": "req_red",
            "request": {"url": "http://example.com", "method": "GET"},
            "type": "Document"
        })
        self.assertEqual(len(monitor.ordered_requests), 1)

        # Redirect arrives with same requestId
        monitor.handle_event("Network.requestWillBeSent", {
            "requestId": "req_red",
            "request": {"url": "https://example.com", "method": "GET"},
            "redirectResponse": {"url": "http://example.com"},
            "type": "Document"
        })
        # Should not duplicate in ordered_requests
        self.assertEqual(len(monitor.ordered_requests), 1)
        self.assertIn("req_red", monitor.requests)
        self.assertEqual(monitor.requests["req_red"]["url"], "https://example.com")
        self.assertEqual(monitor.requests["req_red"]["redirected_from"], "http://example.com")

    def test_cdp_connect_lock_and_compounding_timeouts(self):
        client = CDPClient(port=self.test_port)
        # Verify connect_lock property is present and working
        lock1 = client.connect_lock
        lock2 = client.connect_lock
        self.assertIs(lock1, lock2)
        self.assertIsInstance(lock1, asyncio.Lock)

        async def run():
            await client.connect(target_id=self.tab_id)
            # Test navigation with remaining timeout handling
            res = await client.navigate("about:blank", wait_until_loaded=True, timeout=5.0)
            self.assertIn("frameId", res)
            await client.close()

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
