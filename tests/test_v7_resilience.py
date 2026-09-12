import unittest
import asyncio
from fast_browser.cdp import CDPClient
from fast_browser.snapshot import PageSnapshot
from fast_browser.batch import BatchRunner

class TestV7Resilience(unittest.TestCase):
    def setUp(self):
        self.cdp = CDPClient()
        self.tab = self.cdp.new_tab_sync("about:blank")
        self.tab_id = self.tab["id"]

    def tearDown(self):
        try:
            self.cdp.close_tab_sync(self.tab_id)
        except Exception:
            pass

    def test_element_stability_and_autowait(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            # Inject an element
            await self.cdp.evaluate("""(() => {
                const btn = document.createElement('button');
                btn.id = 'test-stable-btn';
                btn.textContent = 'Stable Button';
                document.body.appendChild(btn);
            })()""")
            stable = await self.cdp.wait_for_element_stable("#test-stable-btn", timeout_ms=2000)
            self.assertTrue(stable)
            # Click with wait_stable=True
            ok = await self.cdp.click("#test-stable-btn", wait_stable=True)
            self.assertTrue(ok)
            await self.cdp.close()
        asyncio.run(run())

    def test_network_idle(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            is_idle = await self.cdp.wait_for_network_idle(idle_time=0.2, timeout=3.0)
            self.assertTrue(is_idle)
            await self.cdp.close()
        asyncio.run(run())

    def test_scoped_and_viewport_snapshot(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            # Inject structured elements
            await self.cdp.evaluate("""(() => {
                const c = document.createElement('div');
                c.id = 'container-scope';
                c.innerHTML = `
                    <button id="b1">Btn 1</button>
                    <button id="b2">Btn 2</button>
                    <button id="b3">Btn 3</button>
                `;
                document.body.appendChild(c);
            })()""")
            snap = PageSnapshot(self.cdp)
            
            # 1. Scoped snapshot
            res = await snap.capture(selector="#container-scope")
            self.assertEqual(res["root"], "#container-scope")
            self.assertGreaterEqual(res["count"], 3)

            # 2. Max elements truncation
            res_trunc = await snap.capture(selector="#container-scope", max_elements=2)
            self.assertEqual(res_trunc["count"], 2)
            self.assertTrue(res_trunc["truncated"])

            # 3. Formatted snapshot
            text = await snap.capture_formatted(selector="#container-scope", in_viewport=True)
            self.assertIn("Btn 1", text)
            await self.cdp.close()
        asyncio.run(run())

    def test_resource_blocker(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.block_resources(block_images=True, block_ads=True)
            self.assertTrue(res["blocked"])
            self.assertGreater(res["count"], 0)
            self.assertTrue(any("*.png" in p for p in res["patterns"]))
            # Reset
            await self.cdp.block_resources(blocked_urls=[])
            await self.cdp.close()
        asyncio.run(run())

    def test_performance_metrics(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            metrics = await self.cdp.get_performance_metrics()
            self.assertIn("js_heap_used_mb", metrics)
            self.assertIn("dom_nodes", metrics)
            self.assertIn("layouts", metrics)
            self.assertGreaterEqual(metrics["dom_nodes"], 0)
            await self.cdp.close()
        asyncio.run(run())

    def test_geolocation_and_timezone(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            # Geolocation
            geo = await self.cdp.set_geolocation(latitude=50.4501, longitude=30.5234)
            self.assertTrue(geo["success"])
            self.assertEqual(geo["latitude"], 50.4501)

            # Timezone
            tz = await self.cdp.set_timezone("Europe/Kyiv")
            self.assertTrue(tz["success"])
            actual_tz = await self.cdp.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            self.assertIn(actual_tz, ("Europe/Kyiv", "Europe/Kiev"))
            await self.cdp.close()
        asyncio.run(run())

    def test_tab_cleanup(self):
        async def run():
            # Open extra tab
            temp_tab = self.cdp.new_tab_sync("about:blank")
            tid = temp_tab["id"]
            
            res = self.cdp.cleanup_tabs(keep_current=True, close_blank=True)
            self.assertIn("closed_count", res)
            self.assertIn("closed_tabs", res)
        asyncio.run(run())

    def test_batch_v7_actions(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "wait_idle", "idle_time": 0.1, "timeout": 2.0},
                {"action": "block_resources", "images": True, "ads": True},
                {"action": "timezone", "timezone": "Europe/Kyiv"},
                {"action": "metrics"},
                {"action": "snapshot", "in_viewport": True, "max_elements": 10}
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 5)
            self.assertIn("metrics", res["results"][3])
            self.assertIn("snapshot", res["results"][4])
            await self.cdp.close()
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
