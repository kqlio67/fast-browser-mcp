import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fast_browser.batch import BatchRunner
from fast_browser.snapshot import PageSnapshot
from tests.base import BaseBrowserTest


class TestReaCdpFeatures(BaseBrowserTest):
    # --- Event Listeners Tests ---

    def test_get_event_listeners_by_selector_and_ref(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)

            html = """
            <!DOCTYPE html>
            <html>
            <body>
                <button id="btn1">Submit</button>
                <script>
                    const b = document.getElementById("btn1");
                    function handleClick(e) { console.log("click"); }
                    function handleCustom(e) { console.log("custom"); }
                    b.addEventListener("click", handleClick, { passive: true });
                    b.addEventListener("custom_event", handleCustom, { once: true });
                </script>
            </body>
            </html>
            """
            await self.cdp.navigate(f"data:text/html,{html}")
            await asyncio.sleep(0.3)

            # 1. Test by selector
            res_sel = await self.cdp.get_event_listeners(selector="#btn1")
            self.assertEqual(res_sel["status"], "success")
            self.assertGreaterEqual(res_sel["listeners_count"], 2)

            types = [item["type"] for item in res_sel["listeners"]]
            self.assertIn("click", types)
            self.assertIn("custom_event", types)

            click_l = next(item for item in res_sel["listeners"] if item["type"] == "click")
            self.assertTrue(click_l["passive"])
            self.assertIn("handleClick", click_l["handler"])

            custom_l = next(
                item for item in res_sel["listeners"] if item["type"] == "custom_event"
            )
            self.assertTrue(custom_l["once"])

            # 2. Test by snapshot @ref
            snapshot_tool = PageSnapshot(self.cdp)
            snap = await snapshot_tool.capture()
            btn_ref = None
            for item in snap.get("interactive", []):
                if "[button]" in item or "Submit" in item:
                    btn_ref = item.split()[0]  # e.g. "@1"
                    break

            self.assertIsNotNone(btn_ref)
            res_ref = await self.cdp.get_event_listeners(ref=btn_ref)
            self.assertEqual(res_ref["status"], "success")
            self.assertGreaterEqual(res_ref["listeners_count"], 2)

            # 3. Test non-existent element
            res_none = await self.cdp.get_event_listeners(
                selector="#non-existent"
            )
            self.assertEqual(res_none["status"], "not_found")

            await self.cdp.close()

        asyncio.run(run())

    # --- Code Coverage Tests ---

    def test_v8_precise_code_coverage(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)

            html = """
            <!DOCTYPE html>
            <html>
            <body>
                <button id="calc-btn" onclick="executeAlgorithm(10)">Run</button>
                <script>
                    function executeAlgorithm(count) {
                        let total = 0;
                        for (let i = 0; i < count; i++) {
                            total += i * 2;
                        }
                        return total;
                    }
                    function unusedFunction() {
                        return "not called";
                    }
                </script>
            </body>
            </html>
            """
            await self.cdp.navigate(f"data:text/html,{html}")
            await asyncio.sleep(0.3)

            # Start coverage
            start_res = await self.cdp.start_coverage(
                detailed=True, call_count=True
            )
            self.assertEqual(start_res["status"], "started")

            # Execute code via button click
            await self.cdp.click(selector="#calc-btn")
            await asyncio.sleep(0.1)

            # Stop coverage
            stop_res = await self.cdp.stop_coverage(only_executed=True)
            self.assertEqual(stop_res["status"], "stopped")
            self.assertGreater(stop_res["total_executed_functions"], 0)

            # Check that executeAlgorithm was captured and unusedFunction was omitted
            all_funcs = []
            for s in stop_res["scripts"]:
                for f in s["functions"]:
                    all_funcs.append(f["name"])

            self.assertIn("executeAlgorithm", all_funcs)
            self.assertNotIn("unusedFunction", all_funcs)

            # Test observe_coverage helper
            obs_res = await self.cdp.observe_coverage(duration_ms=100)
            self.assertEqual(obs_res["status"], "stopped")

            await self.cdp.close()

        asyncio.run(run())

    # --- CacheStorage Tests ---

    def test_cache_storage_inspection(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)

            # 1. Test live call on page
            res = await self.cdp.get_cache_storage()
            self.assertIn("caches", res)
            self.assertIn("total_caches", res)

            # 2. Test get_storage(storage_type="cache")
            storage_res = await self.cdp.get_storage(storage_type="cache")
            self.assertIn("caches", storage_res)

            # 3. Test structured CDP parsing with simulated cache entries
            async def fake_send(method, params=None, **kwargs):
                if method == "CacheStorage.requestCacheNames":
                    return {
                        "caches": [
                            {
                                "cacheId": "test-origin|api-v1",
                                "cacheName": "api-v1",
                                "securityOrigin": "https://example.com",
                            }
                        ]
                    }
                elif method == "CacheStorage.requestEntries":
                    return {
                        "cacheDataEntries": [
                            {
                                "requestURL": "https://example.com/api/data",
                                "requestMethod": "GET",
                                "responseStatus": 200,
                                "responseStatusText": "OK",
                                "responseType": "basic",
                                "responseHeaders": [
                                    {"name": "Content-Type", "value": "application/json"}
                                ],
                            }
                        ]
                    }
                elif method == "CacheStorage.requestCachedResponse":
                    import base64

                    b64 = base64.b64encode(b'{"mocked": true}').decode()
                    return {"response": {"body": b64}}
                return await self.cdp._original_send(
                    method, params=params, **kwargs
                )

            self.cdp._original_send = self.cdp.send
            with patch.object(self.cdp, "send", side_effect=fake_send):
                with patch.object(
                    self.cdp,
                    "evaluate",
                    new=AsyncMock(return_value="https://example.com"),
                ):
                    cache_data = await self.cdp.get_cache_storage(
                        include_response_body=True
                    )
                    self.assertEqual(cache_data["total_caches"], 1)
                    c = cache_data["caches"][0]
                    self.assertEqual(c["cacheName"], "api-v1")
                    self.assertEqual(c["entries_count"], 1)
                    entry = c["entries"][0]
                    self.assertEqual(
                        entry["requestURL"], "https://example.com/api/data"
                    )
                    self.assertEqual(entry["responseBody"], '{"mocked": true}')

            await self.cdp.close()

        asyncio.run(run())

    # --- Batch Integration of New Actions ---

    def test_batch_execution_new_actions(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            batch = BatchRunner(self.cdp)

            html = """
            <!DOCTYPE html>
            <html>
            <body>
                <button id="batch-test-btn">Batch Test</button>
                <script>
                    const btn = document.getElementById("batch-test-btn");
                    btn.addEventListener("click", () => console.log("batch click"));
                </script>
            </body>
            </html>
            """
            await self.cdp.navigate(f"data:text/html,{html}")
            await asyncio.sleep(0.3)

            steps = [
                {"action": "start_coverage"},
                {"action": "get_event_listeners", "selector": "#batch-test-btn"},
                {"action": "click", "selector": "#batch-test-btn"},
                {"action": "stop_coverage"},
                {"action": "get_cache_storage"},
            ]

            batch_res = await batch.execute(steps)
            self.assertTrue(batch_res["success"], f"Batch failed: {batch_res}")
            self.assertEqual(batch_res["steps_executed"], 5)

            # Check step results
            res_list = batch_res["results"]
            # Step 2: get_event_listeners
            listeners_res = res_list[1].get("event_listeners", {})
            self.assertEqual(listeners_res.get("status"), "success")
            self.assertGreaterEqual(listeners_res.get("listeners_count", 0), 1)

            # Step 4: stop_coverage
            cov_res = res_list[3].get("coverage", {})
            self.assertEqual(cov_res.get("status"), "stopped")

            # Step 5: get_cache_storage
            cache_res = res_list[4].get("cache_storage", {})
            self.assertIn("caches", cache_res)

            await self.cdp.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
