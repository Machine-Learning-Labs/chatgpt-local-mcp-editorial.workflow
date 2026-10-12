# Project brief

**editorial.workflow** publishes a local Scribus MCP server to remote AI clients over HTTPS, protected by OAuth 2.1, with a single command (`make up`). It's an open source project (MIT) that runs under Docker or Podman.

## Goals

- Start everything with one command: gateway, Scribus MCP, ngrok, plus printing the URL and a token.
- Be compliant with the MCP authorization spec, so that claude.ai, Claude Code, ChatGPT and Inspector can connect with nothing more than the URL.
- Reuse the existing open source Scribus MCP, [caewa/scribus-mcp](https://github.com/caewa/scribus-mcp). Our own code is limited to the OAuth bridge, which is tested.
- Ship operational scripts in `bin/` (setup, check, up, token, rotate…).

## Non-goals

- Writing or forking a Scribus MCP.
- Multi-user identity, an external IdP, or a database.
- Hosting in production or the cloud. This is a tool you run on your own machine.
