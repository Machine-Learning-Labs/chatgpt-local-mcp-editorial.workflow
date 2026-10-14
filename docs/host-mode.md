# Host mode: ChatGPT drives your desktop Scribus

`MCP_MODE=host` is the default mode. In this mode, the pages ChatGPT (or Claude) builds appear in the Scribus window you have open on your desktop, and every file stays inside `EDITORIAL_ROOT`.

```
ChatGPT ─HTTPS─▶ ngrok ─▶ gateway 127.0.0.1:8080 ─▶ scribus-mcp 127.0.0.1:8765 ─▶ bridge 127.0.0.1:<random>
                 (container, host net)  (container, host net)  (systemd user unit)      inside YOUR Scribus
                                        OAuth + tool policy                              (token in a 0600 file)
```

Everything listens on loopback. Nothing is published to your LAN. The only way in from outside is the ngrok tunnel to the gateway, which requires an OAuth token and enforces the tool policy.

## Daily use

```bash
make up        # starts scribus-mcp (transient unit) + gateway + ngrok, prints URL + token
make scribus   # opens your Scribus with the MCP bridge loaded
# … work from ChatGPT …
make down      # stops everything; the transient unit disappears
```

`make up` starts scribus-mcp as a **transient** systemd user unit (`systemd-run`). It doesn't write anything under `~/.config`, and it vanishes on `make down`, at logout or on reboot.

To keep it permanently:

| Command | Effect |
|---|---|
| `make service-install` | Writes `~/.config/systemd/user/editorial-scribus-mcp.service`. `make up` starts it, and `make down` leaves it running. |
| `make service-enable` | Same as above, and also starts it at every login |
| `make service-status` / `make service-logs` | Show state, the runtime, the endpoint and the bridge; follow the journald logs |
| `make down-all` | Stops the stack, including an installed unit |
| `make service-uninstall` | Stops and disables the unit, then **deletes** the unit file and the runtime venv. Your `EDITORIAL_ROOT` is never touched. |

## Dependencies: what gets installed where

| What | Where | Affects conda? | Affects the system? |
|---|---|---|---|
| scribus-mcp 1.3.1 + `mcp<2` | Its own venv in `~/.local/share/editorial-workflow/scribus-mcp-<ver>/`, on the **uv-managed CPython 3.12** (`--python-preference only-managed`, built with `CONDA_PREFIX` and `VIRTUAL_ENV` unset) | No | No |
| uv | Only needed once, to build that venv | No | No |
| `python3-pyqt5` (apt) | System Python, which is the interpreter **embedded in Scribus** | No (conda has its own Python) | One small, distro-maintained package |
| The unit's `PATH` | Fixed to `/usr/local/bin:/usr/bin:/bin` | conda is never on it | No |

### Why `python3-pyqt5` can't come from uv or conda

The bridge (`scribus_mcp_bridge.spy`) doesn't run in a Python you choose. It runs inside Scribus's own embedded interpreter, which is the system `libpython3.x` that Scribus is linked against. To keep the GUI responsive, the bridge needs a Qt binding that this interpreter can import, and that binding has to match the Qt that Scribus itself loaded.

- On Ubuntu/Debian, Scribus 1.6 is built with **Qt5**, so the binding is **`python3-pyqt5`**. Don't install PyQt6: it would load Qt6 into a Qt5 process.
- A pip or conda PyQt5 wheel ships its own Qt5 build. Loaded into Scribus, it would clash with the system Qt5, so the distro package is the clean option.
- Without any binding, the bridge falls back to a loop that blocks the main thread, which freezes the Scribus GUI. `bin/check` and `make scribus` detect this.

```bash
sudo apt install python3-pyqt5      # once; remove with: sudo apt remove python3-pyqt5
```

## The editorial folder

`EDITORIAL_ROOT` (`~/Editorial` by default) is the only place the MCP can read or write.

- Every path argument (`path`, `image_path`, `font_path`, `target_dir`, …) is resolved, symlinks included, and must land inside it. Otherwise the call is refused before it reaches Scribus. Those four names are the only path arguments in scribus-mcp 1.3.1; the `PATH_ARG` pattern in `policy.py` covers them and the usual spellings other MCPs use.
- Relative paths are resolved against the root and forwarded as absolute paths.
- `bin/setup` creates the folder with mode 700, plus `inbox/` and `libro/assets/`. It refuses `/`, `$HOME` or a parent of `$HOME` as the root.

### Images

Images generated in ChatGPT reach `EDITORIAL_ROOT/libro/assets/` through the **Editorial Assets** connector, see [assets-connector.md](assets-connector.md). The manual alternative still works: drop a file into `~/Editorial/inbox/` and ask, for example, *"create an image frame on page 1 and load ~/Editorial/inbox/cover.png, scaled to the frame"* (with `~` spelled out). ChatGPT then calls `create_image_frame`, `load_image` and `scale_image_to_frame`.

### Who else can reach the service

scribus-mcp and the assets server trust every local process: they listen on 127.0.0.1 without authentication of their own. That is fine for your own account on your own machine. `bin/check` warns when other login accounts exist; [security.md](security.md) explains the options for a shared machine.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Scribus freezes for minutes | No Qt binding is available, so the bridge is blocking the main thread. Run `sudo apt install python3-pyqt5`, then restart Scribus. |
| Calls run headless instead of in your window | The bridge isn't running. Run `make scribus` and check with `make service-status`. |
| `port 8765 is already in use` | An old `make host-mcp` or another process holds the port. Change `HOST_MCP_PORT`. |
| The New Document wizard blocks the bridge | Close it once. To disable it, set `ShowStartupDialog="0"` in `~/.config/scribus/scribus*.rc`. |
| `Refused: … outside the editorial folder` | Working as intended. Use a path under `EDITORIAL_ROOT`. |
