import unittest

from fast_browser.launcher import (
    find_browser_executable,
    find_free_port,
)


class TestLauncher(unittest.TestCase):
    def test_find_browser_executable(self):
        # Should return a valid string or None without throwing
        browser_bin = find_browser_executable()
        if browser_bin:
            self.assertIsInstance(browser_bin, str)
            self.assertTrue(len(browser_bin) > 0)

    def test_find_free_port(self):
        port1 = find_free_port()
        port2 = find_free_port()
        self.assertIsInstance(port1, int)
        self.assertGreater(port1, 1024)
        self.assertIsInstance(port2, int)
        self.assertGreater(port2, 1024)
