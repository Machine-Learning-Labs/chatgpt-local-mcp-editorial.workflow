# Changelog

This file follows [Keep a Changelog](https://keepachangelog.com/) and [SemVer](https://semver.org/).

## [Unreleased]

### Added

- An OAuth 2.1 gateway (`mcp-oauth-gateway`) that implements the MCP authorization spec, with DCR, PKCE S256, a consent page and refresh tokens. It proxies MCP traffic to the upstream server, streaming it and checking the bearer token on every request.
- A compose stack with the gateway, caewa/scribus-mcp 1.3.1 (headless Scribus 1.6) and ngrok, working with Docker or Podman.
- Scripts in `bin/`: `setup`, `check` (preflight and `--live`), `up`, `token`, `url`, `rotate`, `host-mcp`, `compose` and `test`.
- Host mode, which serves the scribus-mcp running on your desktop.
