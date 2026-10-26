import os
import tempfile
import unittest

from fast_browser.server import MCPServer
from fast_browser.visual_diff import (
    compare_screenshots,
    decode_png,
    encode_png,
)


class TestVisualDiff(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_diff_")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_identical_png(self):
        rgba = bytearray([100, 150, 200, 255] * 25)  # 5x5 image
        png1 = encode_png(5, 5, rgba)
        res = compare_screenshots(png1, png1)

        self.assertEqual(res["status"], "identical")
        self.assertEqual(res["compared_pixels"], 25)
        self.assertEqual(res["changed_pixels"], 0)
        self.assertEqual(res["changed_ratio"], 0.0)
        self.assertEqual(res["maximum_channel_delta"], 0)
        self.assertIsNone(res["bounding_box"])

    def test_different_png_with_bounding_box(self):
        rgba1 = bytearray([0, 0, 0, 255] * 100)  # 10x10 black
        rgba2 = bytearray(rgba1)

        # Alter pixel at (2, 3) and (7, 8)
        idx1 = (3 * 10 + 2) * 4
        rgba2[idx1] = 255  # red = 255
        idx2 = (8 * 10 + 7) * 4
        rgba2[idx2 + 1] = 200  # green = 200

        png1 = encode_png(10, 10, rgba1)
        png2 = encode_png(10, 10, rgba2)

        res = compare_screenshots(png1, png2, channel_threshold=16)
        self.assertEqual(res["status"], "different")
        self.assertEqual(res["compared_pixels"], 100)
        self.assertEqual(res["changed_pixels"], 2)
        self.assertEqual(res["changed_ratio"], 0.02)
        self.assertEqual(res["maximum_channel_delta"], 255)

        bbox = res["bounding_box"]
        self.assertIsNotNone(bbox)
        self.assertEqual(bbox["min_x"], 2)
        self.assertEqual(bbox["max_x"], 7)
        self.assertEqual(bbox["min_y"], 3)
        self.assertEqual(bbox["max_y"], 8)
        self.assertEqual(bbox["width"], 6)
        self.assertEqual(bbox["height"], 6)

    def test_channel_threshold_sensitivity(self):
        rgba1 = bytearray([100, 100, 100, 255] * 10)  # 10 pixels
        rgba2 = bytearray(rgba1)
        # Small delta of 10 (less than default threshold 16)
        rgba2[0] = 110

        png1 = encode_png(10, 1, rgba1)
        png2 = encode_png(10, 1, rgba2)

        # With threshold 16: considered identical
        res1 = compare_screenshots(png1, png2, channel_threshold=16)
        self.assertEqual(res1["status"], "identical")
        self.assertEqual(res1["changed_pixels"], 0)

        # With threshold 5: considered different
        res2 = compare_screenshots(png1, png2, channel_threshold=5)
        self.assertEqual(res2["status"], "different")
        self.assertEqual(res2["changed_pixels"], 1)

    def test_dimension_mismatch(self):
        png1 = encode_png(4, 4, bytearray([0] * 64))
        png2 = encode_png(6, 6, bytearray([0] * 144))

        res = compare_screenshots(png1, png2)
        self.assertEqual(res["status"], "dimension_mismatch")
        self.assertEqual(res["dimensions_1"], {"width": 4, "height": 4})
        self.assertEqual(res["dimensions_2"], {"width": 6, "height": 6})

    def test_diff_output_file(self):
        rgba1 = bytearray([50, 50, 50, 255] * 16)  # 4x4
        rgba2 = bytearray(rgba1)
        rgba2[0] = 250  # Changed pixel

        p1 = os.path.join(self.tmpdir, "img1.png")
        p2 = os.path.join(self.tmpdir, "img2.png")
        diff_p = os.path.join(self.tmpdir, "diff.png")

        with open(p1, "wb") as f:
            f.write(encode_png(4, 4, rgba1))
        with open(p2, "wb") as f:
            f.write(encode_png(4, 4, rgba2))

        res = compare_screenshots(p1, p2, diff_output_path=diff_p)
        self.assertEqual(res["status"], "different")
        self.assertTrue(os.path.isfile(diff_p))

        # Validate generated diff image
        with open(diff_p, "rb") as f:
            w, h, raw_rgba = decode_png(f.read())
        self.assertEqual(w, 4)
        self.assertEqual(h, 4)
        # First pixel should be highlighted in red (255, 0, 0, 255)
        self.assertEqual(raw_rgba[0], 255)
        self.assertEqual(raw_rgba[1], 0)
        self.assertEqual(raw_rgba[2], 0)

    def test_mcp_server_compare_screenshots_offline(self):
        import asyncio

        async def run():
            server = MCPServer()
            rgba = bytearray([200, 100, 50, 255] * 9)  # 3x3
            png = encode_png(3, 3, rgba)

            p1 = os.path.join(self.tmpdir, "s1.png")
            p2 = os.path.join(self.tmpdir, "s2.png")
            with open(p1, "wb") as f:
                f.write(png)
            with open(p2, "wb") as f:
                f.write(png)

            # Call MCP tool handler directly
            ret_json = await server.handle_call(
                "browser_compare_screenshots", {"image1": p1, "image2": p2}
            )
            import json

            ret = json.loads(ret_json)
            self.assertEqual(ret["status"], "identical")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
