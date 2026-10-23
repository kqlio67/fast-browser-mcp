import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fast_browser.batch import BatchRunner
from fast_browser.server import TOOL_REGISTRY, TOOLS, MCPServer


class TestServerRegistryAndSchemas(unittest.TestCase):
    """Test the integrity and schema validation of tool definitions and handler registry."""

    def test_tool_count_and_exact_match(self):
        self.assertEqual(
            len(TOOLS), 75, "Expected exactly 75 registered tools in TOOLS"
        )
        self.assertEqual(
            len(TOOL_REGISTRY),
            75,
            "Expected exactly 75 registered handlers in TOOL_REGISTRY",
        )
        tools_names = {t["name"] for t in TOOLS}
        registry_names = set(TOOL_REGISTRY.keys())
        self.assertEqual(
            tools_names, registry_names, f"Difference: {tools_names ^ registry_names}"
        )

    def test_tool_schemas(self):
        for tool_def in TOOLS:
            self.assertIn("name", tool_def)
            self.assertIn("description", tool_def)
            self.assertTrue(len(tool_def["description"]) > 5)
            self.assertIn("inputSchema", tool_def)
            schema = tool_def["inputSchema"]
            self.assertEqual(schema.get("type"), "object")
            self.assertIn("properties", schema)

    def test_connection_requirements(self):
        # Tabs management and lifecycle tools should not require existing CDP active connection
        no_conn_tools = {
            "browser_list_tabs",
            "browser_select_tab",
            "browser_new_tab",
            "browser_close_tab",
            "browser_connect",
            "browser_launch",
            "browser_close_browser",
        }
        for name in no_conn_tools:
            handler_info = TOOL_REGISTRY[name]
            self.assertFalse(
                handler_info.requires_connection,
                f"{name} should not require connection",
            )

        # Interactive tools should require connection
        conn_tools = {
            "browser_snapshot",
            "browser_batch",
            "browser_click",
            "browser_eval",
        }
        for name in conn_tools:
            handler_info = TOOL_REGISTRY[name]
            self.assertTrue(
                handler_info.requires_connection, f"{name} should require connection"
            )


class TestServerPathSandboxing(unittest.TestCase):
    """Test path sandboxing and security validations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.allowed_dir = os.path.join(self.temp_dir, "sandbox")
        os.makedirs(self.allowed_dir, exist_ok=True)
        self.server = MCPServer(allowed_dir=self.allowed_dir)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_inside_sandbox_allowed(self):
        inside_path = os.path.join(self.allowed_dir, "test.png")
        resolved = self.server.validate_path(inside_path, for_write=True)
        self.assertEqual(resolved, os.path.abspath(inside_path))

    def test_path_outside_sandbox_denied(self):
        outside_path = os.path.join(self.temp_dir, "evil.png")
        with self.assertRaises(PermissionError):
            self.server.validate_path(outside_path, for_write=True)

    def test_path_traversal_denied(self):
        traversal_path = os.path.join(self.allowed_dir, "..", "secret.txt")
        with self.assertRaises(PermissionError):
            self.server.validate_path(traversal_path, for_write=True)

    def test_invalid_path_types(self):
        with self.assertRaises(ValueError):
            self.server.validate_path("")
        with self.assertRaises(ValueError):
            self.server.validate_path(None)  # type: ignore

    def test_must_exist_flag(self):
        non_existent = os.path.join(self.allowed_dir, "does_not_exist.txt")
        with self.assertRaises(FileNotFoundError):
            self.server.validate_path(non_existent, must_exist=True)

        existing = os.path.join(self.allowed_dir, "exists.txt")
        with open(existing, "w") as f:
            f.write("hello")
        resolved = self.server.validate_path(existing, must_exist=True)
        self.assertEqual(resolved, os.path.abspath(existing))

    def test_batch_runner_inherits_sandboxing(self):
        batch = BatchRunner(self.server.cdp, allowed_dir=self.allowed_dir)
        inside_path = os.path.join(self.allowed_dir, "batch_out.txt")
        self.assertEqual(batch.validate_path(inside_path), os.path.abspath(inside_path))

        outside_path = "/tmp/escape.txt"
        with self.assertRaises(PermissionError):
            batch.validate_path(outside_path)


class TestServerStdioTransport(unittest.IsolatedAsyncioTestCase):
    """Test MCP stdio transport parsing: NDJSON and Content-Length framed messages."""

    async def test_read_message_ndjson(self):
        server = MCPServer()
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n')
        reader.feed_eof()

        msg = await server._read_message(reader)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["method"], "ping")
        self.assertEqual(msg["id"], 1)
        self.assertFalse(server._client_used_headers)

    async def test_read_message_content_length_framing(self):
        server = MCPServer()
        reader = asyncio.StreamReader()
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 42, "method": "initialize"}
        ).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode()
        reader.feed_data(header + payload)
        reader.feed_eof()

        msg = await server._read_message(reader)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["method"], "initialize")
        self.assertEqual(msg["id"], 42)
        self.assertTrue(server._client_used_headers)

    async def test_read_message_malformed_json_recovery(self):
        server = MCPServer()
        reader = asyncio.StreamReader()
        reader.feed_data(b"MALFORMED JSON LINE\n")
        reader.feed_data(b'{"jsonrpc": "2.0", "id": 2, "method": "ping"}\n')
        reader.feed_eof()

        msg = await server._read_message(reader)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["method"], "ping")

    async def test_send_response_adaptive_framing(self):
        server = MCPServer()

        # In default NDJSON mode:
        server._client_used_headers = False
        with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
            server._send_response({"id": 1, "result": "ok"})
            mock_write.assert_called_once_with('{"id": 1, "result": "ok"}\n')

        # In Content-Length framed mode:
        server._client_used_headers = True
        with patch("sys.stdout.write") as mock_write, patch("sys.stdout.flush"):
            resp = {"id": 1, "result": "ok"}
            body = json.dumps(resp, ensure_ascii=False)
            expected_header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
            server._send_response(resp)
            mock_write.assert_called_once_with(expected_header + body)


class TestServerMockToolDispatch(unittest.IsolatedAsyncioTestCase):
    """Test tool dispatch in handle_call with mocked CDPClient."""

    async def asyncSetUp(self):
        self.server = MCPServer()
        self.server.cdp = MagicMock()
        self.server.cdp.is_connected = True
        self.server.cdp.connect = AsyncMock()
        self.server.batch = MagicMock()

    async def test_handle_call_unknown_tool(self):
        with self.assertRaises(ValueError) as ctx:
            await self.server.handle_call("unknown_tool_xyz", {})
        self.assertIn("Unknown tool", str(ctx.exception))

    async def test_handle_call_list_tabs(self):
        self.server.cdp.list_targets_async = AsyncMock(
            return_value=[
                {
                    "id": "t1",
                    "title": "Tab One",
                    "url": "https://example.com",
                    "type": "page",
                },
                {
                    "id": "bg1",
                    "title": "ServiceWorker",
                    "url": "chrome-extension://xyz",
                    "type": "service_worker",
                },
            ]
        )
        res_str = await self.server.handle_call("browser_list_tabs", {})
        res = json.loads(res_str)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], "t1")
        self.assertEqual(res[0]["title"], "Tab One")

    async def test_handle_call_navigate(self):
        self.server.cdp.navigate = AsyncMock(return_value={"status": "ok"})
        res = await self.server.handle_call(
            "browser_navigate", {"url": "https://anthropic.com"}
        )
        self.assertIn("Navigated to https://anthropic.com", res)
        self.server.cdp.navigate.assert_awaited_once_with("https://anthropic.com")

    async def test_handle_call_eval(self):
        self.server.cdp.evaluate = AsyncMock(return_value={"value": 42})
        res_str = await self.server.handle_call("browser_eval", {"script": "21 + 21"})
        res = json.loads(res_str)
        self.assertEqual(res["value"], 42)
        self.server.cdp.evaluate.assert_awaited_once_with("21 + 21")

    async def test_handle_call_dialog(self):
        self.server.cdp.handle_dialog = AsyncMock(
            return_value={"status": "dialog_handled", "action": "accept"}
        )
        res_str = await self.server.handle_call(
            "browser_handle_dialog", {"action": "accept", "prompt_text": "hello"}
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "dialog_handled")
        self.server.cdp.handle_dialog.assert_awaited_once_with(
            action="accept", prompt_text="hello"
        )

    async def test_handle_call_screencast(self):
        self.server.cdp.start_screencast = AsyncMock()
        self.server.cdp.stop_screencast = AsyncMock()
        # Mock validate_path to just return the passed path for testing
        self.server.validate_path = MagicMock(return_value="/tmp/out.mp4")

        await self.server.handle_call(
            "browser_screencast_start", {"file_path": "/tmp/out.mp4"}
        )
        self.server.cdp.start_screencast.assert_awaited_once_with("/tmp/out.mp4")

        await self.server.handle_call("browser_screencast_stop", {})
        self.server.cdp.stop_screencast.assert_awaited_once()

    async def test_handle_call_webmcp(self):
        self.server.cdp.evaluate = AsyncMock(return_value={"tools": ["test_tool"]})
        res_str = await self.server.handle_call("browser_list_webmcp_tools", {})
        res = json.loads(res_str)
        self.assertEqual(res["tools"], ["test_tool"])

        self.server.cdp.evaluate = AsyncMock(return_value={"result": "ok"})
        res_str = await self.server.handle_call(
            "browser_execute_webmcp_tool", {"name": "test_tool", "arguments": {"a": 1}}
        )
        res = json.loads(res_str)
        self.assertEqual(res["result"], "ok")

    async def test_handle_call_batch(self):
        self.server.batch.execute = AsyncMock(
            return_value={"success": True, "steps_executed": 1, "results": []}
        )
        # Test with 'steps'
        res_str = await self.server.handle_call(
            "browser_batch", {"steps": [{"action": "eval", "expression": "1+1"}]}
        )
        res = json.loads(res_str)
        self.assertTrue(res["success"])
        self.server.batch.execute.assert_awaited_with(
            [{"action": "eval", "expression": "1+1"}]
        )

        # Test with 'actions' alias
        res_str2 = await self.server.handle_call(
            "browser_batch", {"actions": [{"action": "click", "selector": "#btn"}]}
        )
        res2 = json.loads(res_str2)
        self.assertTrue(res2["success"])
        self.server.batch.execute.assert_awaited_with(
            [{"action": "click", "selector": "#btn"}]
        )

    async def test_handle_call_connect(self):
        self.server.cdp.switch_connection = AsyncMock(
            return_value={"status": "connected", "port": 43275}
        )
        res_str = await self.server.handle_call("browser_connect", {"port": 43275})
        res = json.loads(res_str)
        self.assertEqual(res["status"], "connected")
        self.assertEqual(self.server.port, 43275)

    async def test_handle_call_session(self):
        self.server.cdp.export_session = AsyncMock(
            return_value={"cookies": [], "localStorage": {"k": "v"}, "sessionStorage": {}}
        )
        self.server.cdp.import_session = AsyncMock(return_value={"status": "imported"})

        res_str = await self.server.handle_call("browser_export_session", {})
        res = json.loads(res_str)
        self.assertIn("localStorage", res)

        res_str = await self.server.handle_call(
            "browser_import_session", {"session_data": res}
        )
        res = json.loads(res_str)
        self.assertEqual(res["status"], "imported")

    async def test_screenshot_multimodal(self):
        # When save_path is omitted, server should return multimodal _mcp_content with image
        self.server.batch.execute = AsyncMock(
            return_value={
                "success": True,
                "results": [
                    {
                        "action": "screenshot",
                        "status": "ok",
                        "data_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    }
                ],
            }
        )
        res = await self.server.handle_call("browser_screenshot", {})
        self.assertIsInstance(res, dict)
        self.assertIn("_mcp_content", res)
        types = [c["type"] for c in res["_mcp_content"]]
        self.assertIn("text", types)
        self.assertIn("image", types)

    async def test_resources_and_prompts(self):
        self.server.cdp.list_targets_async = AsyncMock(
            return_value=[{"id": "t1", "type": "page", "title": "Test", "url": "http://test"}]
        )
        tabs_res = await self.server.handle_resource_read("browser://tabs")
        self.assertEqual(tabs_res["mimeType"], "application/json")
        self.assertIn("Test", tabs_res["text"])

        # Test browser://active/snapshot returns string formatted text
        self.server.snapshot.capture_formatted = AsyncMock(return_value="=== Page: Test ===\n@1 [button] 'Click'")
        snap_res = await self.server.handle_resource_read("browser://active/snapshot")
        self.assertEqual(snap_res["mimeType"], "text/plain")
        self.assertIsInstance(snap_res["text"], str)
        self.assertIn("@1 [button]", snap_res["text"])

        # Test browser://active/dom returns HTML
        self.server.cdp.get_html = AsyncMock(return_value="<html><body>Hello</body></html>")
        dom_res = await self.server.handle_resource_read("browser://active/dom")
        self.assertEqual(dom_res["mimeType"], "text/html")
        self.assertEqual(dom_res["text"], "<html><body>Hello</body></html>")

        # Test browser://console
        self.server.cdp.console.list_logs = MagicMock(return_value=[{"message": "log1"}])
        console_res = await self.server.handle_resource_read("browser://console")
        self.assertEqual(console_res["mimeType"], "application/json")
        self.assertIn("log1", console_res["text"])

        # Test browser://network
        self.server.cdp.network.list_requests = MagicMock(return_value=[{"id": "req1"}])
        net_res = await self.server.handle_resource_read("browser://network")
        self.assertEqual(net_res["mimeType"], "application/json")
        self.assertIn("req1", net_res["text"])

        # Test unknown resource URI raises ValueError
        with self.assertRaises(ValueError):
            await self.server.handle_resource_read("browser://unknown_xyz")

        # Test prompts
        p1 = self.server.handle_prompt_get("web-research", {"query": "AI"})
        self.assertIn("messages", p1)
        self.assertIn("AI", p1["messages"][0]["content"]["text"])

        p2 = self.server.handle_prompt_get("form-automation", {"url": "https://example.com"})
        self.assertIn("messages", p2)
        self.assertIn("https://example.com", p2["messages"][0]["content"]["text"])

        p3 = self.server.handle_prompt_get("network-debugger", {"url": "https://api.com"})
        self.assertIn("messages", p3)
        self.assertIn("https://api.com", p3["messages"][0]["content"]["text"])

        # Test unknown prompt raises ValueError
        with self.assertRaises(ValueError):
            self.server.handle_prompt_get("unknown_prompt_xyz", {})


if __name__ == "__main__":
    unittest.main()
