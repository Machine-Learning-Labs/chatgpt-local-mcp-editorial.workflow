# AGENTS.md

These are instructions for AI coding agents and for people working on this repository. `CLAUDE.md` points here.

## What this project is

The project lets ChatGPT or Claude drive the owner's **desktop Scribus**, safely, with one command (`make up`). We **reuse** [caewa/scribus-mcp](https://github.com/caewa/scribus-mcp) and do not write our own MCP. The only code we own is the OAuth gateway and policy layer in `src/mcp_oauth_gateway/`, plus the glue around it: compose, containers, systemd and `bin/`.

There are two modes:
- `MCP_MODE=host` (default): scribus-mcp runs as a systemd user unit, and the gateway and ngrok run on the host network, so everything listens on loopback.
- `MCP_MODE=container`: headless Scribus inside the stack.

## Layout

```
docker-compose.yml          gateway + scribus-mcp (profile "container") + ngrok
docker-compose.host.yml     host-mode override: gateway + ngrok on host network, loopback only
containers/gateway/         Containerfile for the gateway (python:3.12-slim)
containers/scribus-mcp/     Containerfile for Debian trixie + scribus + xvfb + scribus-mcp (pip)
src/mcp_oauth_gateway/
  config.py                 Settings.from_env(): every env var the gateway reads
  tokens.py                 HS256 compact JWS, stdlib only; PKCE helper
  oauth.py                  metadata (RFC 9728/8414), DCR (RFC 7591), /authorize, /token
  proxy.py                  IP allowlist, bearer/aud check, body cap, JSON-RPC policy, streaming proxy
  policy.py                 tool deny/allow lists, path jail (POLICY_ROOT), tools/list rewriting
  pages.py                  consent / error HTML
  app.py                    Starlette wiring (create_app), CORS, GuardMiddleware (headers, /token IP + size)
  cli.py                    `mcp-oauth-gateway serve | token`
tests/                      pytest; FakeUpstream (conftest.py) stands in for the MCP
bin/                        every operational script; lib.sh holds the shared helpers
  host-service              scribus-mcp systemd user unit: start (transient) / install / uninstall
  scribus                   open the desktop Scribus with the MCP bridge
docs/                       stable docs (architecture, host-mode, security, clients, scribus-mcp)
memory-bank/                living project memory (decisions, progress, current focus)
```

## Commands

- `make dev` sets up `.venv`. `make test` runs ruff check, ruff format --check, pytest --cov and shellcheck.
- `bin/check` runs the preflight checks and `bin/check --live` runs the end-to-end checks. Run the preflight before you change compose or `bin/`.
- `bin/compose <args>` is the only supported way to call compose. It picks docker or podman, the `.env` file and the profile.
- Test the scripts against a throwaway env file, for example `ENV_FILE=/tmp/x.env bin/setup`. Never touch the real `.env`.
- Test `bin/host-service` with `HOST_SERVICE_NAME=ewf-test-… EWF_DATA_DIR=/tmp/…` and another `HOST_MCP_PORT`. Always finish with `uninstall`.
- Never call tools with `mode="interactive"` while testing on the owner's machine. It would drive their open Scribus.

## Rules

1. **Don't write a Scribus MCP.** For Scribus features, upgrade or configure `scribus-mcp` (`SCRIBUS_MCP_VERSION`), or contribute upstream.
2. **Every gateway change needs tests.** Security-relevant branches (PKCE, redirect matching, token types, expiry, scopes, rate limit) must each have a failing-path test. Keep coverage of `oauth.py`, `tokens.py` and `proxy.py` at or above 90%.
3. **The gateway stays stateless.** Clients, codes and tokens are signed tokens, distinguished by `typ`. The only in-memory state is used-code tracking and the rate limiter, and both are disposable. Don't add a database without recording the decision in `memory-bank/systemPatterns.md`.
4. **Keep the runtime dependency list short:** starlette, uvicorn, httpx, python-multipart. Crypto comes from the stdlib (`hmac`, `hashlib`, `secrets`).
5. **Scripts must work with Docker and Podman,** in bash 4+ with `set -euo pipefail`, and must pass shellcheck. Use `${arr[@]+"${arr[@]}"}` for arrays that may be empty. Read `.env` through `env_get`/`env_set` and never `source` it.
6. **Never print or commit secrets.** `.env` is mode 600 and git-ignored. Redact secrets in logs and in examples.
7. **Security controls are not optional.** Never weaken any of these without an entry in `docs/security.md` and in the memory bank:
   - the path jail,
   - the deny list,
   - the loopback-only binds,
   - audience checks,
   - redirect allowlists,
   - the systemd and container hardening.
   Any new tool argument that carries a path must be covered by `PATH_ARG` in `policy.py`.
8. **Upstream quirks you must keep handling:**
   - scribus-mcp 1.3.x imports `mcp.server.fastmcp`, so pin `mcp<2` wherever you install it.
   - FastMCP rejects a `Host` other than localhost (421) and a foreign `Origin` (403). The gateway sends `UPSTREAM_HOST_HEADER` and drops `Origin`.
9. Write docs and code comments in English. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).

## Before you finish a task

- Run `make test` and make sure it's green.
- If you touched compose, containers or `bin/`, run `bin/check` and `bin/compose config -q`.
- Update `memory-bank/activeContext.md` and `memory-bank/progress.md`. If you changed behaviour, update `docs/` too.
