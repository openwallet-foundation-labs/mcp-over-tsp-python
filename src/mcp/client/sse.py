import json
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import ServerSentEvent, aconnect_sse

import mcp.shared.tmcp as tmcp
import mcp.types as types
from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


def remove_request_params(url: str) -> str:
    return urljoin(url, urlparse(url).path)


@asynccontextmanager
async def sse_client(
    name: str,
    server_did: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    auth: httpx.Auth | None = None,
    **tmcp_settings: Any,
):
    """
    Client transport for SSE.

    `sse_read_timeout` determines how long (in seconds) the client will wait for a new
    event before disconnecting. All other HTTP operations are controlled by `timeout`.

    Args:
        url: The SSE endpoint URL.
        headers: Optional headers to include in requests.
        timeout: HTTP timeout for regular operations.
        sse_read_timeout: Timeout for SSE read operations.
        auth: Optional HTTPX authentication handler.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # initialize TMCP client
    tmcp_connection = tmcp.TmcpIdentityManager(alias=f"{name}TmcpClient", **tmcp_settings).get_connection(server_did)
    url = tmcp_connection.resolve_server_url(True)

    if not url.startswith("sse://") and not url.startswith("sses://"):
        raise Exception(f"Server does not use SSE for transport: {url}")

    url = url.replace("sse://", "http://")  # SSE actually just uses HTTP
    url = url.replace("sses://", "https://")

    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to SSE endpoint: {remove_request_params(url)}")
            async with httpx_client_factory(
                headers=headers, auth=auth, timeout=httpx.Timeout(timeout, read=sse_read_timeout)
            ) as client:
                async with aconnect_sse(
                    client,
                    "GET",
                    url,
                ) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("SSE connection established")

                    async def sse_reader(
                        task_status: TaskStatus[str] = anyio.TASK_STATUS_IGNORED,
                    ):
                        try:
                            async for sse in event_source.aiter_sse():
                                # Open TSP message
                                json_message = tmcp_connection.open_message(sse.data)
                                json_data = json.loads(json_message)
                                sse = ServerSentEvent(**json_data)

                                logger.debug(f"Received SSE event: {sse.event}")
                                match sse.event:
                                    case "endpoint":
                                        endpoint_url = urljoin(url, sse.data)
                                        logger.debug(f"Received endpoint URL: {endpoint_url}")

                                        url_parsed = urlparse(url)
                                        endpoint_parsed = urlparse(endpoint_url)
                                        if (
                                            url_parsed.netloc != endpoint_parsed.netloc
                                            or url_parsed.scheme != endpoint_parsed.scheme
                                        ):
                                            error_msg = (
                                                f"Endpoint origin does not match connection origin: {endpoint_url}"
                                            )
                                            logger.error(error_msg)
                                            raise ValueError(error_msg)

                                        task_status.started(endpoint_url)

                                    case "message":
                                        try:
                                            message = types.JSONRPCMessage.model_validate_json(  # noqa: E501
                                                sse.data
                                            )
                                            logger.debug(f"Received server message: {message}")
                                        except Exception as exc:
                                            logger.error(f"Error parsing server message: {exc}")
                                            await read_stream_writer.send(exc)
                                            continue

                                        session_message = SessionMessage(message)
                                        await read_stream_writer.send(session_message)
                                    case _:
                                        logger.warning(f"Unknown SSE event: {sse.event}")
                        except Exception as exc:
                            logger.error(f"Error in sse_reader: {exc}")
                            await read_stream_writer.send(exc)
                        finally:
                            await read_stream_writer.aclose()

                    async def post_writer(endpoint_url: str):
                        try:
                            async with write_stream_reader:
                                async for session_message in write_stream_reader:
                                    json_message = session_message.message.model_dump_json(
                                        by_alias=True,
                                        exclude_none=True,
                                    )

                                    # Encrypt & sign message with TSP
                                    tsp_message = tmcp_connection.seal_message(json_message)

                                    response = await client.post(
                                        endpoint_url,
                                        content=tsp_message,
                                        headers={"content-type": "application/tsp"},
                                    )
                                    response.raise_for_status()
                                    logger.debug(f"Client message sent successfully: {response.status_code}")
                        except Exception as exc:
                            logger.error(f"Error in post_writer: {exc}")
                        finally:
                            await write_stream.aclose()

                    endpoint_url = await tg.start(sse_reader)
                    logger.debug(f"Starting post writer with endpoint URL: {endpoint_url}")
                    tg.start_soon(post_writer, endpoint_url)

                    try:
                        yield read_stream, write_stream
                    finally:
                        tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
