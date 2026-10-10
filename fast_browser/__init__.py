"""
Fast Browser MCP
~~~~~~~~~~~~~~~~

Universal, ultra-fast Chrome DevTools Protocol (CDP) browser automation
engine and Model Context Protocol (MCP) server designed for AI agents.
"""

from .batch import BatchRunner
from .cdp import CDPClient
from .network import ConsoleMonitor, NetworkMonitor
from .server import MCPServer
from .snapshot import PageSnapshot

__version__ = "0.10.0"
__author__ = "kqlio67"
__license__ = "MIT"

__all__ = [
    "BatchRunner",
    "CDPClient",
    "ConsoleMonitor",
    "MCPServer",
    "NetworkMonitor",
    "PageSnapshot",
    "__version__",
]
