import asyncio
from contextlib import AsyncExitStack

import mcp
from anthropic import Anthropic
from dotenv import load_dotenv
from mcp.client.streamable_http import streamablehttp_client

from tmcp import TmcpManager

load_dotenv()  # load environment variables from .env


class TMCPClient:
    # Based on https://github.com/modelcontextprotocol/quickstart-resources/blob/main/mcp-client-python/client.py
    def __init__(self, name: str):
        # Initialize session and client objects
        self.session: mcp.ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        self.name = name

    async def connect_to_server(self, url_or_id: str):
        """Connect to an MCP server"""

        print("Server endpoint:", url_or_id)

        self.read, self.write, _ = await self.exit_stack.enter_async_context(
            streamablehttp_client(url_or_id, transport_hook=TmcpManager().get_client_hook(url_or_id))
        )

        self.session = await self.exit_stack.enter_async_context(mcp.ClientSession(self.read, self.write))

        await self.session.initialize()

        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnected to server with tools:", [tool.name for tool in tools])

    async def process_query(self, query: str):
        """Process a query using Claude and available tools"""
        messages = [{"role": "user", "content": query}]

        response = await self.session.list_tools()
        available_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in response.tools
        ]

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools,
        )

        # Process response and handle tool calls
        assistant_message_content = []

        async def handle_response_content(content):
            nonlocal assistant_message_content

            if content.type == "text":
                print("\n" + content.text)
                assistant_message_content.append(content)
            elif content.type == "tool_use":
                tool_name = content.name
                tool_args = content.input

                # Execute tool call
                result = await self.session.call_tool(tool_name, tool_args)
                print(f"\n\033[90m[Calling tool {tool_name} with args {tool_args}]\033[0m")

                assistant_message_content.append(content)
                messages.append({"role": "assistant", "content": assistant_message_content})
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": content.id,
                                "content": result.content,
                            }
                        ],
                    }
                )

                assistant_message_content = []

                # Get next response from Claude
                response = self.anthropic.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=1000,
                    messages=messages,
                    tools=available_tools,
                )

                print("\n" + response.content[0].text)
                for content in response.content[1:]:
                    await handle_response_content(content)

        for content in response.content:
            await handle_response_content(content)

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                # Use asyncio friendly version of input() such that we don't time out
                # the websocket connection
                # query = input("\nQuery: ").strip()
                await asyncio.to_thread(sys.stdout.write, "\nQuery: ")
                query = await asyncio.to_thread(sys.stdin.readline)
                query = query.strip()

                if query.lower() == "quit":
                    break

                await self.process_query(query)

            except Exception as e:
                print(f"\nError: {str(e)}")

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run client.py did:web:did.teaspoon.world:endpoint:YourMcpServer")
        sys.exit(1)

    client = TMCPClient("Demo")
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    import sys

    asyncio.run(main())
