# Tech context

| Piece | Version / choice |
|---|---|
| Gateway | Python ≥ 3.11 (image `python:3.12-slim`), starlette, uvicorn, httpx, python-multipart |
| Dev | uv, pytest + pytest-cov, ruff, shellcheck |
| Scribus MCP | `scribus-mcp==1.3.1` from PyPI with **`mcp>=1.10,<2`** pinned (1.3.1 breaks on mcp 2.x) |
| Scribus | Debian trixie package (1.6.3) in the container; the owner's machine has 1.6.5 |
| Tunnel | `ngrok/ngrok:latest` image, v2 config file generated inline (`web_addr 0.0.0.0:4040`) |
| Engines | docker compose v2 (≥ 2.24 for `!reset`), podman-compose 1.5 (tested), podman compose |
| Host runtime | systemd user units (`systemd-run --user` for the transient mode), uv-managed CPython 3.12 venv |
| Bridge Qt binding | Must match Scribus's Qt and be importable by the system Python: Ubuntu Scribus 1.6 uses Qt5, so `python3-pyqt5` |

## Environment of the original author

Ubuntu 26.04.1, with podman 5.7 rootless and podman-compose 1.5.0 (no Docker). ngrok CLI 3.39 is installed with an authtoken. Scribus 1.6.5 is linked against Qt5 and the system Python 3.14, with no PyQt installed yet. uv 0.10 lives inside the conda env `scan-gpu`, but the runtime venv doesn't depend on it after it's built. `EDITORIAL_ROOT=/home/manuel/Editorial`.

## Constraints

- scribus-mcp's FastMCP enforces DNS-rebinding protection: it answers 421 on a non-localhost `Host` and 403 on a foreign `Origin`.
- Free ngrok shows a browser interstitial page on the first visit to `/authorize`.
- Host mode needs Linux (`network_mode: host`) and compose `!reset` support (docker compose ≥ 2.24, podman-compose ≥ 1.1).
