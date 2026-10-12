# editorial.workflow

Publish **Scribus** to AI assistants as a remote **MCP server with OAuth 2.1**, using one command.

```bash
make up
```

That command builds and starts three containers, opens an HTTPS tunnel and prints the public MCP URL and a ready-to-use access token:

```
internet ──HTTPS──▶ ngrok ──▶ gateway :8080 ──▶ scribus-mcp :8000/mcp ──▶ Scribus (headless)
                              OAuth 2.1 AS +
                              bearer-checking proxy
```

| Service | What it is |
|---|---|
| `scribus-mcp` | [caewa/scribus-mcp](https://github.com/caewa/scribus-mcp) (PyPI `scribus-mcp`, about 170 tools) with Scribus 1.6 on Xvfb. It isn't published on the host. |
| `gateway` | The only code in this repo, `src/mcp_oauth_gateway`. It's a small OAuth 2.1 authorization server that implements the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization), plus a streaming reverse proxy that checks tokens. |
| `ngrok` | Public HTTPS URL. Your static ngrok domain keeps the URL stable. |

It works with **Docker** (`docker compose`) and **Podman** (`podman-compose` / `podman compose`), on Linux and macOS.

## Quick start

Requirements: Docker or Podman with compose, `curl`, and an [ngrok account](https://dashboard.ngrok.com) (the free tier works).

```bash
git clone <this repo> editorial.workflow && cd editorial.workflow
make up        # setup → checks → build → start → prints URL + token
```

On the first run, `bin/setup` creates `.env` (mode 600) and does three things:
- generates `GATEWAY_SECRET` (the HMAC signing key) and `GATEWAY_OWNER_PASSWORD` (the password for the consent screen),
- imports your ngrok authtoken from `ngrok config`, if you already have one,
- leaves `NGROK_DOMAIN` empty. Set it to your free static domain so the URL survives restarts.

### Connect a client

The MCP endpoint is **`https://<your-domain>/mcp`**.

- **Clients that support OAuth** (claude.ai custom connectors, Claude Desktop, ChatGPT connectors, Claude Code, MCP Inspector): give them only the URL. They discover the authorization server, register themselves dynamically and open the consent screen. Approve the request with the owner password from `.env`.
- **Clients that only take a static token:** run `make token` and pass the token as `Authorization: Bearer <token>`:

  ```bash
  claude mcp add --transport http scribus https://<your-domain>/mcp \
    --header "Authorization: Bearer $(bin/token --quiet)"
  ```

See [docs/clients.md](docs/clients.md) for each client.

## Two ways to run Scribus

| `MCP_MODE` | Where scribus-mcp runs | Use it for |
|---|---|---|
| `container` (default) | Inside the stack, with headless Scribus 1.6 and Xvfb | Batch work, PDF export, anything reproducible |
| `host` | On your machine, through `make host-mcp` | Driving **your open Scribus window** live, through scribus-mcp's bridge |

To use host mode, set `MCP_MODE=host` in `.env` and run `make host-mcp` in one terminal and `make up` in another. See [docs/scribus-mcp.md](docs/scribus-mcp.md).

## Commands

| Command | Script | What it does |
|---|---|---|
| `make up` | `bin/up` | Runs everything in one go |
| `make check` | `bin/check` | Runs preflight checks: tools, `.env`, ports, compose file |
| `make check-live` | `bin/check --live` | Runs end-to-end checks: health, OAuth metadata, 401 challenge, MCP `initialize`, both locally and through ngrok |
| `make token` | `bin/token` | Mints an access token without the browser flow |
| `make url` | `bin/url` | Prints the public MCP URL |
| `make logs s=ngrok` | `bin/compose logs` | Follows logs |
| `make rotate` | `bin/rotate` | Rotates the signing key, which revokes every token and client |
| `make host-mcp` | `bin/host-mcp` | Runs scribus-mcp on the host (host mode) |
| `make test` | `bin/test` | Runs ruff, pytest with coverage, and shellcheck |
| `make down` | | Stops the stack |

`bin/compose` runs compose with the detected engine, `.env` and the right profile. Set `COMPOSE=` in `.env` to force a specific engine.

## Configuration

All settings live in `.env`. [.env.example](.env.example) documents every variable. The most important ones:

| Variable | Default | Notes |
|---|---|---|
| `NGROK_AUTHTOKEN` | imported | Required |
| `NGROK_DOMAIN` | empty | Your static domain. Without it, the URL changes on every restart. |
| `GATEWAY_OWNER_PASSWORD` | generated | Asked on the consent screen |
| `GATEWAY_AUTO_APPROVE` | `false` | `true` skips consent, so anyone with the URL gets a token. Use it only for tests. |
| `ACCESS_TOKEN_TTL` / `REFRESH_TOKEN_TTL` | 1 h / 30 d | |
| `SCRIBUS_MCP_VERSION` | `1.3.1` | PyPI version used for the image and for host mode |
| `SCRIBUS_MCP_RUN_SCRIPT` | `0` | `1` lets any authorized client run arbitrary Python inside Scribus |
| `WORKSPACE_DIR` | `./workspace` | Mounted at `/workspace`. Use `/workspace/...` paths in prompts. |

## Security model

- The gateway is the only door. scribus-mcp has no authentication and is never published on the host. ngrok points only at the gateway.
- Authorization uses the code flow with mandatory **PKCE S256**. Codes are single-use and short-lived. Redirect URIs must be `https`, loopback `http`, or a private-use scheme.
- A human approves every new client with the owner password. Failed attempts are rate-limited (5 every 10 minutes per IP).
- Tokens are HS256-signed and stateless. `make rotate` invalidates everything at once.
- The bearer token is **stripped** before the request reaches the MCP.

Read [docs/architecture.md](docs/architecture.md) and [SECURITY.md](SECURITY.md) before you expose anything you care about.

## Development

```bash
make dev     # .venv with the gateway + test dependencies (uses uv if available)
make test    # ruff + pytest (+ shellcheck)
```

The project layout, conventions and rules for agents are in [AGENTS.md](AGENTS.md). The project's working memory is in [memory-bank/](memory-bank/).

## License

MIT. scribus-mcp, Scribus and ngrok are separate projects with their own licenses.
