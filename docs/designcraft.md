# DesignCraft connector

[DesignCraft](https://getartcraft.com/apps/designcraft) is an open-source page-layout app (Apache-2.0/MIT) with its own MCP server, `designcraft-cli mcp`. That server speaks **stdio only**. DesignCraft's docs say "ChatGPT on the web can't connect to programs on your computer", so this third connector bridges the gap. It is opt-in and runs in host mode only.

```
ChatGPT ─HTTPS─▶ ngrok ─▶ gateway 127.0.0.1:8080 ── /designcraft/mcp ─▶ mcp-proxy 127.0.0.1:8767 ─stdio─▶ designcraft-cli mcp
                          OAuth + DesignCraft policy                     (systemd user unit)            --automation-read-root  $EDITORIAL_ROOT
                                                                                                         --automation-write-root $EDITORIAL_ROOT
```

| Piece | What it is |
|---|---|
| `designcraft-cli mcp` | DesignCraft's own MCP server, **headless**: an in-process engine with no window. We reuse it as-is. |
| [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) | The stdio → Streamable HTTP bridge (MIT, PyPI), in its own hash-pinned venv. It is a bridge, not an MCP of ours. |
| `bin/designcraft-service` | Runs both as a systemd **user** unit on loopback. It is transient by default, like scribus-mcp. |
| `policy_designcraft.py` | The gateway policy for this resource. |

## Set up

1. Install DesignCraft (it provides `/usr/bin/designcraft-cli`; on Ubuntu, from the ArtCraft apt repository or the `.deb` on its [releases](https://github.com/storytold/designcraft/releases)).
2. In `.env`: `DESIGNCRAFT_ENABLED=true`, with `MCP_MODE=host`. `bin/check` tells you if anything is missing.
3. `make up`. It starts the unit, then the stack, and prints the third URL (`make url`).
4. In ChatGPT add a third custom MCP server with the same settings as the others ([clients.md](clients.md)): **Name** DesignCraft, **Server URL** `https://<domain>/designcraft/mcp`, OAuth with DCR, scope `mcp`, OIDC off.

`make designcraft-status`, `make designcraft-logs`, `make designcraft-install` / `designcraft-uninstall` (persistent unit) work like the `service-*` targets.

## Working with it

- Documents are `.designcraft` files under `EDITORIAL_ROOT`. Images saved by Editorial Assets (`EDITORIAL_ROOT/libro/assets`) can be placed directly, for example *"place ~/Editorial/libro/assets/cover.png on page 1"*.
- ChatGPT sees pages with `render_page`, which returns a PNG. To look or finish by hand, open the saved file in your desktop DesignCraft. The headless engine and your desktop app do not share a session.
- Every ChatGPT conversation shares one engine (one `designcraft-cli` process), so documents opened in one chat are open in the next. Save before stopping: `make down` ends the session.
- The `initialize` instructions tell the model the folder rules and what is disabled.

## What confines it

The headless engine confines files **itself**. With `--automation-read-root` and `--automation-write-root`, every file a command reads or writes has to lie inside `EDITORIAL_ROOT`, with links followed. That covers opening, placing, data sources, libraries, saving, exporting and packaging, and also the files a document references (linked images, IDML parts, `Document Fonts`). This is the primary control. It holds for every one of the ~550 commands, including those inside `batch`.

The gateway adds what the roots don't cover, and **fails closed**:

| Rule | Why |
|---|---|
| **Tools: an allow-list** of 12 (`list_commands`, `execute`, `batch`, `inspect_document`, `get_story`, `set_story_text`, `new_document`, `open_document`, `save_document`, `place_image`, `render_page`, `export_png`) | A tool that a new release adds stays hidden. `key` is left out because in headless mode it runs **command shortcuts**: Cmd+P ran `file.print`, which called `lp`. The window tools (`screenshot`, `click`, `drag`, `menu_list`, `ui_*`, `dialog_*`) need a desktop app. The gesture tools (`pointer`, `select_tool`, `type_text`, `ime`) aren't needed, since every action is a command. |
| **Commands: allow, then deny** | `execute` and `batch` run commands by id. An id must look like `namespace.name`, match a reviewed pattern (every 0.20.1 namespace except `app`, `view` and `script`; `file.*` and `edit.*` one by one) and no deny pattern. Denied: `file.print` (the system print spooler), `file.printers`, the recent-files list, `edit.paste` / `edit.pasteWithoutFormatting` (system clipboard text) and `script.run`. A new namespace is refused until it is reviewed. |
| **Shapes** | `execute` is exactly `{command, params}` and `batch` exactly `{commands: [{command, params}]}`. Batch `script` text is refused, because the gateway can't see the commands inside it. |
| **Paths** | `path`, `dir` and `coverImage` (the only path parameters of 0.20.1) go through the gateway's path jail too, as defense in depth. They must be literal: batch references such as `$0.path` are resolved after the check, so they are refused there (other arguments can use them). `fileName` export templates are left alone. |
| **JSON-RPC** | No batches (arrays). Only the reviewed methods. `resources/read` only for `designcraft://` URIs. The request is always forwarded re-serialized, so DesignCraft parses exactly what was checked. |

The service adds isolation of its own:

- It listens on 127.0.0.1 only, and mcp-proxy answers 421 to a foreign `Host`.
- The CLI runs under `env -i` with a private `HOME`. It gets no `DISPLAY`, so no system clipboard, and shares no settings, presets or recovery files with your desktop DesignCraft. Your user font folders are linked in.
- It runs under the same systemd hardening as scribus-mcp, plus `MemoryMax=2G` and `TasksMax=256`.
- It refuses to start when `designcraft-cli --version` is not `DESIGNCRAFT_VERSION`.

Settings: `DESIGNCRAFT_ALLOW_TOOLS`, `DESIGNCRAFT_ALLOW_COMMANDS` and `DESIGNCRAFT_DENY_COMMANDS` replace the defaults in `src/mcp_oauth_gateway/config.py`. Leave them empty to use the defaults. `none` empties a list, and an empty allow-list allows **nothing**.

### Not covered (accepted)

- Inside `EDITORIAL_ROOT`, an authorized client can overwrite or delete documents, as with Scribus.
- The engine reads the system font folders. That's a fixed list, not agent input.
- mcp-proxy has no authentication of its own on loopback, like the other upstreams ([security.md](security.md), "Other users on this machine"). A local caller still can't leave the engine's roots.
- **Live window mode is not supported.** `designcraft-cli mcp --connect` drives a running desktop app, which DesignCraft does **not** confine ("a connected assistant can open and save anywhere you can"), and its dialog tools take paths the gateway can't see.

## Upgrading DesignCraft

DesignCraft releases often, and apt upgrades it with the rest of the system. The policy was reviewed against one version (`DESIGNCRAFT_VERSION`, 0.20.1), and the service refuses any other. After an upgrade:

```bash
bin/designcraft-audit            # new tools and commands, path parameters, risky mentions
```

Review every line it prints:
- a new tool stays hidden unless you add it to `DEFAULT_DESIGNCRAFT_ALLOW_TOOLS`;
- a new namespace is refused unless you add it to `DEFAULT_DESIGNCRAFT_ALLOW_COMMANDS`;
- a new path parameter goes into `PATH_KEYS` in `policy_designcraft.py`;
- anything that prints, opens programs or reaches the network goes into the deny list.

Then record the review with `bin/designcraft-audit --update` (it rewrites `containers/designcraft-mcp/reviewed.json`), set `DESIGNCRAFT_VERSION` in `.env` and `.env.example`, and run `make test` and `make check-live`.

mcp-proxy is pinned like everything else: change `MCP_PROXY_VERSION`, then run `make lock` and restart the unit (`make designcraft-uninstall` drops the old venv).
