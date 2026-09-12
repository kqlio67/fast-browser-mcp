import unittest
import asyncio
from fast_browser.cdp import CDPClient
from fast_browser.snapshot import PageSnapshot
from fast_browser.batch import BatchRunner

class TestFastBrowser(unittest.TestCase):
    def setUp(self):
        self.cdp = CDPClient()

    def test_list_targets(self):
        targets = self.cdp.list_targets()
        self.assertIsInstance(targets, list)
        self.assertGreater(len(targets), 0, "Should find running browser targets on port 9222")

    def test_snapshot_and_eval(self):
        async def run():
            await self.cdp.connect()
            title = await self.cdp.evaluate("document.title")
            self.assertIsInstance(title, str)
            
            snap = PageSnapshot(self.cdp)
            text = await snap.capture_formatted()
            self.assertIn("Page:", text)
            await self.cdp.close()

        asyncio.run(run())

    def test_batch_execution(self):
        async def run():
            await self.cdp.connect()
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "eval", "script": "1 + 1"},
                {"action": "scroll", "delta_y": 50},
                {"action": "wait", "ms": 20}
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 3)
            self.assertEqual(res["results"][0]["result"], 2)
            await self.cdp.close()

        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
