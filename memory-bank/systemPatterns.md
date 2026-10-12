# System patterns

The full diagram and flow are in [docs/architecture.md](../docs/architecture.md). The patterns we keep are below.

## Gateway

- **Stateless signed artefacts.** Clients, authorization requests, codes, access tokens and refresh tokens are all HS256 compact JWS tokens, distinguished by the `typ` claim. `Signer.decode(token, typ=...)` must always be called with the expected `typ`.
- **Only disposable state lives in memory:** `UsedCodes` (code replay protection) and `RateLimiter` (failed passwords per IP). Losing either on restart is acceptable.
- **The issuer comes from the request** (`X-Forwarded-Proto` + `Host`) unless `PUBLIC_URL` is set. That's how random ngrok URLs work.
- **Proxy hygiene.** Strip hop-by-hop headers, `Authorization`, `Cookie` and `Origin`. Rewrite `Host` to `UPSTREAM_HOST_HEADER`. Stream raw bytes both ways (SSE-safe). Return 502 JSON when the upstream is down.
- **Error placement.** `/authorize` errors that happen before the client and redirect are validated render an HTML page and never redirect. Later errors redirect with `error` and `state`.
- **Starlette detail.** Route endpoints must be functions or bound methods. A class instance with `__call__` is treated as a raw ASGI app.

## Policy layer (gateway)

- `Policy.apply_call` validates **and rewrites** `tools/call` params. Path arguments (`PATH_ARG` regex: `path`, `*_path`, `*_dir`, `file`, …, found at any depth) are resolved with `realpath` against `POLICY_ROOT` and forwarded in absolute form, so the upstream acts on exactly what was checked.
- A refusal is a JSON-RPC **result** with `isError: true` and the reason, not a transport error, so the model can read it and recover. Batches containing a refused call are rejected whole.
- Only `tools/list` and `initialize` responses are buffered and rewritten (JSON or SSE). Everything else is streamed. If a rewrite fails, the gateway answers 502 and never passes the response through unfiltered.
- Tokens are audience-bound. The proxy checks `aud` against `base_url(request)/mcp`, so local checks need `bin/token --local`.
- Client IP: the last `X-Forwarded-For` hop is used, and only when the peer is in `GATEWAY_TRUSTED_PROXIES`.

## Ops

- `bin/lib.sh` is the single source of truth for engine detection, `.env` access, profile and upstream selection, the container user and public URL discovery.
- Modes are selected through compose files. Container mode is `docker-compose.yml` with `--profile container`. Host mode adds `docker-compose.host.yml`, which puts the gateway and ngrok on the host network with `ports: !reset []` and bindings to 127.0.0.1.
- In host mode, scribus-mcp is a systemd user unit (`bin/host-service`). `bin/up` starts it as a transient unit unless one is installed. `bin/down` stops it only when it's transient (`--all` stops it either way).
- `EDITORIAL_ROOT` is mounted at the same absolute path everywhere: read-only in the gateway (for `realpath`), read-write in the scribus-mcp container.
- The container user is `0:0` on rootless Podman and `uid:gid` on Docker, so files in the workspace belong to the owner.
- ngrok: `$$`-escaped shell in compose adds `--url` only when `NGROK_DOMAIN` is set. Port 4040 is used for URL discovery, with a fallback to the logs.

## Testing

- `tests/conftest.py::FakeUpstream` is backed by `httpx.MockTransport`. The upstream bodies must be **async iterators**, because bytes content is pre-read by httpx and breaks `aiter_raw` (`StreamConsumed`).
- Real end-to-end checks (done manually, see `progress.md`) run the gateway from `.venv` against the real scribus-mcp, both through `bin/host-service` (with a test unit name) and in the built image.
