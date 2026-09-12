"""
Fast Browser MCP
~~~~~~~~~~~~~~~~

Universal, ultra-fast Chrome DevTools Protocol (CDP) browser automation
engine and Model Context Protocol (MCP) server designed for AI agents.
"""

from .cdp import CDPClient
from .snapshot import PageSnapshot
from .batch import BatchRunner
from .network import NetworkMonitor, ConsoleMonitor
from .server import MCPServer

__version__ = "0.8.0"
__author__ = "kqlio67"
__license__ = "MIT"

__all__ = [
    "CDPClient",
    "PageSnapshot",
    "BatchRunner",
    "NetworkMonitor",
    "ConsoleMonitor",
    "MCPServer",
    "__version__",
]
