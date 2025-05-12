from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import httpx
import tsp_python as tsp
from pydantic_settings import BaseSettings


class TmcpSettings(BaseSettings):
    """TMCP general settings"""

    did_publish_url: str = "https://did.teaspoon.world/add-vid"
    did_publish_history_url: str = "https://did.teaspoon.world/add-history/{did}"
    # did_format: str = "did:web:did.teaspoon.world:endpoint:{name}"  # format for did:web
    did_format: str = "did.teaspoon.world/endpoint/{name}"  # format for did:webvh
    transport: str = "tmcpclient://"  # clients are not publicly accessible


def init_identity(wallet: tsp.SecureStore, alias: str, **tmcp_settings: Any) -> str:
    """Get an identity or create a new identity"""

    settings: TmcpSettings = TmcpSettings(**tmcp_settings)

    did = wallet.resolve_alias(alias)

    if did is not None:
        # Verify DID still exists
        try:
            wallet.verify_vid(did)
        except Exception as e:
            if 'ResolveVid("Not found")' in e.args[0] or "kind: Status(404)" in e.args[0]:
                did = None  # create a new DID
            else:
                raise e

        if did is not None:
            print("Using existing DID: " + did)
            return did

    # Initialize new TSP identity
    did = settings.did_format.format(name=f"{alias}-{uuid4()}"[:63])
    # identity = tsp.OwnedVid.bind(did, settings.transport)  # did:web
    (identity, history) = tsp.OwnedVid.new_did_webvh(did, settings.transport)  # did:webvh

    did = identity.identifier()

    # Publish DID
    httpx.post(
        settings.did_publish_url,
        data=identity.json(),
        headers={"Content-type": "application/json"},
    ).raise_for_status()

    httpx.post(
        settings.did_publish_history_url.format(did=did),
        data=history,
        headers={"Content-type": "application/json"},
    ).raise_for_status()

    print("Published client DID:", did)

    wallet.add_private_vid(identity, alias)

    return did


def add_request_params(url_str: str, params: dict[str, str]) -> str:
    url = urlparse(url_str)
    query = dict(parse_qsl(url.query))
    query.update(params)
    url = url._replace(query=urlencode(query))
    return urlunparse(url)


def resolve_server(wallet: tsp.SecureStore, server_did: str, did: str | None = None):
    url = wallet.verify_vid(server_did)
    if did is not None:
        url = add_request_params(url, {"did": did})
    return url
