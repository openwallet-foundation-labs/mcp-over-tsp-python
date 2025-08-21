import base64
import logging
from typing import Any
from uuid import uuid4

import httpx
import tsp_python as tsp
from mcp.shared.transport_hook import TransportHook, TransportManager
from pydantic_settings import BaseSettings
from starlette.requests import Request

# our client & fast-agent currently only support TMCP over StreamableHTTP
# TODO: how does the server know the client's DID with SSE?

logger = logging.getLogger(__name__)


class TmcpSettings(BaseSettings):
    """TMCP general settings"""

    did_publish_url: str = "https://did.teaspoon.world/add-vid"
    did_publish_history_url: str = "https://did.teaspoon.world/add-history/{did}"
    did_web_format: str = "did:web:did.teaspoon.world:endpoint:{name}"
    did_webvh_format: str = "did.teaspoon.world/endpoint/{name}"
    transport: str = "tmcp://"  # clients are not publicly accessible by default
    verbose: bool = True  # whether or not TSP message should be printed
    wallet_url: str = "sqlite://wallet.sqlite"
    wallet_password: str = "unsecure"
    use_webvh: bool = True


class TmcpManager(TransportManager):
    def __init__(self, alias: str = "tmcp", **tmcp_settings: Any):
        self.settings = TmcpSettings(**tmcp_settings)
        self.wallet = tsp.SecureStore(
            self.settings.wallet_url,
            self.settings.wallet_password,
        )
        self.did = self._init_identity(alias)

    def _init_identity(self, alias: str) -> str:
        # Store did:webvh under separate alias to avoid overwriting the did:web
        wallet_alias = alias + "vh" if self.settings.use_webvh else ""
        did = self.wallet.resolve_alias(wallet_alias)

        if did is not None:
            # Verify DID is of correct type
            if (self.settings.use_webvh and not did.startswith("did:webvh:")) or (
                not self.settings.use_webvh and not did.startswith("did:web:")
            ):
                did = None
            else:
                # Verify DID still exists
                try:
                    endpoint = self.wallet.verify_vid(did)
                    if endpoint == self.settings.transport:
                        print("Using existing DID: " + did)
                        return did
                except Exception as e:
                    if 'ResolveVid("Not found")' in e.args[0] or "kind: Status(404)" in e.args[0]:
                        did = None  # create a new DID
                    else:
                        raise e

        is_new_did = False
        # TODO: update existing did:webvh properly (our webvh bindings don't support updating transport info yet)
        if did is None or self.settings.use_webvh:
            # Initialize new TSP identity
            did_format = self.settings.did_webvh_format if self.settings.use_webvh else self.settings.did_web_format
            did = did_format.format(name=f"{alias.replace(' ', '')}-{uuid4()}"[:63])
            is_new_did = True

        history = None
        if self.settings.use_webvh:
            (identity, history) = tsp.OwnedVid.new_did_webvh(did, self.settings.transport)
        else:
            identity = tsp.OwnedVid.bind(did, self.settings.transport)

        did = identity.identifier()  # get generate DID (may be different from the formatted DID, e.g. for did:webvh)

        # Publish DID
        post_or_put = httpx.post if is_new_did else httpx.put
        post_or_put(
            self.settings.did_publish_url,
            content=identity.json().encode(),
            headers={"Content-type": "application/json"},
        ).raise_for_status()

        if history:
            # Publish did:webvh history
            post_or_put(
                self.settings.did_publish_history_url.format(did=did),
                content=history.encode(),
                headers={"Content-type": "application/json"},
            ).raise_for_status()

        print("Published client DID:", did)

        self.wallet.add_private_vid(identity, wallet_alias)

        return did

    def get_client_hook(self, url_or_id: str):
        return TmcpTransportHook(self.wallet, self.did, url_or_id, self.settings.verbose)

    def get_server_hook(self, request: Request):
        user_did = request.query_params.get("did")
        if user_did is None:
            logger.warning("Received request without user did")
            raise Exception("did is required")
        return TmcpTransportHook(self.wallet, self.did, user_did, self.settings.verbose)

    def retrieve_from_wallet(self, key: str) -> bytes:
        return self.wallet.get_kv(key)


class TmcpTransportHook(TransportHook):
    def __init__(self, wallet: tsp.SecureStore, my_did: str, other_did: str, verbose: bool = True):
        print("init tmcp hook")
        self.wallet = wallet
        self.my_did = my_did
        self.other_did = other_did
        self.other_endpoint = self.wallet.verify_vid(other_did)
        self.verbose = verbose

    def get_endpoint(self):
        print("tmcp get_endpoint:", self.other_endpoint)
        c = "&" if "?" in self.other_endpoint else "?"
        return self.other_endpoint + c + "did=" + self.my_did

    def open_message(self, data: str):
        tsp_message = base64.urlsafe_b64decode(data)

        # Open TSP message
        if self.verbose:
            logger.info("Received TSP message:")
            print(tsp.color_print(tsp_message))

        (sender, receiver) = self.wallet.get_sender_receiver(tsp_message)
        if receiver != self.my_did:
            logger.warning(f"Received message intended for: {receiver} (expected {self.my_did})")
        if sender != self.other_did:
            logger.warning(f"Received message intended for: {sender} (expected {self.other_did})")

        opened_message = self.wallet.open_message(tsp_message)
        if self.verbose:
            logger.info(f"Opened TSP message: {opened_message}")

        if not isinstance(opened_message, tsp.GenericMessage):
            raise Exception("Received not generic message", opened_message)

        return opened_message.message.decode()

    def seal_message(self, data: str):
        message_data = data.encode()

        # Seal TSP message
        if self.verbose:
            logger.info(
                f"Encoding TSP message: {
                    tsp.GenericMessage(
                        sender=self.my_did,
                        receiver=self.other_did,
                        message=message_data,
                        nonconfidential_data=None,
                        crypto_type='',
                        signature_type='',
                    )
                }"
            )

        _, tsp_message = self.wallet.seal_message(self.my_did, self.other_did, message_data)

        if self.verbose:
            logger.info("Sending TSP message:")
            print(tsp.color_print(tsp_message))

        return base64.urlsafe_b64encode(tsp_message).decode()
