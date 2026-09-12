import unittest
import asyncio
from fast_browser.network import NetworkMonitor
from fast_browser.batch import BatchRunner
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

if __name__ == "__main__":
    unittest.main()
