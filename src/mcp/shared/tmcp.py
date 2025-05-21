import base64
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import requests
import tsp_python as tsp
from pydantic_settings import BaseSettings


class TmcpSettings(BaseSettings):
    """TMCP general settings"""

    did_publish_url: str = "https://did.teaspoon.world/add-vid"
    did_format: str = "did:web:did.teaspoon.world:endpoint:{name}-{uuid}"
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
            if "reqwest::Error { kind: Status(404)" in e.args[0]:
                did = None  # create a new DID
            else:
                raise e

        if did is not None:
            print("Using existing DID: " + did)
            return did

    # Initialize new TSP identity
    did = settings.did_format.format(name=alias, uuid=uuid4())
    identity = tsp.OwnedVid.bind(did, settings.transport)

    # Publish DID
    response = requests.post(
        settings.did_publish_url,
        data=identity.json(),
        headers={"Content-type": "application/json"},
    )

    if not response.ok:
        raise Exception(f"Could not publish DID (status code: {response.status_code})")

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
