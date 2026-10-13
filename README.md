# editorial.workflow

Let ChatGPT (or Claude) lay out pages **in your own Scribus**, using the images it generates, safely, with one command.

```bash
make up        # scribus-mcp service + OAuth gateway + ngrok → prints the URL and a token
make scribus   # opens your Scribus with the MCP bridge loaded
make down      # stops everything and leaves nothing behind
```

```
ChatGPT ─HTTPS─▶ ngrok ─▶ gateway (OAuth 2.1 + tool policy) ─┬─▶ /editor/mcp scribus-mcp ─▶ your Scribus window
                                                               └─▶ /assets/mcp assets ─▶ ~/Editorial/libro/assets
                          everything on 127.0.0.1 · files only inside ~/Editorial
```

| Piece | What it is |
|---|---|
| [caewa/scribus-mcp](https://github.com/caewa/scribus-mcp) | The Scribus MCP server (PyPI `scribus-mcp`, about 170 tools). We reuse it as-is. |
| `gateway` | The only code in this repo, `src/mcp_oauth_gateway`. It's an OAuth 2.1 authorization server that implements the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) and meets ChatGPT's requirements: DCR, PKCE, RFC 9207, audience binding and `securitySchemes`. It also proxies MCP traffic, checking the bearer token and enforcing a **tool policy**: a path jail in `EDITORIAL_ROOT` and a deny list for code-execution tools. |
| `assets` | Our **Editorial Assets** MCP server (`src/editorial_assets`), exposed as a second connector. It saves images generated in ChatGPT (`openai/fileParams`) or uploaded through a single-use link into `~/Editorial/libro/assets`, keeping their C2PA provenance. See [docs/assets-connector.md](docs/assets-connector.md). |
| `ngrok` | The public HTTPS URL. A static domain keeps it stable. |

## Modes

| `MCP_MODE` | scribus-mcp runs… | Scribus | Use it for |
|---|---|---|---|
| `host` (default, Linux) | as a systemd **user** unit, from its own venv, on 127.0.0.1 | **your desktop window**, live, through the bridge | Editorial work from ChatGPT |
| `container` | in the compose stack | headless Scribus 1.6 inside the container | Batch work, PDF export, CI |

Host mode is explained in [docs/host-mode.md](docs/host-mode.md), including which dependencies go where. Short version: nothing goes into conda, and one apt package, `python3-pyqt5`, goes into Scribus's own Python.

## Quick start (Ubuntu)

```bash
sudo apt install scribus python3-pyqt5   # PyQt5 keeps Scribus responsive while the bridge runs
# podman (or docker) with compose, curl, uv, and an ngrok account
make up
```

On the first run, `bin/setup` creates `.env` (mode 600) and does the following:
- generates the signing key and the consent password,
- imports your ngrok authtoken,
- sets `EDITORIAL_ROOT=~/Editorial` and creates that folder (mode 700) with an `inbox/` for images.

Then connect ChatGPT with **two connectors**, Scribus editor (`…/editor/mcp`) and Editorial Assets (`…/assets/mcp`), using DCR, scope `mcp` and OIDC off. [docs/clients.md](docs/clients.md) has the exact settings.

## Commands

| Command | What it does |
|---|---|
| `make up` / `make down` | Start or stop everything. Host mode uses a **transient** systemd unit, which `down` removes. |
| `make scribus` | Opens your Scribus with the bridge (and warns if PyQt5 is missing) |
| `make check` / `make check-live` | Preflight / end-to-end checks: OAuth, policy refusals, loopback-only listeners, the bridge, ngrok |
| `make token` / `make url` | Mint a token for static clients (`bin/token --assets` for the assets connector) / print both public URLs |
| `make service-install` / `service-enable` / `service-uninstall` | Make the scribus-mcp unit persistent (optionally at login) / remove the unit **and** its venv |
| `make service-status` / `service-logs` | Unit, runtime, endpoint and bridge state / journald logs |
| `make logs s=gateway` | Gateway logs, including the **audit log** of every tool call |
| `make rotate` | Revoke every token and client |
| `make test` | ruff, pytest (165 tests) and shellcheck |

Every command is a script in `bin/` that works with Docker or Podman. `bin/compose` picks the engine and the compose files for the mode.

## Security

Read [docs/security.md](docs/security.md) for the threat model and the controls. In short:

- OAuth with owner consent.
- Redirect allowlist.
- Audience-bound tokens.
- Path jail in `~/Editorial`.
- Code-execution tools hidden.
- Loopback-only listeners.
- Hardened containers and systemd unit.
- An audit log.
- An optional OpenAI IP allowlist.

## Development

```bash
make dev && make test
```

The layout, conventions and agent rules are in [AGENTS.md](AGENTS.md). The living project memory is in [memory-bank/](memory-bank/).

## License

MIT. scribus-mcp, Scribus and ngrok are separate projects with their own licenses.
