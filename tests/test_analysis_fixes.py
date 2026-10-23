import asyncio
import subprocess
import unittest
from unittest.mock import AsyncMock, MagicMock

import fast_browser
from fast_browser.batch import BatchRunner
from fast_browser.cdp import CDPClient
from fast_browser.launcher import BrowserProcess, _active_browsers
from fast_browser.network import NetworkMonitor
from fast_browser.snapshot import SNAPSHOT_JS


class TestAnalysisFixes(unittest.TestCase):
    def test_version_match(self):
        """Ensure __version__ in __init__.py matches 0.11.0."""
        self.assertEqual(fast_browser.__version__, "0.11.0")

    def test_network_monitor_none_url(self):
        """Ensure list_requests with url_pattern does not crash when request url is None."""
        monitor = NetworkMonitor()
        monitor.requests["req_none"] = {
            "id": "req_none",
            "url": None,
            "method": "GET",
            "headers": {},
            "postData": None,
            "type": "Other",
            "timestamp": "12:00:00",
            "status": None,
            "statusText": None,
            "responseHeaders": {},
            "mimeType": None,
        }
        monitor.ordered_requests.append("req_none")

        # Filtering by url_pattern must not throw AttributeError on None.lower()
        res = monitor.list_requests(url_pattern="example")
        self.assertEqual(len(res), 0)

        res2 = monitor.list_requests(url_pattern=None)
        self.assertEqual(len(res2), 1)

    def test_snapshot_regex_collapses_whitespace(self):
        """Ensure SNAPSHOT_JS has proper regex for whitespace collapsing."""
        self.assertIn(r"replace(/\s+/g, ' ')", SNAPSHOT_JS)
        self.assertNotIn(r"replace(/\\s+/g, ' ')", SNAPSHOT_JS)

    def test_browser_process_terminate_cleanup(self):
        """Ensure BrowserProcess.terminate removes instance from _active_browsers and reaps."""
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None

        bp = BrowserProcess(
            proc=mock_proc,
            port=9999,
            user_data_dir="/tmp/test_profile_dir_fake",
            is_temp_dir=False,
        )
        _active_browsers.append(bp)
        self.assertIn(bp, _active_browsers)

        bp.terminate()
        self.assertNotIn(bp, _active_browsers)
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called()

    def test_batch_validate_ref_format(self):
        """Ensure validate_step rejects invalid ref formats."""
        err1 = BatchRunner.validate_step({"action": "click", "ref": "@1"}, 0)
        self.assertIsNone(err1)

        err2 = BatchRunner.validate_step({"action": "click", "ref": "invalid_ref"}, 0)
        self.assertIsNotNone(err2)
        self.assertIn("invalid ref", err2 or "")

    def test_batch_wait_aliases(self):
        """Ensure wait action handles 'seconds' and 'duration' parameters."""
        cdp = MagicMock(spec=CDPClient)
        runner = BatchRunner(cdp)

        async def run():
            # Wait with seconds
            t0 = asyncio.get_running_loop().time()
            res = await runner.execute([{"action": "wait", "seconds": 0.05}])
            elapsed = asyncio.get_running_loop().time() - t0
            self.assertTrue(res["success"])
            self.assertGreaterEqual(elapsed, 0.04)

            # Wait with duration (ms)
            res2 = await runner.execute([{"action": "wait", "duration": 50}])
            self.assertTrue(res2["success"])

        asyncio.run(run())

    def test_batch_click_and_hover_coordinates(self):
        """Ensure click and hover actions handle (x, y) coordinates correctly."""
        cdp = MagicMock(spec=CDPClient)
        cdp.trusted_click = AsyncMock(return_value=True)
        cdp.mouse_move = AsyncMock(return_value=True)
        runner = BatchRunner(cdp)

        async def run():
            # Click with coordinates
            res1 = await runner.execute([{"action": "click", "x": 120.5, "y": 340.0}])
            self.assertTrue(res1["success"])
            cdp.trusted_click.assert_awaited_once_with(120.5, 340.0)

            # Hover with coordinates
            res2 = await runner.execute([{"action": "hover", "x": 55.0, "y": 77.0}])
            self.assertTrue(res2["success"])
            cdp.mouse_move.assert_awaited_once_with(55.0, 77.0)

        asyncio.run(run())

    def test_batch_all_tool_aliases_execute(self):
        """Ensure all aliases mapped to actions execute without 'Unknown action' errors."""
        cdp = MagicMock(spec=CDPClient)
        cdp.get_performance_metrics = AsyncMock(return_value={"metrics": {}})
        cdp.set_download_path = AsyncMock(return_value={})
        cdp.wait_for_network_idle = AsyncMock(return_value=True)
        cdp.set_stealth_mode = AsyncMock(return_value={"stealth": True})
        cdp.find_in_page = AsyncMock(return_value={"found": True})
        cdp.get_css_styles = AsyncMock(return_value={"tag": "div"})
        cdp.print_to_pdf = AsyncMock(return_value="AQID")
        cdp.list_extensions = AsyncMock(return_value=[])
        cdp.set_audio_muted = AsyncMock(return_value={"muted": True})
        cdp.set_network_throttling = AsyncMock(return_value={"profile": "fast3g"})
        cdp.open_system_page = AsyncMock(return_value={"status": "opened"})
        cdp.new_isolated_tab = AsyncMock(return_value={"isolated": True})
        cdp.add_preload_script = AsyncMock(return_value="id1")
        cdp.remove_preload_script = AsyncMock(return_value=True)
        cdp.network = MagicMock()
        cdp.network.list_ws_frames = MagicMock(return_value=[])
        cdp.network.get_request_details = MagicMock(return_value={})
        cdp.get_response_body = AsyncMock(return_value={"body": ""})
        cdp.wait_for_download = AsyncMock(return_value={"status": "completed"})
        cdp.set_ignore_certificate_errors = AsyncMock(return_value={"ignore": True})
        cdp.set_media_theme = AsyncMock(return_value={"theme": "dark"})
        cdp.set_page_zoom = AsyncMock(return_value={"scale": 1.0})
        cdp.set_cpu_throttling = AsyncMock(return_value={"rate": 1.0})
        cdp.get_indexeddb_data = AsyncMock(return_value={"databases": []})
        cdp.clear_cache = AsyncMock(return_value=True)
        cdp.clear_cookies = AsyncMock(return_value=True)
        cdp.set_geolocation = AsyncMock(return_value={"success": True})
        cdp.set_timezone = AsyncMock(return_value={"success": True})
        cdp.get_cookies = AsyncMock(return_value=[])
        cdp.evaluate = AsyncMock(return_value="ok")

        runner = BatchRunner(cdp)
        runner.validate_path = MagicMock(return_value="/tmp/test_file")

        steps = [
            {"action": "performance_metrics"},
            {"action": "download_path", "path": "/tmp/downloads"},
            {"action": "wait_for_network_idle"},
            {"action": "stealth_mode"},
            {"action": "find_in_page", "query": "hello"},
            {"action": "get_css_styles", "selector": "#header"},
            {"action": "list_extensions"},
            {"action": "mute_tab"},
            {"action": "network_throttling"},
            {"action": "open_system_page", "page": "settings"},
            {"action": "new_isolated_tab"},
            {"action": "add_preload_script", "source": "console.log(1)"},
            {"action": "remove_preload_script", "identifier": "id1"},
            {"action": "websocket_messages"},
            {"action": "wait_for_download", "directory": "/tmp/downloads"},
            {"action": "set_ignore_certificate_errors"},
            {"action": "set_media_theme"},
            {"action": "set_page_zoom"},
            {"action": "set_cpu_throttling"},
            {"action": "get_indexeddb"},
            {"action": "clear_storage"},
            {"action": "emulate_environment", "latitude": 10.0, "longitude": 20.0},
            {"action": "get_cookies"},
            {"action": "network_get_response", "request_id": "r1"},
            {"action": "list_webmcp_tools"},
            {"action": "execute_webmcp_tool", "name": "test_tool"},
        ]

        async def run():
            res = await runner.execute(steps)
            self.assertTrue(res["success"], f"Failed with: {res.get('error')}")
            self.assertEqual(res["steps_executed"], len(steps))

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
