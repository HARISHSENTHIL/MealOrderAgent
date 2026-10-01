# Build an agent

> Working code to wire Swiggy MCP into the framework you already use.

Swiggy MCP speaks standard streamable HTTP. Every major agent framework in 2026 has first-class MCP support. Pick your framework, paste the connector, give your agent access to 35 Swiggy tools.

Swiggy MCP is OAuth 2.1 + PKCE - there is no static API key. SDK support for the flow splits into two camps:

- **Native `authProvider` support** (raw MCP TS / Python SDKs, OpenAI Agents JS, Vercel AI SDK 6, Mastra) - pass an OAuth client provider and the SDK runs PKCE against Swiggy's `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` automatically.
- **Bearer-header only** (OpenAI Agents Python, LangChain MCP adapters, PydanticAI, CrewAI, Google ADK, Anthropic hosted MCP connector) - the SDK has no OAuth hook, so you obtain an access token via the [Authenticate](/docs/start/authenticate.md) flow and forward it as `Authorization: Bearer <token>`.

The snippets below assume:

- `swiggyOAuthProvider` / `swiggy_oauth_provider` - your implementation of the MCP SDK's `OAuthClientProvider` interface, wrapping the [Authenticate](/docs/start/authenticate.md) flow. The Mastra tab shows a ready-made one via `MCPOAuthClientProvider`.
- `getSwiggyAccessToken()` - your helper that runs the [Authenticate](/docs/start/authenticate.md) flow and returns a fresh Bearer token. Re-run on 401.

Refresh tokens are not yet wired in v1.0; treat the 5-day access token as the full session and re-run authorization on 401.

#### OpenAI Agents SDK

```ts

const agent = new Agent({
  name: "FoodOrderingAgent",
  instructions: "Help users order food on Swiggy. Always call get_addresses first.",
  mcpServers: [swiggyFood],
});

await swiggyFood.connect();
const result = await Runner.run(agent, "Order biryani to my home address.");
console.log(result.finalOutput);
```

Python (the `agents` SDK doesn't expose an OAuth hook today - pass a Bearer token in headers):

```python

const swiggyToken = await getSwiggyAccessToken(); // your OAuth helper

const response = await anthropic.beta.messages.create({
  model: "claude-opus-4-7",
  max_tokens: 1024,
  betas: ["mcp-client-2025-11-20"],
  mcp_servers: [
    {
      type: "url",
      url: "https://mcp.swiggy.com/food",
      name: "swiggy-food",
      authorization_token: swiggyToken,
    },
    {
      type: "url",
      url: "https://mcp.swiggy.com/im",
      name: "swiggy-instamart",
      authorization_token: swiggyToken,
    },
  ],
  tools: [
    { type: "mcp_toolset", mcp_server_name: "swiggy-food" },
    { type: "mcp_toolset", mcp_server_name: "swiggy-instamart" },
  ],
  messages: [
    { role: "user", content: "Order biryani and 2L milk to my home address." },
  ],
});
```

Claude reads the tool catalogues from each server and picks the right tools automatically.

#### LangGraph

Use the official `langchain-mcp-adapters` to load Swiggy tools into any LangGraph agent.

`langchain-mcp-adapters` only supports header-based auth in its per-server config - fetch a token via [Authenticate](/docs/start/authenticate.md) first.

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

token = await get_swiggy_access_token()  # your OAuth helper

client = MultiServerMCPClient({
    "swiggy-food": {
        "url": "https://mcp.swiggy.com/food",
        "transport": "streamable_http",
        "headers": {"Authorization": f"Bearer {token}"},
    },
})

tools = await client.get_tools()

agent = create_react_agent(ChatOpenAI(model="gpt-4o"), tools)

result = await agent.ainvoke({
    "messages": [{"role": "user", "content": "Order biryani to my home address."}],
})
```

#### Vercel AI SDK

Vercel AI SDK 6 ships `createMCPClient` with first-class streamable-HTTP support.

```ts

const tools = await mcp.tools();

const { text } = await generateText({
  model: anthropic("claude-opus-4-7"),
  tools,
  prompt: "Order biryani to my home address.",
});

await mcp.close();
```

#### Mastra

Mastra supports MCP both as client (consuming) and server (exposing agents). Here's client usage:

```ts

const swiggyOAuth = new MCPOAuthClientProvider({
  serverUrl: "https://mcp.swiggy.com/food",
  redirectUrl: "http://localhost:3000/oauth/callback",
  clientMetadata: {
    client_name: "my-mastra-agent",
    redirect_uris: ["http://localhost:3000/oauth/callback"],
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
  },
});

const mcp = new MCPClient({
  servers: {
    "swiggy-food": {
      url: new URL("https://mcp.swiggy.com/food"),
      authProvider: swiggyOAuth,
    },
  },
});

const agent = new Agent({
  name: "FoodAgent",
  model: anthropic("claude-opus-4-7"),
  tools: await mcp.getTools(),
});

const result = await agent.generate("Order biryani to my home address.");
```

#### PydanticAI

PydanticAI doesn't run the OAuth flow for you - fetch a token via [Authenticate](/docs/start/authenticate.md) and pass it as a header.

```python

const client = new Client({ name: "my-agent", version: "1.0.0" });
await client.connect(transport);

const { tools } = await client.listTools();
const result = await client.callTool({
  name: "search_restaurants",
  arguments: { addressId: "addr_01HXYZ", query: "biryani" },
});
```

Python:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    "https://mcp.swiggy.com/food",
    auth=my_swiggy_oauth_provider,  # implements OAuthClientProvider
) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(
            "search_restaurants",
            arguments={"addressId": "addr_01HXYZ", "query": "biryani"},
        )
```

## Handling expired tokens

Access tokens live 5 days. When a call returns 401 (or JSON-RPC `-32001`), re-run the OAuth flow and retry. Most frameworks expose a hook for this; for raw clients:

```ts
async function callWithReauth<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e: any) {
    if (e?.status === 401) {
      await reAuthenticate();
      return fn();
    }
    throw e;
  }
}
```

See [Authenticate](/docs/start/authenticate.md) for the full OAuth walkthrough.

## Wire more than one Swiggy server

Each server is independent - connect multiple if your agent needs to span domains:

```ts
mcpServers: [
  { url: "https://mcp.swiggy.com/food" },
  { url: "https://mcp.swiggy.com/im" },
  { url: "https://mcp.swiggy.com/dineout" },
  { url: "https://mcp.swiggy.com/scenes" },
]
```

Tool names are unique across servers, so your agent can dispatch across all 66 public tools without conflict.

## Where to go next

- [Recipes](/docs/build.md) - end-to-end journeys for food, grocery, dineout, and combined flows.
- [Agent patterns](/docs/build/agent-patterns/voice-vs-chat.md) - voice vs chat response shaping, multi-turn state.
- [Reference](/docs/reference.md) - every tool, every parameter.
- [Ship to production](/docs/build/ship-to-production.md) - retries, observability, go-live checklist.
