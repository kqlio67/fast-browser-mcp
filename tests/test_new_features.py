import unittest
from unittest.mock import AsyncMock, MagicMock

from fast_browser.adblock import (
    CORE_AD_PATTERNS,
    get_adblock_patterns,
)
from fast_browser.batch import BatchRunner
from fast_browser.human_input import (
    TrajectoryPoint,
    _bezier_point,
    _ease_in_out,
    generate_human_trajectory,
)
from fast_browser.launcher import detect_backend
from fast_browser.semantic_finder import FINDER_JS


class TestHumanInput(unittest.TestCase):
    def test_ease_in_out(self):
        self.assertAlmostEqual(_ease_in_out(0.0), 0.0)
        self.assertAlmostEqual(_ease_in_out(1.0), 1.0)
        self.assertAlmostEqual(_ease_in_out(0.5), 0.5)

    def test_bezier_point(self):
        p0 = (0.0, 0.0)
        p1 = (10.0, 50.0)
        p2 = (90.0, 50.0)
        p3 = (100.0, 100.0)

        start = _bezier_point(p0, p1, p2, p3, 0.0)
        self.assertEqual(start, (0.0, 0.0))

        end = _bezier_point(p0, p1, p2, p3, 1.0)
        self.assertEqual(end, (100.0, 100.0))

        mid = _bezier_point(p0, p1, p2, p3, 0.5)
        self.assertAlmostEqual(mid[0], 50.0)
        self.assertAlmostEqual(mid[1], 50.0)

    def test_generate_human_trajectory(self):
        points = generate_human_trajectory(0, 0, 500, 400, steps=20, jitter=False)
        self.assertGreater(len(points), 10)
        # Last point should be destination (500, 400)
        self.assertEqual(points[-1].x, 500.0)
        self.assertEqual(points[-1].y, 400.0)
        self.assertIsInstance(points[0], TrajectoryPoint)

        # Close points
        close_points = generate_human_trajectory(100, 100, 100.5, 100.5)
        self.assertEqual(len(close_points), 1)


class TestAdBlock(unittest.TestCase):
    def test_get_blocked_patterns(self):
        pats_all = get_adblock_patterns(block_trackers=True)
        self.assertGreater(len(pats_all), len(CORE_AD_PATTERNS))
        self.assertTrue(any("doubleclick" in p for p in pats_all))
        self.assertTrue(any("google-analytics" in p for p in pats_all))

        pats_ads_only = get_adblock_patterns(block_trackers=False)
        self.assertEqual(len(pats_ads_only), len(CORE_AD_PATTERNS))

        custom = ["*evil-ad.com*"]
        pats_custom = get_adblock_patterns(block_trackers=False, custom_patterns=custom)
        self.assertIn("*evil-ad.com*", pats_custom)


class TestSemanticFinder(unittest.TestCase):
    def test_finder_js_structure(self):
        self.assertIn("intentQuery", FINDER_JS)
        self.assertIn("targetRole", FINDER_JS)
        self.assertIn("__fb_refs", FINDER_JS)
        self.assertIn("scored", FINDER_JS)


class TestLauncherBackendDetection(unittest.TestCase):
    def test_detect_backend_fallback(self):
        # Port 59999 should not be running, so should cleanly return 'unknown'
        backend = detect_backend(port=59999, timeout=0.2)
        self.assertEqual(backend, "unknown")


class TestBatchRunnerNewActions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cdp = MagicMock()
        self.cdp.ref_session_map = {}
        self.cdp.human_click = AsyncMock()
        self.cdp.human_move = AsyncMock()
        self.cdp.set_adblock = AsyncMock(return_value={"enabled": True, "rules_count": 80})
        self.cdp.smart_find = AsyncMock(return_value=[{"ref": "@e1", "role": "button", "score": 90}])
        self.cdp.create_browser_context = AsyncMock(return_value="ctx-999")
        self.cdp.dispose_browser_context = AsyncMock()
        self.cdp.list_browser_contexts = AsyncMock(return_value=["ctx-999"])
        self.batch = BatchRunner(self.cdp)

    async def test_human_mouse_action(self):
        step = {"action": "human_mouse", "subaction": "click", "x": 120, "y": 240, "button": "left"}
        res = await self.batch.execute([step])
        self.assertTrue(res["success"])
        self.cdp.human_click.assert_awaited_once_with(120.0, 240.0, button="left")

        step2 = {"action": "human_move", "x": 300, "y": 400, "steps": 30}
        res2 = await self.batch.execute([step2])
        self.assertTrue(res2["success"])
        self.cdp.human_move.assert_awaited_once_with(300.0, 400.0, steps=30)

    async def test_set_adblock_action(self):
        step = {"action": "set_adblock", "enabled": True, "block_trackers": True}
        res = await self.batch.execute([step])
        self.assertTrue(res["success"])
        self.cdp.set_adblock.assert_awaited_once_with(enabled=True, block_trackers=True, custom_patterns=None)

    async def test_smart_find_action(self):
        step = {"action": "smart_find", "intent": "sign in", "role": "button", "max_results": 3}
        res = await self.batch.execute([step])
        self.assertTrue(res["success"])
        self.cdp.smart_find.assert_awaited_once_with(intent="sign in", role="button", max_results=3)

    async def test_context_pool_actions(self):
        # create
        res_create = await self.batch.execute([{"action": "create_context"}])
        self.assertTrue(res_create["success"])
        self.assertEqual(res_create["results"][0]["browser_context_id"], "ctx-999")

        # list
        res_list = await self.batch.execute([{"action": "list_contexts"}])
        self.assertTrue(res_list["success"])
        self.assertEqual(res_list["results"][0]["browser_contexts"], ["ctx-999"])

        # dispose
        res_dispose = await self.batch.execute([{"action": "dispose_context", "browser_context_id": "ctx-999"}])
        self.assertTrue(res_dispose["success"])
        self.cdp.dispose_browser_context.assert_awaited_once_with("ctx-999")

    async def test_universal_new_actions(self):
        self.cdp.get_page_state = AsyncMock(return_value={"seq": 10, "url": "https://example.com", "backend": "chrome"})
        self.cdp.set_control_value = AsyncMock(return_value={"status": "ok", "value": "test-val"})
        self.cdp.mark_paint_damage = AsyncMock(return_value={"status": "ok"})
        self.cdp.get_paint_damage_since = AsyncMock(return_value={"status": "ok", "damaged_count": 1})
        self.cdp.set_turbo_mode = AsyncMock(return_value={"status": "ok", "turbo": True})

        # page_state
        res1 = await self.batch.execute([{"action": "get_page_state"}])
        self.assertTrue(res1["success"])
        self.assertEqual(res1["results"][0]["page_state"]["seq"], 10)

        # set_control_value
        res2 = await self.batch.execute([{"action": "set_control_value", "value": "test-val", "selector": "#input"}])
        self.assertTrue(res2["success"])
        self.cdp.set_control_value.assert_awaited_once_with(value="test-val", ref=None, selector="#input", node_id=None)

        # paint_damage mark & get
        res3 = await self.batch.execute([{"action": "mark_paint_damage"}])
        self.assertTrue(res3["success"])
        self.cdp.mark_paint_damage.assert_awaited_once()

        res4 = await self.batch.execute([{"action": "get_paint_damage"}])
        self.assertTrue(res4["success"])
        self.cdp.get_paint_damage_since.assert_awaited_once_with(exclude_ref=None, exclude_selector=None)

        # turbo_mode
        res5 = await self.batch.execute([{"action": "turbo_mode", "enabled": True}])
        self.assertTrue(res5["success"])
        self.cdp.set_turbo_mode.assert_awaited_once_with(enabled=True)

        # activate_tab
        self.cdp.activate_tab = AsyncMock(return_value=True)
        res6 = await self.batch.execute([{"action": "activate_tab", "target_id": "t1"}])
        self.assertTrue(res6["success"])
        self.cdp.activate_tab.assert_awaited_once_with("t1", bring_to_front=False)

        # type
        self.cdp.type_text = AsyncMock(return_value=True)
        res7 = await self.batch.execute([{"action": "type", "text": "hello", "delay_ms": 15.0}])
        self.assertTrue(res7["success"])
        self.cdp.type_text.assert_awaited_once_with("hello", delay_ms=15.0, press_enter=False)


class TestUniversalCdpMethods(unittest.IsolatedAsyncioTestCase):
    async def test_kitesurf_vs_chrome_get_page_state(self):
        from fast_browser.cdp import CDPClient

        client = CDPClient()

        # 1. Kitesurf backend
        client._backend = "kitesurf"
        client.send = AsyncMock(return_value={"seq": 42, "scrollX": 0, "scrollY": 150, "href": "https://kitesurf.dev", "title": "Kitesurf"})
        state_k = await client.get_page_state()
        self.assertEqual(state_k["seq"], 42)
        self.assertEqual(state_k["backend"], "kitesurf")

        # 2. Chrome backend fallback
        client._backend = "chrome"
        client.evaluate = AsyncMock(return_value={"seq": 7, "scroll_x": 0, "scroll_y": 50, "url": "https://google.com", "title": "Google", "backend": "chrome"})
        state_c = await client.get_page_state()
        self.assertEqual(state_c["seq"], 7)
        self.assertEqual(state_c["backend"], "chrome")

    async def test_turbo_mode_cdp(self):
        from fast_browser.cdp import CDPClient

        client = CDPClient()
        client._backend = "kitesurf"
        client.send = AsyncMock(return_value={"mode": "off"})
        res_k = await client.set_turbo_mode(True)
        self.assertEqual(res_k["backend"], "kitesurf")
        self.assertTrue(res_k["turbo"])

        client._backend = "chrome"
        client.send = AsyncMock()
        client.evaluate = AsyncMock()
        res_c = await client.set_turbo_mode(True)
        self.assertEqual(res_c["backend"], "chrome")
        self.assertTrue(res_c["turbo"])

    async def test_activate_tab_and_type_text_cdp(self):
        from fast_browser.cdp import CDPClient

        client = CDPClient()
        client.target_id = "test-tab-id"
        client.send = AsyncMock(return_value={})

        ok = await client.activate_tab()
        self.assertTrue(ok)
        client.send.assert_any_await("Target.activateTarget", {"targetId": "test-tab-id"})
        client.send.assert_any_await("Emulation.setFocusEmulationEnabled", {"enabled": True})

        # Test type_text
        client.send.reset_mock()
        ok_type = await client.type_text("hi", delay_ms=0, press_enter=False)
        self.assertTrue(ok_type)
        self.assertEqual(client.send.await_count, 4)  # 2 chars * (keyDown + keyUp)


if __name__ == "__main__":
    unittest.main()
