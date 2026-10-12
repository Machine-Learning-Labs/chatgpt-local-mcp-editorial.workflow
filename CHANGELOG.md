# Changelog

This file follows [Keep a Changelog](https://keepachangelog.com/) and [SemVer](https://semver.org/).

## [Unreleased]

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
