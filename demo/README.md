# TMCP Demo

## Run the server
In the `server` directory, run the demo TMCP server with:
```
uv run server.py
```
This hosts the demo TMCP server locally. When it starts, it prints its own DID. This DID will be either a newly generated DID published on <https://did.teaspoon.world/>, or a previously saved DID from the wallet using the server's name as an alias.

## Run the client
For the client, you will need an Anthropic API key, which you can get [here](https://console.anthropic.com/settings/keys). In the `client` directory, create a `.env` file with your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-api03-put-your-private-key-here
```

Then, run the demo TMCP client in the `client` directory with:
```
uv run client.py did:web:did.teaspoon.world:the:servers:did:here
```
It should list the available MCP tools from the demo MCP server. You should be able to enter a query to prompt it to use these tools.

The server will print the encoded and decoded MCP over TSP messages that it sends and receives.
