# Connect your AI client

> Six configurations for adding Swiggy MCP to Claude Desktop, ChatGPT, Cursor, VS Code, Windsurf, and any MCP-compatible client.

Pick your AI client. Paste the config. Restart. Complete OAuth. You're done.

#### Claude Desktop

Edit Claude Desktop's config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add all four Swiggy servers:

```json
{
  "mcpServers": {
    "swiggy-food": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.swiggy.com/food"]
    },
    "swiggy-instamart": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.swiggy.com/im"]
    },
    "swiggy-dineout": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.swiggy.com/dineout"]
    },
    "swiggy-scenes": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.swiggy.com/scenes"]
    }
  }
}
```

Restart Claude Desktop. On first launch a browser window opens - complete OAuth (phone + OTP). Claude confirms the connection in the bottom-left status bar.

Try: *"Search Instamart for bananas near my saved home address."*

Only need one server? Keep just that entry in `mcpServers`.

#### ChatGPT

ChatGPT supports remote MCP servers in **Developer Mode** on Business, Enterprise, and Edu tiers (gradually rolling out more broadly - check OpenAI's docs).

1. Settings → **Developer Mode** → **MCP Connectors**
2. Click **Add server**
3. Paste one of:
   - `https://mcp.swiggy.com/food`
   - `https://mcp.swiggy.com/im`
   - `https://mcp.swiggy.com/dineout`
   - `https://mcp.swiggy.com/scenes`
4. Complete OAuth in the browser when prompted

Enable the Swiggy connector from the tools menu in a new chat.

Try: *"Book a table for 4 at an Italian restaurant in Koramangala for Friday 8pm."*

Some write-side tools (placing orders, checkouts) require explicit per-call confirmation in the ChatGPT UI - a ChatGPT-side safety default.

#### Cursor

Edit (or create) `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "swiggy-food": {
      "url": "https://mcp.swiggy.com/food"
    },
    "swiggy-instamart": {
      "url": "https://mcp.swiggy.com/im"
    },
    "swiggy-dineout": {
      "url": "https://mcp.swiggy.com/dineout"
    },
    "swiggy-scenes": {
      "url": "https://mcp.swiggy.com/scenes"
    }
  }
}
```

Open Cursor → `Cmd/Ctrl+Shift+P` → **MCP: Reload Servers**. Complete OAuth in the browser.

In Cursor Chat or Composer, mention Swiggy by name:

> **Note**
>
> *"Use Swiggy Food to find a restaurant that serves pasta near my address."*

For per-project scoping, create `<repo>/.cursor/mcp.json`.

#### VS Code

**Via GitHub Copilot (Agent mode)**:

Open `settings.json` (`Cmd/Ctrl+,` → "Open Settings (JSON)"):

```json
{
  "github.copilot.chat.mcp.servers": {
    "swiggy-food": { "url": "https://mcp.swiggy.com/food" },
    "swiggy-instamart": { "url": "https://mcp.swiggy.com/im" },
    "swiggy-dineout": { "url": "https://mcp.swiggy.com/dineout" },
    "swiggy-scenes": { "url": "https://mcp.swiggy.com/scenes" }
  }
}
```

Reload window. Open Copilot Chat → switch to Agent mode → complete OAuth.

Verify in Agent mode: *"What Swiggy Food tools are available?"*

Project-level `.vscode/mcp.json` takes precedence over user settings.

Logs: View → Output → GitHub Copilot Chat → MCP.

#### Windsurf

Windsurf supports MCP via its Cascade interface.

1. Open **Windsurf Settings** → **MCP**
2. Click **Add Server**
3. Paste a Swiggy endpoint (e.g. `https://mcp.swiggy.com/food`)
4. Complete OAuth

Alternatively, edit `~/.codeium/windsurf/mcp_config.json` directly:

```json
{
  "mcpServers": {
    "swiggy-food": { "url": "https://mcp.swiggy.com/food" },
    "swiggy-instamart": { "url": "https://mcp.swiggy.com/im" },
    "swiggy-dineout": { "url": "https://mcp.swiggy.com/dineout" },
    "swiggy-scenes": { "url": "https://mcp.swiggy.com/scenes" }
  }
}
```

Reload Cascade to pick up the new servers.

#### Any MCP client

Swiggy MCP speaks the standard [Model Context Protocol](https://modelcontextprotocol.io) over streamable HTTP. Any MCP-compatible client with remote server support works.

| Setting | Value |
| --- | --- |
| Transport | Streamable HTTP |
| URL | `https://mcp.swiggy.com/food` (or `/im`, `/dineout`, `/scenes`) |
| Authentication | OAuth 2.1 with PKCE |

If your client supports remote OAuth servers (the spec's dynamic client registration flow is still firming up across vendors), point it at the URL above; it will discover the `/auth/authorize` and `/auth/token` endpoints via the OAuth metadata document at `https://mcp.swiggy.com/.well-known/oauth-authorization-server`.

If you're building a **new** MCP client and need your custom redirect scheme allowlisted, email [builders@swiggy.in](mailto:builders@swiggy.in).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| OAuth flow loops | Kill the client fully and retry; PKCE verifier is regenerated each attempt |
| Tools not showing up | After config changes, reload the MCP server list in your client |
| 401 after a few days | Session expired. Re-connect / complete OAuth again |
| "Tool not found" | Check you're pointed at the right server URL (`/food` vs `/im` vs `/dineout` vs `/scenes`) |
| Only want Food | Keep only the `swiggy-food` entry in your config |

## Privacy

- Your AI client provider (Anthropic, OpenAI, etc.) receives your chat + tool results per their privacy policy.
- Swiggy's stance on data handling: [data-and-compliance](/docs/operate/data-and-compliance.md).
- You remain in control - any action is visible (and reversible) in the Swiggy app.
