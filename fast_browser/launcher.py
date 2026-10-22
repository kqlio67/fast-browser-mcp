import atexit
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import requests

logger = logging.getLogger("fast_browser.launcher")

CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "microsoft-edge",
    "google-chrome-unstable",
    "google-chrome-beta",
]

MACOS_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

WINDOWS_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser_executable(custom_path: str | None = None) -> str | None:
    """Locate a Chrome-compatible browser executable on the current system."""
    if custom_path and os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
        return custom_path

    env_path = os.environ.get("CHROME_PATH") or os.environ.get("BROWSER_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    # Check standard PATH
    for candidate in CHROME_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found

    # macOS paths
    for mac_path in MACOS_CANDIDATES:
        if os.path.exists(mac_path) and os.access(mac_path, os.X_OK):
            return mac_path

    # Windows paths
    for win_path in WINDOWS_CANDIDATES:
        if os.path.exists(win_path) and os.access(win_path, os.X_OK):
            return win_path

    return None


def find_free_port() -> int:
    """Find an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def is_running_as_root() -> bool:
    """Check if the current process is running as root or administrator."""
    try:
        return os.getuid() == 0  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def is_running_in_container() -> bool:
    """Check if the current process is running inside a Docker/Kubernetes container."""
    if (
        os.path.exists("/.dockerenv")
        or os.environ.get("container")
        or os.environ.get("KUBERNETES_SERVICE_HOST")
    ):
        return True
    try:
        if os.path.exists("/proc/1/cgroup"):
            with open("/proc/1/cgroup", encoding="utf-8") as f:
                content = f.read()
                return "docker" in content or "kubepods" in content
    except (OSError, PermissionError):
        pass
    return False


def sandbox_must_be_disabled() -> bool:
    """Determine if Chrome sandbox must be disabled on the current platform."""
    if platform.system().lower() != "linux":
        return False
    return is_running_as_root() or is_running_in_container()


def cleanup_stale_profiles(max_age_seconds: int = 21600) -> int:
    """Clean up orphan fast_browser_profile_* temp directories older than max_age_seconds (default 6h)."""
    temp_dir = tempfile.gettempdir()
    now = time.time()
    cleaned = 0
    try:
        for entry in os.listdir(temp_dir):
            if entry.startswith("fast_browser_profile_"):
                full_path = os.path.join(temp_dir, entry)
                try:
                    if os.path.isdir(full_path):
                        mtime = os.path.getmtime(full_path)
                        if (now - mtime) > max_age_seconds:
                            shutil.rmtree(full_path, ignore_errors=True)
                            cleaned += 1
                except (OSError, PermissionError):
                    pass
    except Exception as e:
        logger.debug(f"Error sweeping stale profiles: {e}")
    return cleaned


def validate_environment() -> dict[str, Any]:
    """Validate system and browser environment for automation readiness."""
    browser_path = find_browser_executable()
    sys_name = platform.system()
    is_root = is_running_as_root()
    is_container = is_running_in_container()
    sandbox_needed = sandbox_must_be_disabled()

    browser_type = "Unknown"
    if browser_path:
        b_lower = browser_path.lower()
        if "brave" in b_lower:
            browser_type = "Brave"
        elif "edge" in b_lower or "msedge" in b_lower:
            browser_type = "Microsoft Edge"
        elif "chromium" in b_lower:
            browser_type = "Chromium"
        elif "chrome" in b_lower:
            browser_type = "Google Chrome"

    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    return {
        "status": "ready" if browser_path else "missing_browser",
        "browser_path": browser_path,
        "browser_type": browser_type,
        "system": sys_name,
        "release": platform.release(),
        "is_root": is_root,
        "is_container": is_container,
        "sandbox_disabled_required": sandbox_needed,
        "has_display": has_display,
        "recommended_args": ["--no-sandbox"] if sandbox_needed else [],
    }


class BrowserProcess:
    """Manages the lifecycle of a launched browser process with remote debugging."""

    def __init__(
        self,
        proc: subprocess.Popen,
        port: int,
        user_data_dir: str,
        is_temp_dir: bool = False,
    ):
        self.proc = proc
        self.port = port
        self.user_data_dir = user_data_dir
        self.is_temp_dir = is_temp_dir
        self._cleaned = False

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self):
        if self._cleaned:
            return
        self._cleaned = True
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except OSError as e:
            logger.debug(f"Error terminating browser process: {e}")

        if self.is_temp_dir and os.path.exists(self.user_data_dir):
            try:
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
            except OSError as e:
                logger.debug(f"Error removing temp user data dir: {e}")

    def __del__(self):
        self.terminate()


_active_browsers: list[BrowserProcess] = []


def _cleanup_all():
    for b in list(_active_browsers):
        b.terminate()
    _active_browsers.clear()


atexit.register(_cleanup_all)


def launch_browser(
    port: int | None = None,
    headless: bool = True,
    user_data_dir: str | None = None,
    executable_path: str | None = None,
    extra_args: list[str] | None = None,
    timeout: float = 15.0,
) -> BrowserProcess:
    """Launch a Chrome/Chromium instance with CDP remote debugging enabled.

    Args:
        port: Target CDP port. If None or 0, a free port is chosen.
        headless: Whether to run in new headless mode.
        user_data_dir: Path to browser profile directory. If None, a temp directory is created.
        executable_path: Custom path to browser binary.
        extra_args: Additional command line flags.
        timeout: Seconds to wait for CDP endpoint to become ready.
    """
    browser_bin = find_browser_executable(executable_path)
    if not browser_bin:
        raise RuntimeError(
            "No Chrome or Chromium-based browser executable found. "
            "Please install Google Chrome or set CHROME_PATH."
        )

    target_port = port if (port and port > 0) else find_free_port()

    is_temp_dir = False
    if not user_data_dir:
        user_data_dir = tempfile.mkdtemp(prefix="fast_browser_profile_")
        is_temp_dir = True
    else:
        os.makedirs(user_data_dir, exist_ok=True)

    cleanup_stale_profiles()

    cmd = [
        browser_bin,
        f"--remote-debugging-port={target_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--mute-audio",
    ]

    if sandbox_must_be_disabled():
        cmd.append("--no-sandbox")

    if headless:
        cmd.append("--headless=new")
        if (
            sys.platform == "linux"
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        ):
            cmd.append("--disable-gpu")

    if extra_args:
        cmd.extend(extra_args)

    cmd.append("about:blank")

    logger.info(f"Launching browser: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    bp = BrowserProcess(
        proc=proc,
        port=target_port,
        user_data_dir=user_data_dir,
        is_temp_dir=is_temp_dir,
    )

    url = f"http://127.0.0.1:{target_port}/json/version"
    start_time = time.time()
    ready = False

    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            bp.terminate()
            raise RuntimeError(
                f"Browser exited prematurely with code {proc.poll()} while starting on port {target_port}."
            )
        try:
            resp = requests.get(url, timeout=0.5)
            if resp.status_code == 200:
                ready = True
                break
        except (requests.RequestException, OSError):
            pass
        time.sleep(0.1)

    if not ready:
        bp.terminate()
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for browser CDP endpoint on port {target_port}."
        )

    _active_browsers.append(bp)
    return bp
