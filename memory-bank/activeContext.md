# Active context

_Last updated: 2026-10-12_

## Current focus

The first version is scaffolded and verified locally. It hasn't yet run as a full stack with ngrok; the owner will start it.

## Recent decisions

- **Use caewa/scribus-mcp and don't write our own MCP** (the owner asked for this on 2026-10-12). The earlier example MCP and the `mcp-proxy` stdio bridge were removed, because scribus-mcp serves Streamable HTTP natively (`--http`).
- The gateway rewrites `Host` and drops `Origin` so that scribus-mcp's FastMCP accepts the proxied calls.
- There are two modes: `container` (headless Scribus, the default) and `host` (scribus-mcp on the desktop, which can drive the open Scribus window through its bridge).

## Next steps

1. The owner runs `make up` and then `make check-live`, and connects claude.ai or Claude Code through OAuth.
2. Set `NGROK_DOMAIN` (a static domain) so client registrations survive restarts.
3. Create the GitHub remote, push, and check that CI passes.
4. Optionally contribute the `mcp<2` pin and the Host/Origin note upstream to caewa/scribus-mcp.

## Open questions

- Test interactive bridge mode against the owner's Scribus 1.6.5. It needs a Qt binding in Scribus's Python.
- Whether to support per-client token revocation, which would require state.
