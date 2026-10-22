import unittest

from fast_browser.launcher import (
    cleanup_stale_profiles,
    find_browser_executable,
    find_free_port,
    is_running_as_root,
    is_running_in_container,
    sandbox_must_be_disabled,
    validate_environment,
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

    def test_environment_validation(self):
        res = validate_environment()
        self.assertIn("status", res)
        self.assertIn("system", res)
        self.assertIn("is_root", res)
        self.assertIn("is_container", res)
        self.assertIn("sandbox_disabled_required", res)
        self.assertIsInstance(res["is_root"], bool)
        self.assertIsInstance(res["is_container"], bool)

    def test_sandbox_helpers(self):
        root = is_running_as_root()
        container = is_running_in_container()
        self.assertIsInstance(root, bool)
        self.assertIsInstance(container, bool)
        self.assertIsInstance(sandbox_must_be_disabled(), bool)

    def test_cleanup_stale_profiles(self):
        cleaned = cleanup_stale_profiles(max_age_seconds=1000000)
        self.assertIsInstance(cleaned, int)
