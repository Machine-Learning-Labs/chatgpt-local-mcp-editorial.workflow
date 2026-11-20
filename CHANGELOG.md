# Changelog

This file follows [Keep a Changelog](https://keepachangelog.com/) and [SemVer](https://semver.org/).

## [Unreleased]

### Added

- **DesignCraft connector** (optional, host mode, `DESIGNCRAFT_ENABLED=true`): a third protected resource at `/designcraft/mcp` for [DesignCraft](https://getartcraft.com/apps/designcraft)'s own MCP server. Details in [docs/designcraft.md](docs/designcraft.md).
  - `designcraft-cli mcp` runs headless and is confined to `EDITORIAL_ROOT` by DesignCraft itself (`--automation-read-root/--automation-write-root`).
  - [mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) bridges its stdio to Streamable HTTP, as a systemd user unit on loopback (`bin/designcraft-service`).
  - `DesignCraftPolicy` fails closed:
    - tool and command allow-lists (`key` is hidden: it runs command shortcuts such as Cmd+P → print);
    - a deny list for printing, the system clipboard and `script.run`;
    - strict `execute`/`batch` shapes, with no batch `script` text;
    - literal path arguments;
    - no JSON-RPC batches, and only `designcraft://` resources.
  - The CLI runs with a private `HOME` and no display.
  - The service refuses any DesignCraft version other than `DESIGNCRAFT_VERSION`. `bin/designcraft-audit` diffs an upgrade against the reviewed snapshot.
- `bin/lock --upgrade-package X` (and `--upgrade`) to move pins with the supported command.

### Changed

- `bin/host-service uninstall` removes only scribus-mcp's runtimes, not the whole data folder.
- Dependencies: pillow 13.0.0 and certifi 2026.10.23 (security fixes: PYSEC-2026-4320 and 4326–4343, plus four CVEs), starlette 1.10.0, python-multipart 0.0.34, Python 3.15 base images, setup-uv 10.3.3.

### Security

Findings of the 2026-10-13 audit, all fixed:

- **Client IP spoofing.** uvicorn ran with `proxy_headers=True` and `forwarded_allow_ips="*"`, which hands the application the *first* `X-Forwarded-For` hop, the one the client writes (ngrok appends its own at the end). `GATEWAY_ALLOWED_CLIENT_CIDRS` could be bypassed with a forged header, and the consent-password rate limiter could be reset on every attempt. uvicorn now runs with `proxy_headers=False`; `network.py` takes the last hop, only from `GATEWAY_TRUSTED_PROXIES`, for the allowlist, the rate limiter and the audit log.
- **Issuer derivation.** `X-Forwarded-Host` is no longer used (ngrok passes a client-supplied one through); the issuer is `PUBLIC_URL` or the `Host` header, with the scheme from the last `X-Forwarded-Proto` hop of a trusted proxy.
- **ngrok inspector.** The agent now runs with `--inspect=false`. Its inspector kept every request, bearer tokens and the consent password included, on an unauthenticated local API.
- **Body caps for chunked requests.** Every body-carrying route has a Starlette `max_body_size`, so a request without `Content-Length` is cut off at the cap instead of being read whole. The consent POST is capped too (64 KB). The assets server applies its own limit.
- **Decompression bombs.** The pixel cap is checked on the image header before anything is decoded (Pillow alone only fails at twice the cap).
- **Dependencies.** `starlette>=1.6` (per-route body limits; the urlencoded form limits of CVE-2026-54283 were fixed in 1.3.1, and `max_part_size` only exists from 0.45). Every dependency is pinned with hashes: `uv.lock` plus `containers/*/requirements.txt`, regenerated with `make lock`; the images and the host runtime install with `--require-hashes`; CI runs `pip-audit`; Dependabot is configured; GitHub Actions are pinned by commit; the ngrok image is `ngrok/ngrok:3` instead of `:latest`.
- **Hardening.** Containers have `mem_limit` and `pids_limit`. `/editor/mcp/...` and `/assets/mcp/...` sub-paths are no longer proxied (Streamable HTTP is a single endpoint). A malformed `code_verifier` answers `invalid_grant` instead of a 500. The 502 error no longer names the internal upstream address. `bin/setup` and `bin/check` refuse `EDITORIAL_ROOT` set to `/`, `$HOME` or a parent of `$HOME`. The consent page warns that anyone can register a client under any name.
- **Documented.** The single-user assumption (scribus-mcp and the assets server trust every local process), with a `bin/check` warning when other login accounts exist and an nftables example; that a used refresh token stays valid until it expires; that upload links appear in access logs.

### Fixed

- `import_image` accepts the file URLs ChatGPT web actually hands over, on OpenAI's Azure storage accounts (`oaisdmntpr<region>.blob.core.windows.net`). `ASSETS_DOWNLOAD_HOSTS` entries may use `*` for part of one label; the default list includes `oaisdmntpr*.blob.core.windows.net`. The image flow from ChatGPT web is verified end to end.

### Changed

- **Breaking:** the Scribus connector moved from `/mcp` to **`/editor/mcp`**, alongside `/assets/mcp`. The resource paths are constants in `config.py`. Update the ChatGPT connector URL; `/mcp` now answers 404.
- `bin/setup --dev` uses `uv sync` (the locked set) when uv is available.
- Personal paths in the docs are now written as `~/Editorial`.

### Added

- The **Editorial Assets** MCP server (`src/editorial_assets`, container `assets`), exposed as a second connector at `/assets/mcp` with its own OAuth audience. Its tools:
  - `import_image`, which receives files from ChatGPT through `openai/fileParams`, with an SSRF-guarded download from OpenAI file hosts,
  - `list_assets`,
  - `request_image_upload`, which issues single-use signed upload links served through `/upload/<token>`.
- Images are validated strictly and stored in `EDITORIAL_ROOT/libro/assets`. PNG and JPEG are kept byte for byte, so C2PA provenance survives. WebP is converted to PNG. Writes are deduplicated and never overwrite.
- The gateway supports multiple protected resources, each with its own metadata, challenge and audience. It forwards `X-Forwarded-Host`. `token --resource` and `bin/token --assets` mint tokens for a given resource.
- `bin/check --live` covers the assets connector: separate audience, `fileParams`, policy refusals, loopback bind, and the path through ngrok.

## [0.2.0] - 2026-10-12

Host mode: ChatGPT drives the desktop Scribus, verified end to end through ngrok.

### Added

- Host mode as the default. scribus-mcp runs as a systemd user unit (`bin/host-service`), either transient or installed, from a dedicated uv venv that is isolated from conda. Gateway and ngrok run on the host network and bind to loopback only. `bin/scribus` opens the desktop Scribus with the bridge loaded.
- A tool policy in the gateway:
  - a path jail in `EDITORIAL_ROOT`, with paths resolved through `realpath` and rewritten to absolute form,
  - a deny list (`run_script`, `install_custom_font`, `set_js_action`, `create_pdf_push_button`) and an optional allow list,
  - rewriting of `tools/list` (JSON and SSE) to add `securitySchemes`,
  - an audit log.
- OAuth hardening:
  - RFC 9207 `iss`,
  - audience binding (RFC 8707 `resource` becomes `aud`, which the proxy checks),
  - a redirect URI allowlist for DCR,
  - an optional client IP allowlist with trusted-proxy handling of `X-Forwarded-For`,
  - body size caps,
  - security headers.
- Hardened containers: `cap_drop: ALL`, `no-new-privileges`, and a read-only gateway.
- `bin/check` host checks: Qt binding, loopback-only listeners, discovery file permissions, and the policy exercised live.

### Changed

- `WORKSPACE_DIR=./workspace` was replaced by `EDITORIAL_ROOT`, which defaults to `~/Editorial` and is mounted at the same absolute path everywhere.
- `bin/host-mcp`, which bound to `0.0.0.0`, was replaced by `bin/host-service`.

### Removed

- `/.well-known/openid-configuration`. The gateway is not an OIDC provider, and ChatGPT would otherwise request OIDC scopes.

### Fixed

- Rewritten SSE responses (`tools/list`, `initialize`) now keep the upstream's CRLF framing and are streamed without `Content-Length`. Before this fix, ngrok broke them with an HTTP/2 `PROTOCOL_ERROR`.
- `bin/` finds `uv` outside `PATH`: standalone installs, conda envs, or `UV` in `.env`.

## [0.1.0] - 2026-10-12

### Added

- An OAuth 2.1 gateway (`mcp-oauth-gateway`) that implements the MCP authorization spec, with DCR, PKCE S256, a consent page and refresh tokens. It proxies MCP traffic to the upstream server, streaming it and checking the bearer token on every request.
- A compose stack with the gateway, caewa/scribus-mcp 1.3.1 (headless Scribus 1.6) and ngrok, working with Docker or Podman.
- Scripts in `bin/`: `setup`, `check` (preflight and `--live`), `up`, `token`, `url`, `rotate`, `host-mcp`, `compose` and `test`.
- Host mode, which serves the scribus-mcp running on your desktop.
