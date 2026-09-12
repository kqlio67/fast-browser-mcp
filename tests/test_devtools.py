import unittest
import asyncio
from fast_browser.batch import BatchRunner
try:
    from .base import BaseBrowserTest
except ImportError:
    from base import BaseBrowserTest

class TestDevTools(BaseBrowserTest):

    def test_send_cdp_raw(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            ver = await self.cdp.send_cdp("Browser.getVersion")
            self.assertIn("product", ver)
            self.assertIn("protocolVersion", ver)
            await self.cdp.close()
        asyncio.run(run())

    def test_get_css_styles(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            await self.cdp.evaluate("""(() => {
                const d = document.createElement('div');
                d.id = 'v8-styled-element';
                d.style.color = 'rgb(255, 0, 0)';
                d.style.fontSize = '24px';
                d.textContent = 'CSS Test';
                document.body.appendChild(d);
            })()""")
            styles = await self.cdp.get_css_styles(selector="#v8-styled-element")
            self.assertEqual(styles["tag"], "div")
            self.assertEqual(styles["id"], "v8-styled-element")
            self.assertIn("computed", styles)
            self.assertIn("24px", styles["computed"].get("font-size", ""))
            await self.cdp.close()
        asyncio.run(run())

    def test_new_isolated_tab(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            iso = await self.cdp.new_isolated_tab("about:blank")
            self.assertTrue(iso.get("isolated"))
            self.assertIn("target_id", iso)
            self.assertIn("browser_context_id", iso)
            # Cleanup target
            if iso.get("target_id"):
                self.cdp.close_tab_sync(iso["target_id"])
            await self.cdp.close()
        asyncio.run(run())

    def test_cpu_throttling(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            res = await self.cdp.set_cpu_throttling(rate=2.0)
            self.assertTrue(res["throttled"])
            self.assertEqual(res["rate"], 2.0)
            # Reset
            await self.cdp.set_cpu_throttling(rate=1.0)
            await self.cdp.close()
        asyncio.run(run())

    def test_dialog_handling(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            self.cdp.set_dialog_behavior(action="accept")
            # trigger alert asynchronously
            asyncio.create_task(self.cdp.evaluate("alert('v8-dialog-test')"))
            await asyncio.sleep(0.3)
            self.assertIn("v8-dialog-test", self.cdp.last_dialog_message or "")
            await self.cdp.close()
        asyncio.run(run())

    def test_batch_v8_actions(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            await self.cdp.evaluate("""(() => {
                const el = document.createElement('span');
                el.id = 'batch-span';
                el.style.display = 'inline-block';
                el.textContent = 'batch';
                document.body.appendChild(el);
            })()""")
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "cdp_send", "method": "DOM.getDocument"},
                {"action": "css_styles", "selector": "#batch-span"},
                {"action": "cpu_throttling", "rate": 1.0}
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 3)
            self.assertIn("cdp_result", res["results"][0])
            self.assertIn("css_styles", res["results"][1])
            await self.cdp.close()
        asyncio.run(run())

if __name__ == "__main__":
    unittest.main()
