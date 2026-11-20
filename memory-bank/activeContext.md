# Active context

_Last updated: 2026-11-20_

## State: DesignCraft connector built, waiting for the owner's end-to-end check; repo ready to go public

- **Open source (decided 2026-11-20): safe to publish.** gitleaks over the full history found nothing, `.env` was never tracked, emails are noreply, CI is safe for fork PRs, licences are permissive. The owner flips the visibility themselves. Right after, enable private vulnerability reporting (`SECURITY.md` relies on it), secret scanning with push protection, Dependabot alerts and security updates, and a ruleset on `main`. Steps are in PR #17.
- **Dependencies (2026-11-20).** The Dependabot batch is on `main` (#16 and the individual PRs). pillow 13 and certifi fix the `audit` failures. `bin/lock --upgrade-package X` moves pins.
- **DesignCraft (branch `feat/designcraft`).** A third connector at `/designcraft/mcp`: headless `designcraft-cli mcp`, confined to `EDITORIAL_ROOT` by its own roots, behind mcp-proxy (`bin/designcraft-service`), with `DesignCraftPolicy`. Opt-in: `DESIGNCRAFT_ENABLED=true`, host mode. Everything up to the real gateway was verified locally (see `progress.md`). What's missing is the owner's check from ChatGPT web.

## How to pick up the work

- `make dev && make test` (uv, locked). `make up` starts the stack, `make check-live` verifies it, `make down` stops it. `make lock` after any dependency change.
- Security rules that must not be weakened are listed in `AGENTS.md` rule 7, now including the DesignCraft controls. New tool arguments that carry paths go through `PATH_ARG` in `policy.py` (Scribus, assets) or `PATH_KEYS` in `policy_designcraft.py`.
- After a DesignCraft upgrade (apt, frequent), run `bin/designcraft-audit`, review, update the policy, then `--update` and bump `DESIGNCRAFT_VERSION`. The service refuses to start until they match.
- The owner's constraints: no OpenAI API key (billed), ChatGPT web, images must land in `EDITORIAL_ROOT/libro/assets` (or the folder the model names under the root), C2PA kept.
- Never call tools with `mode="interactive"` while testing on the owner's machine. Never use DesignCraft `--connect`.

## Candidate features (none started)

- A DesignCraft container image (Debian + `.deb` pinned by `SHA256SUMS.txt` + mcp-proxy) to smoke-test the bridge in CI.
- Force `mode="interactive"` in host mode, so a call never falls back to headless Scribus silently.
- CIMD (client ID metadata documents), which ChatGPT prefers over DCR. Needs an SSRF-guarded fetch of `https://chatgpt.com/oauth/...client.json`.
- Shorter `REFRESH_TOKEN_TTL` by default, since a used refresh token stays valid until it expires.
- `read_only` for the ngrok container (it only writes `/tmp/ngrok.yml`, already on tmpfs). Untested.
- Optional upstream bearer for mcp-proxy (`MCP_PROXY_AUTH_TOKEN`, injected by the gateway) against other local accounts.

## Decisions to keep in mind

- **DesignCraft headless only (2026-11-20, owner).** The live desktop window (`--connect`) is not confined by DesignCraft and its dialog tools take paths the gateway can't see. Rejected.
- **DesignCraft has its own service script**, not a profile of `bin/host-service`, so the proven Scribus unit stays unchanged.
- **Option A, ubuntu-host (2026-10-12).** scribus-mcp runs on the host as a systemd user unit from its own uv venv; the gateway and ngrok run on the host network and bind to loopback. The bridge in the desktop Scribus needs `python3-pyqt5` (Scribus 1.6 on Ubuntu is Qt5).
- **Reuse caewa/scribus-mcp and DesignCraft's own MCP**, never write one. The only MCP we own is Editorial Assets; mcp-proxy is a bridge.
- **The gateway stays stateless** (signed tokens, `typ` claim); only the used-code set and the rate limiter live in memory.
- **Dependencies are hash-pinned** (`uv.lock`, `containers/*/requirements.txt`), audited by `pip-audit` in CI, updated by Dependabot.
- **The owner's home path** in docs and history is acceptable to them (no history rewrite).
- `docs/sync-host-debug.md` is deliberately not committed.
