import base64
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import tsp_python as tsp
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from websockets.asyncio.client import connect as ws_connect
from websockets.typing import Subprotocol

import mcp.shared.tmcp as tmcp
import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def websocket_client(
    name: str,
    server_did: str,
    **tmcp_settings: Any,
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ],
    None,
]:
    """
    WebSocket client transport for MCP, symmetrical to the server version.

    Connects to 'url' using the 'mcp' subprotocol, then yields:
        (read_stream, write_stream)

    - read_stream: As you read from this stream, you'll receive either valid
      JSONRPCMessage objects or Exception objects (when validation fails).
    - write_stream: Write JSONRPCMessage objects to this stream to send them
      over the WebSocket to the server.
    """

    # Create two in-memory streams:
    # - One for incoming messages (read_stream, written by ws_reader)
    # - One for outgoing messages (write_stream, read by ws_writer)
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # initialize TMCP client
    wallet = tsp.SecureStore()
    did = tmcp.init_identity(wallet, alias=f"{name}TmcpClient", **tmcp_settings)
    url = tmcp.resolve_server(wallet, server_did, did)
    if not url.startswith("ws://") and not url.startswith("wss://"):
        raise Exception(f"Server does not use WebSockets for transport: {url}")

    # Connect using websockets, requesting the "mcp" subprotocol
    async with ws_connect(url, subprotocols=[Subprotocol("mcp")]) as ws:

        async def ws_reader():
            """
            Reads text messages from the WebSocket, parses them as JSON-RPC messages,
            and sends them into read_stream_writer.
            """
            async with read_stream_writer:
                async for raw_text in ws:
                    try:
                        # Open TSP message
                        tsp_message = base64.urlsafe_b64decode(raw_text)
                        json_message = wallet.open_message(tsp_message).message

                        message = types.JSONRPCMessage.model_validate_json(json_message)
                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
                    except ValidationError as exc:
                        # If JSON parse or model validation fails, send the exception
                        await read_stream_writer.send(exc)

        async def ws_writer():
            """
            Reads JSON-RPC messages from write_stream_reader and
            sends them to the server.
            """
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    # Convert to a dict, then to JSON
                    msg_dict = session_message.message.model_dump(
                        by_alias=True, mode="json", exclude_none=True
                    )
                    json_message = json.dumps(msg_dict).encode()

                    # Encrypt & sign message with TSP
                    _, tsp_message = wallet.seal_message(did, server_did, json_message)

                    await ws.send(base64.urlsafe_b64encode(tsp_message).decode())

        async with anyio.create_task_group() as tg:
            # Start reader and writer tasks
            tg.start_soon(ws_reader)
            tg.start_soon(ws_writer)

            # Yield the receive/send streams
            yield (read_stream, write_stream)

            # Once the caller's 'async with' block exits, we shut down
            tg.cancel_scope.cancel()
