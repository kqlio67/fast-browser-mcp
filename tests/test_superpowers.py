import asyncio
import json
import unittest

from fast_browser.batch import BatchRunner

try:
    from .base import BaseBrowserTest
except ImportError:
    from base import BaseBrowserTest


class TestSuperpowers(BaseBrowserTest):
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
            await self.cdp.evaluate(
                "(() => { const p = document.createElement('p'); p.id = '__test_find_p'; p.textContent = 'UniqueSuperSearchToken42'; document.body.appendChild(p); })()"
            )
            res = await self.cdp.find_in_page(query="UniqueSuperSearchToken42")
            self.assertTrue(res.get("found"))
            self.assertGreater(res.get("count", 0), 0)
            # cleanup
            await self.cdp.evaluate(
                "(() => { const el = document.getElementById('__test_find_p'); if (el) el.remove(); })()"
            )
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

    def test_batch_superpowers_actions(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "stealth", "enabled": True},
                {"action": "theme", "theme": "dark"},
                {"action": "zoom", "scale": 1.0},
                {"action": "history"},
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 4)
            await self.cdp.close()

        asyncio.run(run())

    def test_stealth_advanced_properties(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            await self.cdp.set_stealth_mode(enabled=True)
            plugin_count = await self.cdp.evaluate("navigator.plugins.length")
            self.assertEqual(plugin_count, 5)
            has_csi = await self.cdp.evaluate("typeof window.chrome.csi === 'function'")
            self.assertTrue(has_csi)
            await self.cdp.close()

        asyncio.run(run())

    def test_batch_paste_and_trusted_click(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            html = """
            <input id="input-box" type="text" />
            <button id="click-btn" onclick="this.textContent='Clicked!'">Click Me</button>
            """
            await self.cdp.evaluate(f"document.body.innerHTML = {json.dumps(html)}")
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "paste", "selector": "#input-box", "text": "PastedFast"},
                {"action": "click", "selector": "#click-btn", "trusted": True},
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            val = await self.cdp.evaluate("document.querySelector('#input-box').value")
            self.assertEqual(val, "PastedFast")
            btn_txt = await self.cdp.evaluate("document.querySelector('#click-btn').textContent")
            self.assertEqual(btn_txt, "Clicked!")

            # Verify get_css_styles includes rect and eventListeners
            styles = await self.cdp.get_css_styles(selector="#click-btn")
            self.assertIn("rect", styles)
            self.assertIn("eventListeners", styles)
            self.assertTrue(any(ev.get("event") == "click" for ev in styles["eventListeners"]))
            await self.cdp.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
