import base64
import logging
from contextlib import asynccontextmanager
from typing import Any

import anyio
import tsp_python as tsp
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic_core import ValidationError
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

import mcp.shared.tmcp as tmcp
import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def websocket_server(
    scope: Scope,
    receive: Receive,
    send: Send,
    wallet: tsp.SecureStore,
    did: str,
    user_did: str,
):
    """
    WebSocket server transport for MCP. This is an ASGI application, suitable to be
    used with a framework like Starlette and a server like Hypercorn.
    """

    websocket = WebSocket(scope, receive, send)
    await websocket.accept(subprotocol="mcp")

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def ws_reader():
        try:
            async with read_stream_writer:
                async for msg in websocket.iter_text():
                    # Open TSP message (only works for known sender DIDs)
                    msg_bytes = base64.urlsafe_b64decode(msg.encode())
                    logger.info("Received TSP message:")
                    tsp.color_print(msg_bytes)
                    (sender, receiver) = wallet.get_sender_receiver(msg_bytes)
                    if receiver != did:
                        logger.warning(f"Received message intended for: {receiver}")
                        continue

                    json_text = wallet.open_message(msg_bytes).message
                    logger.info(f"Decoded TSP message: {json_text}")

                    try:
                        client_message = types.JSONRPCMessage.model_validate_json(
                            json_text
                        )
                    except ValidationError as exc:
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(client_message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:
            await websocket.close()

    async def ws_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_message = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )

                    # Seal TSP message
                    logger.info(f"Encoding TSP message: {json_message}")
                    _, tsp_message = wallet.seal_message(
                        did, user_did, json_message.encode()
                    )
                    logger.info("Sending TSP message:")
                    tsp.color_print(tsp_message)
                    encoded_message = base64.urlsafe_b64encode(tsp_message).decode()

                    await websocket.send_text(encoded_message)
        except anyio.ClosedResourceError:
            await websocket.close()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ws_reader)
        tg.start_soon(ws_writer)
        yield (read_stream, write_stream)
