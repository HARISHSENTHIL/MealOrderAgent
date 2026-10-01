# Developer quickstart

> Zero to first successful Swiggy tool call, self-serve.

This is the self-serve path. You'll ship working agent code that calls a Swiggy MCP tool against a staging endpoint. You will move through account access, framework install, OAuth, and a first tool call.

> **Note**
>
> You don't need approval to start - steps 1 through 5 below run on `http://localhost`, free. You only [apply for access](/access) when you're ready to hit production endpoints. Tip: fill out the form while you build, and include a demo video to speed up review.

## 1. Understand what you're building

Every Swiggy MCP tool call goes through the same loop:

1. Your agent picks a tool from the server's catalogue (e.g. `search_restaurants`).
2. The MCP client in your agent framework sends a JSON-RPC call to `mcp.swiggy.com/{server}`.
3. The server authenticates the session, runs the tool, returns `{ success, data }`.
4. Your agent reads the result and decides what to call next.

Four servers, independent per URL: Food (`/food`), Instamart (`/im`), Dineout (`/dineout`), Scenes (`/scenes`).

## 2. Apply for production access (when you're ready)

You don't need this to start - everything below works on `http://localhost` without approval. Apply only when you want to take your integration live. Production access is reviewed today, so record a short video of your agent flow working end-to-end and include the link with your application; it dramatically speeds up review.

Apply at [/access](/access) with:

- Integration name and organization
- Redirect URIs for OAuth (exact-match, HTTPS - `http://localhost` allowed for dev)
- Which servers you'll call - any of `food`, `instamart`, `dineout`, `scenes` (v1 scopes are `mcp:tools`, `mcp:resources`, `mcp:prompts`)
- Expected volume and use case
- **A demo video link** (Loom, Drive, YouTube unlisted) - or email it to `builders@swiggy.in`

You'll get staging access; production follows once your staging integration is green. Your MCP client registers itself via Dynamic Client Registration - no client identifier to apply for. See [Access](/docs/operate/access.md) for the full flow.

## 3. Pick a framework

Any MCP-compatible framework works. Pick what you already use; if you're starting fresh, OpenAI Agents SDK and Vercel AI SDK have the lowest-friction MCP story in 2026.

Supported frameworks (recipes in [Build an agent](/docs/start/developer/build-an-agent.md)):

- OpenAI Agents SDK (TypeScript + Python)
- Anthropic SDK - native MCP connector
- LangGraph / LangChain (via `langchain-mcp-adapters`)
- Vercel AI SDK 6 (`experimental_createMCPClient`)
- Mastra, PydanticAI, CrewAI, Google ADK
- Raw MCP client (`@modelcontextprotocol/sdk` or `mcp` Python package)

## 4. Complete OAuth

OAuth 2.1 with PKCE. See [Authenticate](/docs/start/authenticate.md) for the full endpoint walkthrough. Most frameworks handle this for you - you paste the auth URL into your config, a browser window opens for phone + OTP, and you're back.

## 5. Make your first tool call

Follow the framework recipe at [Build an agent](/docs/start/developer/build-an-agent.md). The minimal first call:

```ts
const result = await client.callTool({
  name: "get_addresses",
  arguments: {},
});
```

If you see a user's saved addresses, you're wired up. Now try `search_restaurants` with an `addressId` from that response. From there, the world is yours.

## 6. Build something real

Pick a [recipe](/docs/build.md):

- [Order food end-to-end](/docs/build/recipes/order-food.md) - 7 tools, full journey, COD payment.
- [Order groceries end-to-end](/docs/build/recipes/order-groceries.md) - Instamart cart + checkout.
- [Book a table](/docs/build/recipes/book-a-table.md) - Dineout availability + reservation.
- [Combined: plan my evening](/docs/build/recipes/combined.md) - food + dineout in one agent turn.

## What's next

- [Build an agent](/docs/start/developer/build-an-agent.md) - per-framework recipes with working code.
- [Ship to production](/docs/build/ship-to-production.md) - retries, observability, go-live checklist.
