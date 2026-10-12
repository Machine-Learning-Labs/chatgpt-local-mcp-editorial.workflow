# Product context

## Problem

Scribus has a capable MCP (caewa/scribus-mcp), but it speaks stdio or plain localhost HTTP with no authentication. Remote clients such as claude.ai connectors or ChatGPT need a public HTTPS endpoint that implements OAuth 2.1 with DCR and PKCE. Exposing the raw MCP through ngrok would give anyone with the URL control of Scribus, including `run_script` if it's enabled.

## Users

- The owner, a single person who runs Scribus locally and wants their AI assistants to lay out, edit and export documents.
- Contributors who want a reusable "local MCP → OAuth → tunnel" template.

## Experience

1. `make up` asks nothing on the first run. It generates secrets and imports the ngrok token.
2. It prints the URL and a token.
3. Paste the URL into the client. The browser shows a consent page. Enter the owner password, and the client is connected.
4. `make check-live` tells you whether every hop works.
