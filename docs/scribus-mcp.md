# scribus-mcp in this stack

Upstream project: <https://github.com/caewa/scribus-mcp> (MIT), installed from PyPI as `scribus-mcp`. The version is pinned with `SCRIBUS_MCP_VERSION`, and the default is `1.3.1`. It provides about 170 tools: documents, pages, frames, text, images, styles, colours, export and more. The gateway hides the dangerous ones (see [security.md](security.md)).

It drives Scribus in one of two ways:

- **Interactive.** It talks over TCP to `scribus_mcp_bridge.spy`, which runs inside an open Scribus window. The bridge listens on `127.0.0.1:<random port>` and writes `{host, port, token, pid}` to `$XDG_RUNTIME_DIR/scribus-mcp/scribus-mcp.json` (mode 0600). scribus-mcp reads that file to find the bridge.
- **Headless.** It runs one `scribus -g -py …` process per call.

`mode="auto"`, the default for every tool, uses the bridge when it's reachable and headless otherwise. `mode="interactive"` with no bridge running auto-launches a Scribus window.

## Host mode (default)

scribus-mcp runs on the host as a systemd user unit, next to your Scribus, so the bridge's loopback address and discovery file work as designed. See [host-mode.md](host-mode.md).

## Container mode

`MCP_MODE=container` runs Debian trixie with Scribus 1.6.3, Xvfb, Ghostscript and fonts, plus scribus-mcp in `/opt/venv`. It's started as `scribus-mcp --http 0.0.0.0:8000` on the internal network. This mode is headless only, which suits batch work and PDF export, and it **can't** drive your desktop Scribus.

The container's loopback isn't your host's, and the discovery file lives in your session's runtime directory. If you call it with `mode="interactive"`, it tries to launch a Scribus inside the container, which has no display, and hangs.

`EDITORIAL_ROOT` is mounted at the same path. The container runs as your uid:gid on Docker, and as root on rootless Podman (which maps to your user).

## Upstream quirks (handled for you)

| Quirk | Workaround |
|---|---|
| 1.3.x imports `mcp.server.fastmcp`, which was removed in `mcp` 2.x | The image and the host runtime install `mcp>=1.10,<2` |
| The FastMCP DNS-rebinding guard answers 421 for a non-localhost `Host`, and 403 for a foreign `Origin` | The gateway sends `Host: localhost:<port>` and drops `Origin` |
| Without a Qt binding, the bridge blocks the Scribus main thread and the GUI freezes | `python3-pyqt5` for the Qt5 build of Scribus 1.6 ([host-mode.md](host-mode.md)) |
| glama's docs recommend `python3-pyqt6` | That's wrong for Ubuntu's Scribus 1.6, which is Qt5. `bin/check` detects the right binding with `ldd`. |
| `run_script` runs arbitrary code | It's off in the runtime, and the gateway policy also refuses it |
