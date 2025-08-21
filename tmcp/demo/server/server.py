from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.server.fastmcp.server import Context
from mcp.types import (
    ContentBlock,
    ListRootsResult,
    SamplingMessage,
    TextContent,
)
from pydantic import BaseModel, Field

from tmcp import TmcpManager

# Create an MCP server
mcp = FastMCP("Demo", port=8001, transport_manager=TmcpManager(transport="http://localhost:8001/mcp"))


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


# Try out sampling and elicitation by using this tool
@mcp.tool()
async def favorite_animal_guesser() -> ContentBlock:
    """Guess the user's favorite animal"""

    # Ask the user for their favorite color
    class FavoriteColor(BaseModel):
        color: str = Field(description="Your favorite color")

    response = await mcp.get_context().elicit(
        message="What is your favorite color?",
        schema=FavoriteColor,
    )

    if response.action != "accept":
        return TextContent(type="text", text="The user did not answer my question, can't continue.")

    # Sample the LLM for what could be the user's favorite animal based on their favorite color
    value = await mcp.get_context().session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"The user's favorite color is {response.data.color}. Based on this information, suggest what "
                    "you think is most likely the user's favorite animal. Keep your answer short and concise. Even if "
                    "you don't know, pick a random animal that sort of matches the color.",
                ),
            )
        ],
        max_tokens=100,
    )

    return value.content


# Try out roots by using this tool
@mcp.tool()
async def show_roots(ctx: Context) -> str:
    """Show the MCP roots provided by the client"""
    result: ListRootsResult = await ctx.session.list_roots()
    return result.model_dump_json()


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport="streamable-http")
