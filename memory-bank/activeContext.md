# Active context

_Last updated: 2026-10-14_

## State: nothing in flight

Everything the project set out to do works end to end on the owner's machine, through ngrok, from **ChatGPT web**:

- Host mode drives the owner's desktop Scribus (v0.2.0, 2026-10-12).
- The security audit of 2026-10-13 is closed: every finding fixed and committed on 2026-10-14 (`CHANGELOG.md` "Security", `docs/security.md`). Threat model: **one user, one machine**.
- The image flow works: ChatGPT web hydrates `openai/fileParams`, `import_image` downloads the generated image from OpenAI's Azure blob host and stores it inside `EDITORIAL_ROOT` with C2PA kept (last check: a 2.1 MB PNG, `c2pa=True`). The single-use upload link works as the fallback.

The next session can start a new feature from a clean slate. Read `AGENTS.md` first, then `docs/`; this file and `progress.md` carry the decisions.

## How to pick up the work

- `make dev && make test` (uv, locked). `make up` starts the stack, `make check-live` verifies it, `make down` stops it. `make lock` after any dependency change.
- Security rules that must not be weakened are listed in `AGENTS.md` rule 7. New tool arguments that carry paths go through `PATH_ARG` in `policy.py`.
- The owner's constraints: no OpenAI API key (billed), ChatGPT web, images must land in `EDITORIAL_ROOT/libro/assets` (or the folder the model names under the root), C2PA kept.
- Never call tools with `mode="interactive"` while testing on the owner's machine.

## Candidate features (none started)

- Force `mode="interactive"` in host mode, so a call never falls back to headless Scribus silently.
- CIMD (client ID metadata documents), which ChatGPT prefers over DCR. Needs an SSRF-guarded fetch of `https://chatgpt.com/oauth/...client.json`.
- Shorter `REFRESH_TOKEN_TTL` by default, since a used refresh token stays valid until it expires.
- `read_only` for the ngrok container (it only writes `/tmp/ngrok.yml`, already on tmpfs). Untested.
- A downloads watcher (`~/Downloads/ChatGPT Image*.png` → assets) is no longer needed; keep it only if the owner asks.

## Decisions to keep in mind

- **Option A, ubuntu-host (2026-10-12).** scribus-mcp runs on the host as a systemd user unit from its own uv venv; the gateway and ngrok run on the host network and bind to loopback. The bridge in the desktop Scribus needs `python3-pyqt5` (Scribus 1.6 on Ubuntu is Qt5).
- **Reuse caewa/scribus-mcp**, never write a Scribus MCP. The only MCP we own is Editorial Assets.
- **The gateway stays stateless** (signed tokens, `typ` claim); only the used-code set and the rate limiter live in memory.
- **Dependencies are hash-pinned** (`uv.lock`, `containers/*/requirements.txt`), audited by `pip-audit` in CI, updated by Dependabot.
- **The owner's home path** in docs and history is acceptable to them (no history rewrite).
- `docs/sync-host-debug.md` is deliberately not committed.
