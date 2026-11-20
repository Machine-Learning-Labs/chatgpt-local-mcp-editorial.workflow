# System patterns

The full diagram and flow are in [docs/architecture.md](../docs/architecture.md). The patterns we keep are below.

## Gateway

- **Stateless signed artefacts.** Clients, authorization requests, codes, access tokens and refresh tokens are all HS256 compact JWS tokens, distinguished by the `typ` claim. `Signer.decode(token, typ=...)` must always be called with the expected `typ`.
- **Only disposable state lives in memory:** `UsedCodes` (code replay protection) and `RateLimiter` (failed passwords per IP). Losing either on restart is acceptable.
- **The issuer comes from the request** unless `PUBLIC_URL` is set: the `Host` header (ngrok forwards it unchanged) plus the scheme from the *last* `X-Forwarded-Proto` hop, and only when the TCP peer is a trusted proxy. `X-Forwarded-Host` is never read (ngrok passes a client-supplied one through). That's how random ngrok URLs work without letting a client rename the issuer.
- **uvicorn never rewrites the client address** (`proxy_headers=False` in `cli.py`). With `forwarded_allow_ips="*"` it would use the *first* `X-Forwarded-For` hop, which the client controls; `network.py` uses the last hop from trusted proxies for the IP allowlist, the rate limiter and the audit log. A test pins the uvicorn call.
- **Body caps are per route** (`max_body_size` on each `Route`, Starlette ≥ 1.6): they hold for chunked bodies. The handlers keep a fast Content-Length check for a JSON 413. The assets server wraps its app in `RequestBodyLimitMiddleware` (`build_asgi`).
- **One endpoint per resource.** No `{path:path}` sub-routes: Streamable HTTP needs none, and they only widened the upstream surface.
- **Proxy hygiene.** Strip hop-by-hop headers, `Authorization`, `Cookie` and `Origin`. Rewrite `Host` to `UPSTREAM_HOST_HEADER`. Stream raw bytes both ways (SSE-safe). Return 502 JSON when the upstream is down.
- **Error placement.** `/authorize` errors that happen before the client and redirect are validated render an HTML page and never redirect. Later errors redirect with `error` and `state`.
- **Starlette detail.** Route endpoints must be functions or bound methods. A class instance with `__call__` is treated as a raw ASGI app.

## Policy layer (gateway)

- `Policy.apply_call` validates **and rewrites** `tools/call` params. Path arguments (`PATH_ARG` regex: `path`, `*_path`, `*_dir`, `file`, …, found at any depth) are resolved with `realpath` against `POLICY_ROOT` and forwarded in absolute form, so the upstream acts on exactly what was checked.
- A refusal is a JSON-RPC **result** with `isError: true` and the reason, not a transport error, so the model can read it and recover. Batches containing a refused call are rejected whole.
- Only `tools/list` and `initialize` responses are buffered and rewritten (JSON or SSE). Everything else is streamed. If a rewrite fails, the gateway answers 502 and never passes the response through unfiltered.
- Tokens are audience-bound. The proxy checks `aud` against `base_url(request)` + the resource path (`/editor/mcp` or `/assets/mcp`, constants in `config.py`), so local checks need `bin/token --local`.
- Client IP: the last `X-Forwarded-For` hop is used, and only when the peer is in `GATEWAY_TRUSTED_PROXIES`.
- **One policy per resource.** `McpProxy(policy=...)`; editor and assets share `Policy.from_settings`, DesignCraft gets `DesignCraftPolicy` (`policy_designcraft.py`). Base hooks: `path_key`, `check_message` (non-`tools/call` methods), `audit_detail`, and `strict` (refuse JSON-RPC arrays, always forward the re-serialized body).
- **DesignCraft fails closed.** Allow-lists for tools and command patterns (`config.py` defaults), then a deny list; `execute`/`batch` shapes are exact and batch `script` text is refused; path keys are exactly `path`, `dir`, `coverImage` and must not contain `$` (batch references resolve after the check); `fileName` is a template, not a path. The engine's own roots are the primary file control.
- `PATH_ARG` was checked against every tool of scribus-mcp 1.3.1 (175 tools, parsed with `ast`): the only path arguments are `path`, `image_path`, `font_path` and `target_dir`. Repeat the check when the version changes.

## Dependencies

- `make lock` (`bin/lock`) writes `uv.lock`, exports `containers/gateway/requirements.txt` and `containers/assets/requirements.txt` from it, and compiles `containers/scribus-mcp/requirements.txt` (universal, hashed) from `SCRIBUS_MCP_VERSION`. The images and `bin/host-service` install with `--require-hashes`; `bin/host-service` refuses to build when the pinned version differs from `SCRIBUS_MCP_VERSION`.
- `bin/setup --dev` is `uv sync --extra dev` (pip fallback without uv). CI uses `uv sync --locked`, audits both pinned sets with `pip-audit`, pins actions by SHA, and Dependabot covers uv, pip, docker, docker-compose and actions.

## Ops

- `bin/lib.sh` is the single source of truth for engine detection, `.env` access, profile and upstream selection, the container user and public URL discovery.
- Modes are selected through compose files. Container mode is `docker-compose.yml` with `--profile container`. Host mode adds `docker-compose.host.yml`, which puts the gateway and ngrok on the host network with `ports: !reset []` and bindings to 127.0.0.1.
- DesignCraft is a separate script, `bin/designcraft-service`, not a profile of `host-service` (whose Scribus unit stays untouched). Its `ExecStart` is `bin/designcraft-service run`, which re-checks the version gate on every (re)start and then `exec env -i` mcp-proxy with a private `HOME`. `docker-compose.designcraft.yml` is added by `compose_env` only with host mode and `DESIGNCRAFT_ENABLED=true`.
- In host mode, scribus-mcp is a systemd user unit (`bin/host-service`). `bin/up` starts it as a transient unit unless one is installed. `bin/down` stops it only when it's transient (`--all` stops it either way).
- `EDITORIAL_ROOT` is mounted at the same absolute path everywhere: read-only in the gateway (for `realpath`), read-write in the scribus-mcp container.
- The container user is `0:0` on rootless Podman and `uid:gid` on Docker, so files in the workspace belong to the owner.
- ngrok: `$$`-escaped shell in compose adds `--url` only when `NGROK_DOMAIN` is set, and always passes `--inspect=false` (the inspector would store tokens and the consent password). Port 4040 stays up for `/api/tunnels` URL discovery, with a fallback to the logs. The image is pinned to `ngrok/ngrok:3`.
- Every service has `mem_limit` and `pids_limit`; rootless Podman applies them because the user slice delegates `cpu memory pids`.
- The stack assumes a single-user machine: `bin/check` warns about other login accounts (`other_login_users` in `lib.sh`), and `root_is_dedicated` refuses `/`, `$HOME` or a parent as `EDITORIAL_ROOT`.

## Testing

- `tests/conftest.py::FakeUpstream` is backed by `httpx.MockTransport`. The upstream bodies must be **async iterators**, because bytes content is pre-read by httpx and breaks `aiter_raw` (`StreamConsumed`).
- Real end-to-end checks (done manually, see `progress.md`) run the gateway from `.venv` against the real scribus-mcp, both through `bin/host-service` (with a test unit name) and in the built image.
