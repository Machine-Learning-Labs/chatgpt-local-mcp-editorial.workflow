# Progress

## Works (verified 2026-10-12)

### v0.1: initial stack

- [x] Gateway OAuth: metadata, DCR, consent, PKCE, refresh, bearer proxy (SSE), CLI tokens.
- [x] End-to-end with the real scribus-mcp 1.3.1, both on the host and in the container image (Scribus 1.6.3 headless).
- [x] Images build with podman-compose.

### Host mode and hardening

- [x] 103 unit tests pass at 93% coverage. ruff and shellcheck are clean.
- [x] `bin/host-service` full lifecycle on the owner's machine, under a test unit name, port and data dir:
  - transient `start` (FragmentPath under `/run/.../transient/`, `NoNewPrivileges`, `UMask=0077`, `RestrictAddressFamilies` applied, listening on `127.0.0.1` only),
  - then `install`, `start`, `stop`, and `uninstall`, which leaves **nothing** behind (no unit file, no venv, no unit loaded).
- [x] The runtime venv uses the uv-managed CPython 3.12 (`~/.local/share/uv/python/...`), not conda.
- [x] End-to-end through the gateway (`.venv`) with the real host service (headless Scribus 1.6.5):
  - full OAuth flow with `iss` in the redirect,
  - `openid-configuration` returns 404, and DCR with an evil redirect returns 400,
  - 171 tools listed (4 hidden), with `securitySchemes`,
  - the instructions mention the root,
  - `set_js_action`, `/etc/x.sla` and `~/.ssh/...` are refused with readable errors,
  - allowed calls work, and relative paths are rewritten to absolute inside the root,
  - the audit log is written.
- [x] The hardened gateway container runs with `--network host`, `--read-only`, `--cap-drop ALL`, `no-new-privileges` and the root mounted read-only. It listens on 127.0.0.1 only, and the policy refuses `/etc/passwd`.
- [x] `bin/compose config` works for both modes with podman-compose 1.5 (`!reset` drops the published ports in host mode).

### Editorial Assets (2026-10-13)

- [x] 165 tests pass (assets: images, fetch, server, gateway multi-resource), at 92% coverage. ruff and shellcheck are clean.
- [x] End-to-end with the real hardened assets container (host network, read-only, `cap_drop`, user `0:0`) and the gateway:
  - OAuth with the assets resource; the assets token is rejected on `/editor/mcp`,
  - `tools/list` keeps `openai/fileParams` and adds `securitySchemes`,
  - a download from a disallowed host is refused, and so is `/etc` as a folder,
  - the upload link's GET and POST work, and reuse returns 410,
  - **the owner's real `amplificador.png` was stored byte-identical, with C2PA preserved**, mode 0640.
- [x] `bin/compose config` works for both modes with the assets service.

## Not verified yet

- [ ] Whether ChatGPT web hydrates `openai/fileParams` for our developer-mode connector (`import_image`).
- [ ] The full `make up` with the assets container, and the second connector added in ChatGPT.

- [x] The full `make up` in host mode with ngrok, and ChatGPT connecting (owner confirmed on 2026-10-12, tagged v0.2.0).
- [x] The interactive bridge with `python3-pyqt5` installed (owner confirmed).
- [ ] The image flow from ChatGPT. **The manual inbox flow does not work for the owner**, so an assets service is needed (see activeContext).
- [ ] Docker Engine (only Podman is available here). CI covers compose config and image builds.

## Known issues

- On the free ngrok plan, the consent page shows the interstitial first.
- Container mode can't use the desktop bridge (by design: see `docs/scribus-mcp.md`).
- 2026-10-12: the old `./workspace/` folder was deleted during the migration to `EDITORIAL_ROOT` without its contents being checked first. It was expected to hold only `.gitkeep`.
