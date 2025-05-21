from mcp.server.fastmcp import TMCP

# Create an MCP server
mcp = TMCP("Demo")


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


if __name__ == "__main__":
    import sys

    # Initialize and run the server
    transport = sys.argv[1] if len(sys.argv) >= 2 else "sse"
    mcp.run(transport=transport)
