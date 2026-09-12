import unittest
import asyncio
from fast_browser.cdp import CDPClient
from fast_browser.snapshot import PageSnapshot
from fast_browser.batch import BatchRunner

class TestBrowserManagement(unittest.TestCase):
    def setUp(self):
        self.cdp = CDPClient()

    def test_browser_version(self):
        ver = self.cdp.get_browser_version()
        self.assertIn("Browser", ver)
        self.assertIn("Protocol-Version", ver)

    def test_window_bounds(self):
        async def run():
            bounds = await self.cdp.get_window_bounds()
            self.assertIn("windowId", bounds)
            self.assertIn("bounds", bounds)
            b = bounds["bounds"]
            self.assertIn("windowState", b)
            self.assertIn("width", b)
            self.assertIn("height", b)
        asyncio.run(run())

    def test_list_extensions(self):
        async def run():
            exts = await self.cdp.list_extensions()
            self.assertIsInstance(exts, list)
            if exts:
                self.assertIn("id", exts[0])
                self.assertIn("name", exts[0])
                self.assertIn("enabled", exts[0])
        asyncio.run(run())

    def test_system_page_and_snapshot(self):
        async def run():
            tab_res = await self.cdp.open_system_page("extensions")
            tab = tab_res.get("target")
            tid = tab.get("id")
            try:
                snap = PageSnapshot(self.cdp)
                res = await snap.capture()
                self.assertGreater(res.get("count", 0), 0)
            finally:
                if tab_res.get("status") == "opened" and tid:
                    await self.cdp.close_tab(tid)
        asyncio.run(run())

    def test_batch_browser_management(self):
        async def run():
            await self.cdp.connect()
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "system_info"},
                {"action": "window"}
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 2)
            self.assertIn("browser_version", res["results"][0])
            self.assertIn("window", res["results"][1])
            await self.cdp.close()
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
