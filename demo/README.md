# TMCP Demo

This TMCP demo shows how an MCP client and an MCP server can securely communicate over TSP.

## Run the server

In the `server` directory, run the demo TMCP server with:

```
uv run server.py
```

This hosts the demo TMCP server locally. When it starts, it prints its own DID. This DID will be either a newly generated DID published on <https://did.teaspoon.world/>, or a previously saved DID from the wallet using the server's name as an alias.

The TMCP supports two kinds of transport:

- Server-Sent Events (`sse`)
- WebSockets (`ws`)

The server uses SSE by default. If you want to use another kind of transport you can specify this as the second argument of `server.py`. For example, to use WebSockets you can do:

```
uv run server.py ws
```

The transport information is stored in the server's DID, so if you restart it with a different transport type, a new DID will be generated. The client will automatically determine the transport type to use based on the server's DID.

## Run the client

For the client, you will need an Anthropic API key, which you can get [here](https://console.anthropic.com/settings/keys). In the `client` directory, create a `.env` file with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-api03-put-your-private-key-here
```

Then, run the demo TMCP client in the `client` directory with:

```bash
# Replace <server-did> with the DID of the target server
uv run client.py <server-did>
```

It should list the available MCP tools from the demo MCP server. You should be able to enter a query to prompt it to use these tools.

The server will print the encoded and decoded MCP over TSP messages that it sends and receives.

## Using other MCP servers

If you want to use TMCP with other existing MCP servers, some minor modification is required.

First, update the MCP Python SDK dependency to our fork with the following command:

```
uv add git+https://github.com/openwallet-foundation-labs/mcp-over-tsp-python
```

Then, if the server uses the `FastMCP` server, replace it with our modified `TMCP` server. If the server implements its own MCP server, make sure it uses one of the transport clients that is also supported by TMCP (e.g. SSE or WebSockets). If you want to use WebSockets, make sure to enable the `ws` feature of the MCP dependency, you can do this by using `--extra ws` when adding the TMCP fork.

The `server-duckduckgo`, `server-git`, `server-gmail`, and the `server-sqlite` directories contain examples of such modified MCP servers. You can interact with these example servers using our same TMCP demo client.

## Using the fast-agent client

Our demo client only supports basic **MCP tools** and lacks support for other features of MCP such as resources and sampling. To try out these other MCP features, you can use a more advanced MCP client, like [fast-agent](https://github.com/evalstate/fast-agent). In the `client-fast-agent` folder there is a fork of fast-agent which has been modified to support TMCP.

First, set your Anthropic API key in `fastagent.secrets.yaml`:

```yaml
anthropic:
  api_key: "sk-ant-api03-your-key-here"
```

Then, you can start an interactive session with a TMCP server with the following command (type `exit` to exit the interactive session):

```
uv run fast-agent go --url did:your_server_did_here
```

Alternatively, you can put the server you want to connect with in `fastagent.config.yaml` and start fast-agent using the servers name from the config:

```
uv run fast-agent go --servers Demo
```

### Exploring more MCP features

To try out **MCP resources**, we have created a demo script `test-resource.py`, which is intended to work with our demo server in the `server` directory. After running the server, put the server's DID in the client's `fastagent.config.yaml`, and then run:

```
uv run test-resource.py
```

The `fastagent.config.yaml` config file also contains an example **MCP root**. Using the demo server's `show_roots` tool you can see that the root configuration is shared with the server. This tool may return an error if no roots are configured. MCP roots don't automatically share any data or provide any security guarantees; they only provide a way to share information with the server about what roots the server may use. How these roots are used in practice depends entirely on the server.

Fast-agent also supports **MCP prompts** with the `/prompts` command in the interactive session, and it supports **MCP sampling** and **eliciting** (see the `favorite_animal_guesser` tool in our demo server).
