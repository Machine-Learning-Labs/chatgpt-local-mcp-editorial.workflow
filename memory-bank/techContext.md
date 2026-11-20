# Tech context

| Piece | Version / choice |
|---|---|
| Gateway | Python ≥ 3.11 (image `python:3.15-slim`), starlette ≥ 1.6 (1.10 locked), uvicorn, httpx, python-multipart |
| Dev | uv (lockfile + `make lock`), pytest + pytest-cov, ruff, shellcheck, pip-audit in CI |
| Scribus MCP | `scribus-mcp==1.3.1` from PyPI with **`mcp>=1.10,<2`** pinned (1.3.1 breaks on mcp 2.x), hash-pinned in `containers/scribus-mcp/requirements.txt` |
| Scribus | Debian trixie package (1.6.3) in the container; the owner's machine has 1.6.5 |
| DesignCraft | `designcraft` 0.20.1 `.deb` from the ArtCraft apt repo (`getartcraft.com/apt`, updated by apt about 5 times a week), `/usr/bin/designcraft-cli`. MCP is stdio only, protocol 2025-06-18, 26 tools, 555 commands, capabilities `tools` + `resources` (`designcraft://document`, commands) |
| DesignCraft bridge | `mcp-proxy==0.15.0` (sparfenyuk, MIT) with `mcp>=1.30,<2`, hash-pinned in `containers/designcraft-mcp/requirements.txt`; `--stateless`, one shared child process, accepts `Host: localhost:*`, 421 otherwise |
| Tunnel | `ngrok/ngrok:3` image, `--inspect=false`, v2 config file generated inline (`web_addr 0.0.0.0:4040`) |
| Engines | docker compose v2 (≥ 2.24 for `!reset`), podman-compose 1.5 (tested), podman compose |
| Host runtime | systemd user units (`systemd-run --user` for the transient mode), uv-managed CPython 3.12 venv |
| Bridge Qt binding | Must match Scribus's Qt and be importable by the system Python: Ubuntu Scribus 1.6 uses Qt5, so `python3-pyqt5` |

## Environment of the original author

Ubuntu 26.04.1, with podman 5.7 rootless (the user slice delegates `cpu memory pids`, so `mem_limit` works) and podman-compose 1.5.0 (no Docker). ngrok CLI 3.39 is installed with an authtoken. Scribus 1.6.5 is linked against Qt5 and the system Python 3.14, with `python3-pyqt5` installed. uv 0.10 lives inside a conda env, but the runtime venv doesn't depend on it after it's built. `EDITORIAL_ROOT=~/Editorial`. Single-user machine.

## Constraints

- scribus-mcp's FastMCP enforces DNS-rebinding protection: it answers 421 on a non-localhost `Host` and 403 on a foreign `Origin`.
- Free ngrok shows a browser interstitial page on the first visit to `/authorize`.
- Host mode needs Linux (`network_mode: host`) and compose `!reset` support (docker compose ≥ 2.24, podman-compose ≥ 1.1).
- DesignCraft: only the in-process engine honours `--automation-*-root`; `--connect` (desktop app) is unconfined and its control port 7979 has no authentication. In headless mode the `key` tool runs command shortcuts (Cmd+P → `file.print` → `lp`). Headless `prefs.set` stays in memory; `file.recovery.*` needs a `dir` (no fixed folder).
