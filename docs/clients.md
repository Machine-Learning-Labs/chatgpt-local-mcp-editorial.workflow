# Connecting clients

There are two connectors on the same domain, plus an optional third. Run `make url` to print them:

- **Scribus editor:** `https://<NGROK_DOMAIN>/editor/mcp`
- **Editorial Assets:** `https://<NGROK_DOMAIN>/assets/mcp`
- **DesignCraft** (with `DESIGNCRAFT_ENABLED=true`): `https://<NGROK_DOMAIN>/designcraft/mcp`

## ChatGPT (plugin / custom MCP server)

| Field | Value |
|---|---|
| Server URL | `https://<domain>/editor/mcp` |
| Authentication | OAuth |
| Registration method | **Dynamic Client Registration (DCR)**. ChatGPT's callback (`https://chatgpt.com/…`) is allowed by `GATEWAY_ALLOWED_REDIRECTS`. |
| Token endpoint auth method | `none` |
| Default scopes | `mcp` |
| Base scopes | leave empty |
| OIDC | **off**. The gateway isn't an OpenID provider and doesn't publish `openid-configuration`. |
| Endpoints | auto-discovered: `/authorize`, `/token`, `/register`, resource `…/editor/mcp` |

The gateway supports RFC 9207 (`iss` in the authorization response), so ChatGPT can use its stable redirect URI. When you click *Create*, the ngrok interstitial shows up first (free plan only; click *Visit Site*). Then the consent page appears: enter `GATEWAY_OWNER_PASSWORD` and approve.

Every tool carries `securitySchemes: [{type: oauth2, scopes: [mcp]}]`. Tools hidden by the policy (`run_script`, the JavaScript tools and font installation) don't appear in the list.

## ChatGPT: second connector for images

Add a second custom MCP server with the same settings, changing:

- **Name:** Editorial Assets
- **Server URL:** `https://<domain>/assets/mcp`

It has its own OAuth flow and its own token. Usage and the prompt recipe are in [assets-connector.md](assets-connector.md).

## ChatGPT: third connector for DesignCraft

With `DESIGNCRAFT_ENABLED=true` (host mode), add a third custom MCP server with the same settings, changing:

- **Name:** DesignCraft
- **Server URL:** `https://<domain>/designcraft/mcp`

It has its own OAuth flow and its own token, and only the reviewed tools show up. Details in [designcraft.md](designcraft.md). `bin/token --designcraft` mints a static token for it.

## Other OAuth clients

| Client | Where |
|---|---|
| claude.ai / Claude Desktop | Settings → Connectors → *Add custom connector*, then paste the URL |
| Claude Code | `claude mcp add --transport http scribus https://<domain>/editor/mcp`, then run `/mcp` to authenticate |
| MCP Inspector | `npx @modelcontextprotocol/inspector`, Streamable HTTP transport, the URL, then *Quick OAuth Flow*. Its `http://localhost:6274` callback is allowed. |

A client with a different callback needs its redirect URI prefix added to `GATEWAY_ALLOWED_REDIRECTS`.

## Static token

`make token` prints a token together with ready-made snippets. `bin/token --quiet --ttl 86400` prints only the token. Each token is **bound to one URL**: the public one by default, or `http://127.0.0.1:<port>` with `--local`.

```bash
claude mcp add --transport http scribus https://<domain>/editor/mcp \
  --header "Authorization: Bearer $(bin/token --quiet)"
```

## Paths in prompts

Always use absolute paths under `EDITORIAL_ROOT`, for example *"save as ~/Editorial/flyer.sla"* or *"load ~/Editorial/libro/assets/cover.png"* with `~` spelled out as your home directory. The MCP's `initialize` instructions tell the model the same thing. The gateway refuses anything outside that folder.
