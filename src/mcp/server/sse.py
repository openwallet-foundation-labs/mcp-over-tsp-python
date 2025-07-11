"""
SSE Server Transport Module

This module implements a Server-Sent Events (SSE) transport layer for MCP servers.

Example usage:
```
    # Create an SSE transport at an endpoint
    sse = SseServerTransport("/messages/")

    # Create Starlette routes for SSE and message handling
    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]

    # Define handler functions
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )
        # Return empty response to avoid NoneType error
        return Response()

    # Create and run Starlette app
    starlette_app = Starlette(routes=routes)
    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
```

Note: The handle_sse function must return a Response to avoid a "TypeError: 'NoneType'
object is not callable" error when client disconnects. The example above returns
an empty Response() after the SSE connection ends to fix this.

See SseServerTransport class documentation for more details.
"""

import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

import mcp.shared.tmcp as tmcp
import mcp.types as types
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from mcp.shared.message import ServerMessageMetadata, SessionMessage

logger = logging.getLogger(__name__)


class SseServerTransport:
    """
    SSE server transport for MCP. This class provides _two_ ASGI applications,
    suitable to be used with a framework like Starlette and a server like Hypercorn:

        1. connect_sse() is an ASGI application which receives incoming GET requests,
           and sets up a new SSE stream to send server messages to the client.
        2. handle_post_message() is an ASGI application which receives incoming POST
           requests, which should contain client messages that link to a
           previously-established SSE session.
    """

    _endpoint: str
    _read_stream_writers: dict[str, MemoryObjectSendStream[SessionMessage | Exception]]
    _security: TransportSecurityMiddleware

    def __init__(
        self, name: str, endpoint: str, security_settings: TransportSecuritySettings | None = None, **tmcp_settings: Any
    ) -> None:
        """
        Creates a new SSE server transport, which will direct the client to POST
        messages to the relative or absolute URL given.

        Args:
            endpoint: The relative or absolute URL for POST messages.
            security_settings: Optional security settings for DNS rebinding protection.
        """

        super().__init__()
        self._endpoint = endpoint
        self._read_stream_writers = {}
        self._security = TransportSecurityMiddleware(security_settings)
        logger.debug(f"SseServerTransport initialized with endpoint: {endpoint}")

        self.tmcp = tmcp.TmcpIdentityManager(alias=f"{name}TmcpSseServer", **tmcp_settings)

    @asynccontextmanager
    async def connect_sse(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            logger.error("connect_sse received non-HTTP request")
            raise ValueError("connect_sse can only handle HTTP requests")

        # Validate request headers for DNS rebinding protection
        request = Request(scope, receive)
        error_response = await self._security.validate_request(request, is_post=False)
        if error_response:
            await error_response(scope, receive, send)
            raise ValueError("Request validation failed")

        logger.debug("Setting up SSE connection")
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

        write_stream: MemoryObjectSendStream[SessionMessage]
        write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        request = Request(scope, receive)
        user_did = request.query_params.get("did")
        if user_did is None:
            logger.warning("Received request without user did")
            raise Exception("did is required")
        tmcp_connection = self.tmcp.get_connection(user_did)

        logger.debug(f"Created new session with ID: {user_did}")
        self._read_stream_writers[user_did] = read_stream_writer

        # Determine the full path for the message endpoint to be sent to the client.
        # scope['root_path'] is the prefix where the current Starlette app
        # instance is mounted.
        # e.g., "" if top-level, or "/api_prefix" if mounted under "/api_prefix".
        root_path = scope.get("root_path", "")

        # self._endpoint is the path *within* this app, e.g., "/messages".
        # Concatenating them gives the full absolute path from the server root.
        # e.g., "" + "/messages" -> "/messages"
        # e.g., "/api_prefix" + "/messages" -> "/api_prefix/messages"
        full_message_path_for_client = root_path.rstrip("/") + self._endpoint

        # This is the URI (path + query) the client will use to POST messages.
        client_post_uri_data = quote(full_message_path_for_client)

        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, Any]](0)

        async def sse_send(event: str, data: Any):
            json_message = json.dumps({"event": event, "data": data})

            # Seal TSP message
            tsp_message = tmcp_connection.seal_message(json_message)

            await sse_stream_writer.send({"event": "message", "data": tsp_message})

        async def sse_writer():
            logger.debug("Starting SSE writer")
            async with sse_stream_writer, write_stream_reader:
                await sse_send("endpoint", client_post_uri_data)
                logger.debug(f"Sent endpoint event: {client_post_uri_data}")

                async for session_message in write_stream_reader:
                    await sse_send(
                        "message",
                        session_message.message.model_dump_json(by_alias=True, exclude_none=True),
                    )

        async with anyio.create_task_group() as tg:

            async def response_wrapper(scope: Scope, receive: Receive, send: Send):
                """
                The EventSourceResponse returning signals a client close / disconnect.
                In this case we close our side of the streams to signal the client that
                the connection has been closed.
                """
                await EventSourceResponse(content=sse_stream_reader, data_sender_callable=sse_writer)(
                    scope, receive, send
                )
                await read_stream_writer.aclose()
                await write_stream_reader.aclose()
                logging.debug(f"Client session disconnected {user_did}")

            logger.debug("Starting SSE response task")
            tg.start_soon(response_wrapper, scope, receive, send)

            logger.debug("Yielding read and write streams")
            yield (read_stream, write_stream)

    async def handle_post_message(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.debug("Handling POST message")
        request = Request(scope, receive)

        # Validate request headers for DNS rebinding protection
        error_response = await self._security.validate_request(request, is_post=True)
        if error_response:
            return await error_response(scope, receive, send)

        # Open TSP message (only works for known sender DIDs)
        body = await request.body()
        (sender, receiver) = self.tmcp.wallet.get_sender_receiver(base64.urlsafe_b64decode(body))
        if receiver != self.tmcp.did:
            logger.warning(f"Received message intended for: {receiver}")
            response = Response("Incorrect receiver", status_code=400)
            return await response(scope, receive, send)

        json_text = self.tmcp.get_connection(sender).open_message(body.decode())

        writer = self._read_stream_writers.get(sender)
        if not writer:
            logger.warning(f"Could not find session for ID: {sender}")
            response = Response("Could not find session", status_code=404)
            return await response(scope, receive, send)

        try:
            message = types.JSONRPCMessage.model_validate_json(json_text)
            logger.debug(f"Validated client message: {message}")
        except ValidationError as err:
            logger.error(f"Failed to parse message: {err}")
            response = Response("Could not parse message", status_code=400)
            await response(scope, receive, send)
            await writer.send(err)
            return

        # Pass the ASGI scope for framework-agnostic access to request data
        metadata = ServerMessageMetadata(request_context=request)
        session_message = SessionMessage(message, metadata=metadata)
        logger.debug(f"Sending session message to writer: {session_message}")
        response = Response("Accepted", status_code=202)
        await response(scope, receive, send)
        await writer.send(session_message)
