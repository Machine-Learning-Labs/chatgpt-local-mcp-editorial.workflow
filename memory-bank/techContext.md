# Tech context

| Piece | Version / choice |
|---|---|
| Gateway | Python ≥ 3.11 (image `python:3.12-slim`), starlette, uvicorn, httpx, python-multipart |
| Dev | uv, pytest + pytest-cov, ruff, shellcheck |
| Scribus MCP | `scribus-mcp==1.3.1` from PyPI with **`mcp>=1.10,<2`** pinned (1.3.1 breaks on mcp 2.x) |
| Scribus | Debian trixie package (1.6.3) in the container; the owner's machine has 1.6.5 |
| Tunnel | `ngrok/ngrok:latest` image, v2 config file generated inline (`web_addr 0.0.0.0:4040`) |
| Engines | docker compose v2, podman-compose 1.5 (tested), podman compose |

## Environment of the original author

Linux, podman 5.7 rootless with podman-compose 1.5.0 (no Docker), ngrok CLI 3.39 with an authtoken already configured, Scribus 1.6.5, and uv 0.10.

## Constraints

- scribus-mcp's FastMCP enforces DNS-rebinding protection: it answers 421 on a non-localhost `Host` and 403 on a foreign `Origin`.
- Free ngrok shows a browser interstitial page on the first visit to `/authorize`.
- `host-gateway` in `extra_hosts` needs Docker 20.10+ or Podman 5+.
