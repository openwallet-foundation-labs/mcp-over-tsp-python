"""FastMCP - A more ergonomic interface for MCP servers."""

from importlib.metadata import version

from .server import TMCP, Context
from .utilities.types import Image

__version__ = version("mcp")
__all__ = ["TMCP", "Context", "Image"]
