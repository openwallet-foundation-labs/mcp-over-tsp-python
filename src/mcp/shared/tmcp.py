import base64
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import httpx
import tsp_python as tsp
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class TmcpSettings(BaseSettings):
    """TMCP general settings"""

    did_publish_url: str = "https://did.teaspoon.world/add-vid"
    did_publish_history_url: str = "https://did.teaspoon.world/add-history/{did}"
    did_web_format: str = "did:web:did.teaspoon.world:endpoint:{name}"
    did_webvh_format: str = "did.teaspoon.world/endpoint/{name}"
    transport: str = "tmcpclient://"  # clients are not publicly accessible
    verbose: bool = True  # whether or not TSP message should be printed
    wallet_url: str = "sqlite://wallet.sqlite"
    wallet_password: str = "unsecure"
    use_webvh: bool = True


class TmcpIdentityManager:
    def __init__(self, alias: str, **tmcp_settings: Any):
        self.settings: TmcpSettings = TmcpSettings(**tmcp_settings)
        self.wallet = tsp.SecureStore(
            self.settings.wallet_url,
            self.settings.wallet_password,
        )
        self.did = self._init_identity(alias)

    def _init_identity(self, alias: str) -> str:
        did = self.wallet.resolve_alias(alias)

        if did is not None:
            # Verify DID still exists
            try:
                self.wallet.verify_vid(did)
            except Exception as e:
                if 'ResolveVid("Not found")' in e.args[0] or "kind: Status(404)" in e.args[0]:
                    did = None  # create a new DID
                else:
                    raise e

            if did is not None:
                print("Using existing DID: " + did)
                return did

        # Initialize new TSP identity
        did_format = self.settings.did_webvh_format if self.settings.use_webvh else self.settings.did_web_format
        did = did_format.format(name=f"{alias}-{uuid4()}"[:63])
        history = None
        if self.settings.use_webvh:
            (identity, history) = tsp.OwnedVid.new_did_webvh(did, self.settings.transport)
        else:
            identity = tsp.OwnedVid.bind(did, self.settings.transport)

        did = identity.identifier()  # get generate DID (may be different from the formatted DID, e.g. for did:webvh)

        # Publish DID
        httpx.post(
            self.settings.did_publish_url,
            content=identity.json().encode(),
            headers={"Content-type": "application/json"},
        ).raise_for_status()

        if history:
            # Publish did:webvh history
            httpx.post(
                self.settings.did_publish_history_url.format(did=did),
                content=history.encode(),
                headers={"Content-type": "application/json"},
            ).raise_for_status()

        print("Published client DID:", did)

        self.wallet.add_private_vid(identity, alias)

        return did

    def get_connection(self, other_did: str):
        self.wallet.verify_vid(other_did)
        return TmcpConnection(self.wallet, self.did, other_did, self.settings.verbose)


class TmcpConnection:
    def __init__(self, wallet: tsp.SecureStore, my_did: str, other_did: str, verbose: bool = True):
        self.wallet = wallet
        self.my_did = my_did
        self.other_did = other_did
        self.verbose = verbose

    def seal_message(self, message: str) -> str:
        # Seal TSP message
        if self.verbose:
            logger.info(f"Encoding TSP message: {message}")

        _, tsp_message = self.wallet.seal_message(self.my_did, self.other_did, message.encode())

        if self.verbose:
            logger.info("Sending TSP message:")
            print(tsp.color_print(tsp_message))

        return base64.urlsafe_b64encode(tsp_message).decode()

    def open_message(self, message: str) -> str:
        tsp_message = base64.urlsafe_b64decode(message)

        # Open TSP message
        if self.verbose:
            logger.info("Received TSP message:")
            print(tsp.color_print(tsp_message))

        (sender, receiver) = self.wallet.get_sender_receiver(tsp_message)
        if receiver != self.my_did:
            logger.warning(f"Received message intended for: {receiver} (expected {self.my_did})")
        if sender != self.other_did:
            logger.warning(f"Received message intended for: {sender} (expected {self.other_did})")

        json_message = self.wallet.open_message(tsp_message)
        if not isinstance(json_message, tsp.GenericMessage):
            raise Exception("Received not generic message", json_message)

        if self.verbose:
            logger.info(f"Decoded TSP message: {json_message.message}")

        return json_message.message

    def resolve_server_url(self, append_did: bool = False) -> str:
        return resolve_server(self.wallet, self.other_did, self.my_did if append_did else None)


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
