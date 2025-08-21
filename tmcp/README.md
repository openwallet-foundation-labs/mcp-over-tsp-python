# TMCP Transport Hook

This Python project implements the TMCP transport hook, allowing you to use MCP over TSP.

See [`./demo`](https://github.com/openwallet-foundation-labs/mcp-over-tsp-python/tree/main/tmcp/demo) for some example TMCP servers and clients.

## Example usage

```py
from mcp.server.fastmcp import FastMCP
from tmcp import TmcpManager

# Create an MCP server
mcp = FastMCP("Demo", port=8001, transport_manager=TmcpManager(transport="http://localhost:8001/mcp"))


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="streamable-http")
```
