from starlette.requests import Request


class TransportManager:
    def get_client_hook(self, url_or_id: str):
        return TransportHook(url_or_id)

    def get_server_hook(self, request: Request):
        return TransportHook("client://")


class TransportHook:
    endpoint: str

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def get_endpoint(self):
        return self.endpoint

    def open_message(self, data: str):
        return data

    def seal_message(self, data: str):
        return data
