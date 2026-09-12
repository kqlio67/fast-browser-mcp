import unittest
import asyncio
from fast_browser.cdp import CDPClient
from fast_browser.batch import BatchRunner

class TestV6Superpowers(unittest.TestCase):
    def setUp(self):
        self.cdp = CDPClient()
        self.tab = self.cdp.new_tab_sync("about:blank")
        self.tab_id = self.tab["id"]

    def tearDown(self):
        try:
            self.cdp.close_tab_sync(self.tab_id)
        except Exception:
            pass

    def test_navigation_history(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            hist = await self.cdp.get_navigation_history()
            self.assertIn("current_index", hist)
            self.assertIn("entries", hist)
            await self.cdp.close()
        asyncio.run(run())

    def test_stealth_mode(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.set_stealth_mode(enabled=True)
            self.assertTrue(res.get("stealth"))
            val = await self.cdp.evaluate("navigator.webdriver")
            self.assertIsNone(val)
            await self.cdp.close()
        asyncio.run(run())

    def test_network_throttling(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.set_network_throttling(profile="fast3g")
            self.assertEqual(res.get("profile"), "fast3g")
            # Reset
            await self.cdp.set_network_throttling(profile="none")
            await self.cdp.close()
        asyncio.run(run())

    def test_media_theme_and_zoom(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            theme_res = await self.cdp.set_media_theme(theme="dark")
            self.assertEqual(theme_res.get("theme"), "dark")

            zoom_res = await self.cdp.set_page_zoom(scale=1.25)
            self.assertEqual(zoom_res.get("scale"), 1.25)
            await self.cdp.set_page_zoom(scale=1.0)
            await self.cdp.close()
        asyncio.run(run())

    def test_audio_muted(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.set_audio_muted(muted=True)
            self.assertTrue(res.get("muted"))
            await self.cdp.set_audio_muted(muted=False)
            await self.cdp.close()
        asyncio.run(run())

    def test_clipboard(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            ok = await self.cdp.set_clipboard_text("fast-browser-mcp-test")
            self.assertIsInstance(ok, bool)
            text = await self.cdp.get_clipboard_text()
            self.assertIsInstance(text, str)
            await self.cdp.close()
        asyncio.run(run())

    def test_find_in_page(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            # inject known text to body
            await self.cdp.evaluate("(() => { const p = document.createElement('p'); p.id = '__test_find_p'; p.textContent = 'UniqueSuperSearchToken42'; document.body.appendChild(p); })()")
            res = await self.cdp.find_in_page(query="UniqueSuperSearchToken42")
            self.assertTrue(res.get("found"))
            self.assertGreater(res.get("count", 0), 0)
            # cleanup
            await self.cdp.evaluate("(() => { const el = document.getElementById('__test_find_p'); if (el) el.remove(); })()")
            await self.cdp.close()
        asyncio.run(run())

    def test_indexeddb_data(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.get_indexeddb_data()
            self.assertIn("supported", res)
            self.assertIn("databases", res)
            await self.cdp.close()
        asyncio.run(run())

    def test_batch_v6_actions(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "stealth", "enabled": True},
                {"action": "theme", "theme": "dark"},
                {"action": "zoom", "scale": 1.0},
                {"action": "history"}
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 4)
            await self.cdp.close()
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
