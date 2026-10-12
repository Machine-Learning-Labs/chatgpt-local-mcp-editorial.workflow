# Connecting clients

Every client uses the same URL, `https://<NGROK_DOMAIN>/mcp`. `make url` prints it.

## OAuth clients (recommended)

These clients only need the URL. They register themselves, open the consent page and refresh tokens on their own. Approve the request with `GATEWAY_OWNER_PASSWORD` from `.env`.

| Client | Where |
|---|---|
| claude.ai / Claude Desktop | Settings → Connectors → *Add custom connector*, then paste the URL |
| Claude Code | `claude mcp add --transport http scribus https://<domain>/mcp`, then run `/mcp` to authenticate |
| ChatGPT (developer mode) | Settings → Connectors → *Create*, with the URL and OAuth authentication |
| MCP Inspector | `npx @modelcontextprotocol/inspector`, Streamable HTTP transport, the URL, then *Open Auth Settings* → *Quick OAuth Flow* |

## Static token

`make token` prints a token together with ready-made snippets. `bin/token --quiet --ttl 86400` prints only the token. That's handy for scripts and CI.

```bash
claude mcp add --transport http scribus https://<domain>/mcp \
  --header "Authorization: Bearer $(bin/token --quiet)"
```

When the token expires (after `ACCESS_TOKEN_TTL`), mint a new one. Static tokens can't be refreshed.

## Paths

In container mode, scribus-mcp sees your `WORKSPACE_DIR` as `/workspace`. Ask for example: *"open /workspace/flyer.sla and export it to /workspace/flyer.pdf"*. In host mode, use your real local paths.
