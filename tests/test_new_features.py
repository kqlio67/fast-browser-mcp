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


if __name__ == "__main__":
    unittest.main()
