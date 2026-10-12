# scribus-mcp in this stack

Upstream project: <https://github.com/caewa/scribus-mcp> (MIT), installed from PyPI as `scribus-mcp`. The version is pinned with `SCRIBUS_MCP_VERSION`, and the default is `1.3.1`. It provides about 170 tools: documents, pages, frames, text, images, styles, colours, export and more.

It drives Scribus in one of two ways:

- **Headless.** It runs one `scribus -g -py …` process per call. This is what the container uses (`SCRIBUS_MCP_USE_XVFB=1`).
- **Interactive.** It talks over TCP to a bridge script running inside an **open Scribus window**. This is only useful in host mode.

## Container mode (default)

The image is Debian trixie with Scribus 1.6.x, Xvfb, Ghostscript, DejaVu and Liberation fonts, and scribus-mcp in `/opt/venv`. It's started as `scribus-mcp --http 0.0.0.0:8000`. The service has no published port; only the gateway can reach it.

- The documents folder is `WORKSPACE_DIR`, mounted at `/workspace`. `bin/` runs the container as your uid:gid on Docker, and as root on rootless Podman (which maps to your user), so the files it writes belong to you.
- Some tools need Scribus 1.7, for example `create_qr_code_block`. Debian ships 1.6, so those tools report themselves as unavailable.
- To upgrade scribus-mcp, change `SCRIBUS_MCP_VERSION` and run `make up`. The image tag follows the version.

## Host mode (your desktop Scribus)

```bash
# .env
MCP_MODE=host
HOST_MCP_PORT=8765

make host-mcp   # terminal 1: uvx scribus-mcp --http 0.0.0.0:8765
make up         # terminal 2: gateway + ngrok only
```

To let scribus-mcp drive the Scribus window you have open, load its bridge inside Scribus:

```bash
uvx --from scribus-mcp==1.3.1 --with 'mcp<2' scribus-mcp --print-bridge-path
# Scribus → Script → Execute Script… → choose that .spy file
```

The bridge needs a Qt binding in the Python that Scribus uses, for example `sudo apt install python3-pyqt6` or `python3-pyside2`. If the bridge isn't reachable, scribus-mcp falls back to headless mode.

On Linux, dismiss Scribus's *New Document* wizard the first time it opens, because it blocks scripts.

> scribus-mcp itself has no authentication. `HOST_MCP_BIND=0.0.0.0` lets the containers reach it, but it also exposes it to your LAN. Firewall `HOST_MCP_PORT`. On Docker Desktop and on rootless Podman with pasta, `HOST_MCP_BIND=127.0.0.1` usually works too.

## Known upstream quirks (handled for you)

| Quirk | Workaround |
|---|---|
| 1.3.x imports `mcp.server.fastmcp`, which was removed in `mcp` 2.x | The image and `bin/host-mcp` install `mcp>=1.10,<2` |
| `--http 0.0.0.0` still runs FastMCP's DNS-rebinding guard, which answers 421 for `Host: scribus-mcp` | The gateway sends `Host: localhost:<port>` (`UPSTREAM_HOST_HEADER`) |
| A foreign `Origin` header gets a 403 | The gateway doesn't forward `Origin` |
| `run_script` runs arbitrary code | It's disabled unless you set `SCRIBUS_MCP_RUN_SCRIPT=1` |
