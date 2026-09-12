import os
import sys
import time
import socket
import atexit
import tempfile
import shutil
import subprocess
import requests
import unittest
from fast_browser.cdp import CDPClient

class TestBrowserManager:
    _port = None
    _proc = None
    _tmpdir = None

    @classmethod
    def get_port(cls) -> int:
        if "CDP_PORT" in os.environ:
            return int(os.environ["CDP_PORT"])

        if cls._port is not None:
            return cls._port

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            cls._port = s.getsockname()[1]

        cls._tmpdir = tempfile.mkdtemp(prefix="fast_browser_test_")
        
        browser_bin = None
        for b in ["google-chrome", "chromium", "chromium-browser"]:
            if shutil.which(b):
                browser_bin = b
                break
        
        if not browser_bin:
            cls._port = 9222
            return cls._port

        cmd = [
            browser_bin,
            "--headless=new",
            f"--remote-debugging-port={cls._port}",
            f"--user-data-dir={cls._tmpdir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--mute-audio",
            "about:blank"
        ]

        cls._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        url = f"http://127.0.0.1:{cls._port}/json/version"
        ready = False
        for _ in range(50):
            try:
                r = requests.get(url, timeout=0.5)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.1)

        if not ready:
            cls.cleanup()
            raise RuntimeError(f"Failed to start isolated headless test browser on port {cls._port}")

        os.environ["CDP_PORT"] = str(cls._port)
        atexit.register(cls.cleanup)
        return cls._port

    @classmethod
    def cleanup(cls):
        if cls._proc:
            try:
                cls._proc.terminate()
                cls._proc.wait(timeout=2)
            except Exception:
                try:
                    cls._proc.kill()
                except Exception:
                    pass
            cls._proc = None
        if cls._tmpdir:
            shutil.rmtree(cls._tmpdir, ignore_errors=True)
            cls._tmpdir = None
        cls._port = None


class BaseBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_port = TestBrowserManager.get_port()

    def setUp(self):
        self.cdp = CDPClient(port=self.test_port)
        self.tab = self.cdp.new_tab_sync("about:blank")
        self.tab_id = self.tab["id"]

    def tearDown(self):
        try:
            self.cdp.close_tab_sync(self.tab_id)
        except Exception:
            pass
