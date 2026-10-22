import asyncio
import unittest

from fast_browser.batch import BatchRunner
from fast_browser.snapshot import PageSnapshot

try:
    from .base import BaseBrowserTest
except ImportError:
    from base import BaseBrowserTest


class TestFastBrowser(BaseBrowserTest):
    def test_list_targets(self):
        targets = self.cdp.list_targets()
        self.assertIsInstance(targets, list)
        self.assertGreater(
            len(targets), 0, "Should find running browser targets on port 9222"
        )

    def test_snapshot_and_eval(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            title = await self.cdp.evaluate("document.title")
            self.assertIsInstance(title, str)

            snap = PageSnapshot(self.cdp)
            text = await snap.capture_formatted()
            self.assertIn("Page:", text)
            await self.cdp.close()

        asyncio.run(run())


    def test_batch_execution(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            batch = BatchRunner(self.cdp)
            steps = [
                {"action": "eval", "script": "1 + 1"},
                {"action": "scroll", "delta_y": 50},
                {"action": "wait", "ms": 20},
            ]
            res = await batch.execute(steps)
            self.assertTrue(res["success"])
            self.assertEqual(res["steps_executed"], 3)
            self.assertEqual(res["results"][0]["result"], 2)
            await self.cdp.close()

        asyncio.run(run())



    def test_contenteditable_fill_and_dismiss_banners(self):
        async def run():
            await self.cdp.connect(target_id=self.tab_id)
            # Create a contenteditable div
            await self.cdp.evaluate(
                """(() => {
                document.body.innerHTML = `
                    <div id="editor" contenteditable="true" role="textbox">Initial</div>
                `;
                let entered = false;
                document.getElementById('editor').addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') entered = true;
                });
                window.__entered = () => entered;
            })()"""
            )
            # Use cdp.fill on contenteditable with press_enter=True
            await self.cdp.fill(
                "#editor", "Updated Content", clear=True, press_enter=True
            )
            text = await self.cdp.evaluate(
                "document.getElementById('editor').innerText"
            )
            self.assertIn("Updated Content", text)
            entered = await self.cdp.evaluate("window.__entered()")
            self.assertTrue(entered)

            # Test batch action dismiss_banners
            await self.cdp.evaluate(
                """(() => {
                const dlg = document.createElement('dialog');
                dlg.setAttribute('open', '');
                const btn = document.createElement('button');
                btn.textContent = 'Accept All';
                btn.onclick = () => dlg.remove();
                dlg.appendChild(btn);
                document.body.appendChild(dlg);
            })()"""
            )
            batch = BatchRunner(self.cdp)
            res = await batch.execute([{"action": "dismiss_banners"}])
            self.assertTrue(res["success"])
            # verify dialog was removed
            exists = await self.cdp.evaluate(
                "Boolean(document.querySelector('dialog'))"
            )
            self.assertFalse(exists)

            await self.cdp.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
