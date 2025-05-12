"""
FastMCP Echo Server
"""

from mcp.server.fastmcp import TMCP

# Create server
mcp = TMCP("Echo Server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text"""
    return text
