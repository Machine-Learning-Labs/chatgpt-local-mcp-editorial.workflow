# Progress

## Works (verified 2026-10-12)

- [x] Gateway: metadata (RFC 9728/8414), DCR, consent with password and rate limit, code + PKCE S256, refresh rotation, bearer proxy with SSE streaming, CLI token minting.
- [x] 69 unit tests pass; ruff and shellcheck are clean.
- [x] End-to-end with the real scribus-mcp 1.3.1 on the host via `bin/host-mcp`: the full OAuth flow, then initialize, then 174 tools, then a tool call.
- [x] Images build with podman-compose: gateway (156 MB) and scribus-mcp (948 MB).
- [x] End-to-end against the built scribus-mcp image: `get_scribus_version` returns 1.6.3 (headless Scribus on Xvfb).
- [x] `bin/setup` (imports the ngrok token) and `bin/check` pass, tested with a throwaway env file.
- [x] `bin/compose config` renders both profiles correctly with podman-compose.

## Not verified yet

- [ ] The full `make up` with the ngrok container and a public URL (needs the owner's run).
- [ ] Docker engine (only Podman was available).
- [ ] Real OAuth clients: claude.ai connector, Claude Code `/mcp`, ChatGPT.
- [ ] scribus-mcp interactive bridge in host mode.
- [ ] CI workflow on GitHub (no remote yet).

## Known issues

- The free ngrok interstitial page shows up on the consent page (cosmetic).
- Tools that need Scribus 1.7 aren't available in the container (Debian ships 1.6.3).
