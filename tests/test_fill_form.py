import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from fast_browser.server import MCPServer


class TestBrowserFillForm(unittest.IsolatedAsyncioTestCase):
    async def test_handle_fill_form(self):
        server = MCPServer()
        server.cdp = MagicMock()
        server.cdp.is_connected = True
        server.batch = MagicMock()
        server.batch.execute = AsyncMock(
            return_value={"status": "batch_completed", "results": []}
        )

        res_str = await server.handle_call(
            "browser_fill_form",
            {
                "elements": [
                    {"ref": "@1", "text": "test1"},
                    {"selector": "#id", "text": "test2", "clear": False},
                ]
            },
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "batch_completed")
        server.batch.execute.assert_awaited_once()
        steps = server.batch.execute.call_args[0][0]
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["action"], "fill")
        self.assertEqual(steps[0]["ref"], "@1")
        self.assertEqual(steps[0]["text"], "test1")
        self.assertEqual(steps[0]["clear"], True)

        self.assertEqual(steps[1]["action"], "fill")
        self.assertEqual(steps[1]["selector"], "#id")
        self.assertEqual(steps[1]["text"], "test2")
        self.assertEqual(steps[1]["clear"], False)


if __name__ == "__main__":
    unittest.main()
