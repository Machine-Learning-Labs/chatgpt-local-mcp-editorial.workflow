# Active context

_Last updated: 2026-10-13_

## Current focus (2026-10-13): images from ChatGPT

v0.2.0 is tagged, and the owner confirmed host mode works end to end.

The manual inbox flow **did not work** for the owner. Constraints:
- No OpenAI API key is allowed, because API usage is billed. Generation must stay inside ChatGPT.
- The owner uses **ChatGPT web**.
- The image must land automatically in `~/Editorial/libro/assets`.

The evidence that shaped the design came from the owner's own conversation:
- ChatGPT web uploaded a generated image to the **Canva** connector by itself, from its sandbox file `/mnt/data/cómo_funciona_un_amplificador_de_guitarra.png`.
- It also produced a 2.9 MB base64 `.txt` of that image.

So the sandbox has the generated image, and connectors can receive it through `openai/fileParams`. Base64 through a tool argument is impossible: about 700k output tokens.

What is now implemented, but **not yet tested against ChatGPT**, is the **Editorial Assets** second connector (`/assets/mcp`, our own code in `src/editorial_assets`, its own audience):
- `import_image` (fileParams),
- `list_assets`,
- `request_image_upload` (single-use link, as the fallback).

C2PA is kept, as the owner decided: original bytes, strictly validated.

Next step: the owner runs `make up`, adds the second connector in ChatGPT, and tries the recipe in `docs/assets-connector.md`. Check `make logs s=assets` to see whether `import_image` receives a hydrated file object on web. If it doesn't, use the upload link, and consider the downloads watcher (`~/Downloads/ChatGPT Image*.png` → assets) as a one-click option.

## Previous focus

The goal is that the owner generates images in ChatGPT, and pages are created in their **desktop Scribus**, safely. Option A ("ubuntu-host") is implemented and verified piece by piece. The owner still has to run it end to end with ngrok and ChatGPT.

## Recent decisions (2026-10-12)

- **Option A: ubuntu-host.** We chose it over B (reuse the container plus mounts) and C (a dedicated Scribus container). The bridge inside the desktop Scribus binds only to the host's `127.0.0.1` on a random port, and publishes `{port, token}` in `$XDG_RUNTIME_DIR/scribus-mcp/scribus-mcp.json`. So scribus-mcp must run on the host:
  - scribus-mcp runs as a systemd **user** unit (`bin/host-service`). It's transient by default, so `make down` removes it. `install`, `enable` and `uninstall` are available, and `uninstall` also deletes the runtime venv.
  - The runtime is a dedicated venv under `~/.local/share/editorial-workflow/`, built on the uv-managed CPython 3.12 (`--python-preference only-managed`, with `CONDA_PREFIX` and `VIRTUAL_ENV` unset). It's independent of the owner's conda environment, `scan-gpu`, where uv itself happens to live.
  - The gateway and ngrok use `network_mode: host`, through the `docker-compose.host.yml` override with `!reset` for ports. Everything binds to 127.0.0.1, and nothing listens on the LAN.
- **Root cause of the debugging session** (`docs/sync-host-debug.md`, not committed on purpose):
  - The container couldn't reach the host loopback or the discovery file, so it auto-launched a Scribus without a display. That's the zombie process.
  - The owner's Scribus froze because there's no Qt binding.
  - The fix is `python3-pyqt5` (Ubuntu 26.04's Scribus 1.6.5 is linked against Qt5, and the system Python is 3.14). glama's docs say PyQt6, which is wrong here.
- `EDITORIAL_ROOT=/home/manuel/Editorial` is the only folder the MCP may touch. The gateway enforces it with a path jail. It's mounted at the same absolute path in every container.
- Security hardening is implemented:
  - a tool policy (path jail, deny list),
  - RFC 9207 `iss`,
  - `aud` enforcement,
  - a DCR redirect allowlist,
  - removal of the OIDC alias,
  - an optional client IP allowlist,
  - body caps and security headers,
  - hardening of the containers and the systemd unit,
  - an audit log.
- **Images: manual flow for now.** The owner downloads the image into `~/Editorial/inbox/` and asks the model to `load_image` it. **If that's too much friction**, the owner's decision is to build an additional server: a tool that writes the images to disk, routed through the same gateway, OAuth and ngrok.

## Next steps

1. The owner runs `sudo apt install python3-pyqt5`, then `make up`, `make scribus`, `make check-live`, and connects ChatGPT using `docs/clients.md`. The `.env` has already been switched to `MCP_MODE=host` and `EDITORIAL_ROOT=/home/manuel/Editorial`.
2. Validate the image flow from ChatGPT using the inbox.
3. If it's too much friction, build the assets tool. Design:
   - `import_image` with `_meta["openai/fileParams"]`,
   - downloads only from OpenAI hosts, with a size cap and a magic-bytes check (PNG, JPEG, WebP),
   - writes to `EDITORIAL_ROOT/inbox/`.
   - It can be injected by the gateway (it already rewrites `tools/list`) or run as a separate container behind the same gateway.
   - First, a spike to check whether ChatGPT passes **generated** images (not only uploaded ones) through `fileParams`.
4. Set `NGROK_DOMAIN`, and optionally `GATEWAY_ALLOWED_CLIENT_CIDRS` with OpenAI's ranges.

## Open questions

- Is CIMD worth supporting? ChatGPT prefers it. It would require fetching `https://chatgpt.com/oauth/...client.json`, with SSRF guards.
- Should the gateway force `mode="interactive"` in host mode, to avoid silent headless fallbacks?
