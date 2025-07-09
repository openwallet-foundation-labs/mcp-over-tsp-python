from mcp.server.fastmcp import TMCP
from mcp.server.fastmcp.prompts import base
from mcp.server.fastmcp.server import Context
from mcp.types import (
    ListRootsResult,
    SamplingMessage,
    TextContent,
)

# Create an MCP server
mcp = TMCP("Demo", port=8001)


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


# Add a predefined prompt with a `name` parameter
@mcp.prompt()
async def yoda(name: str) -> list[base.Message]:
    return [
        base.UserMessage(
            TextContent(
                type="text",
                text=f"Hello! I'm {name}. In this conversation, please talk to me like you are Yoda from Star Wars.",
            )
        )
    ]


# Try out sampling by using this tool
@mcp.tool()
async def sampling_demo(message: str) -> str:
    """Perform a sample request to show how the MCP's sample functionality works"""

    value = await mcp.get_context().session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=f"What do you want to do with this: {message}"),
            )
        ],
        max_tokens=100,
    )

    return f"Received back {value.content}"


# Try out roots by using this tool
@mcp.tool()
async def show_roots(ctx: Context) -> str:
    """Show the MCP roots provided by the client"""
    result: ListRootsResult = await ctx.session.list_roots()
    return result.model_dump_json()



if __name__ == "__main__":
    import sys

    # Initialize and run the server
    transport = sys.argv[1] if len(sys.argv) >= 2 else "sse"
    mcp.run(transport=transport)  # type: ignore
