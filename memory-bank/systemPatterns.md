# System patterns

The full diagram and flow are in [docs/architecture.md](../docs/architecture.md). The patterns we keep are below.

## Gateway

- **Stateless signed artefacts.** Clients, authorization requests, codes, access tokens and refresh tokens are all HS256 compact JWS tokens, distinguished by the `typ` claim. `Signer.decode(token, typ=...)` must always be called with the expected `typ`.
- **Only disposable state lives in memory:** `UsedCodes` (code replay protection) and `RateLimiter` (failed passwords per IP). Losing either on restart is acceptable.
- **The issuer comes from the request** (`X-Forwarded-Proto` + `Host`) unless `PUBLIC_URL` is set. That's how random ngrok URLs work.
- **Proxy hygiene.** Strip hop-by-hop headers, `Authorization`, `Cookie` and `Origin`. Rewrite `Host` to `UPSTREAM_HOST_HEADER`. Stream raw bytes both ways (SSE-safe). Return 502 JSON when the upstream is down.
- **Error placement.** `/authorize` errors that happen before the client and redirect are validated render an HTML page and never redirect. Later errors redirect with `error` and `state`.
- **Starlette detail.** Route endpoints must be functions or bound methods. A class instance with `__call__` is treated as a raw ASGI app.

## Ops

- `bin/lib.sh` is the single source of truth for engine detection, `.env` access, profile and upstream selection, the container user and public URL discovery.
- Modes are expressed as compose profiles (`--profile container`). `host` mode drops the service and points the gateway at `host.docker.internal`.
- The container user is `0:0` on rootless Podman and `uid:gid` on Docker, so files in the workspace belong to the owner.
- ngrok: `$$`-escaped shell in compose adds `--url` only when `NGROK_DOMAIN` is set. Port 4040 is used for URL discovery, with a fallback to the logs.

## Testing

- `tests/conftest.py::FakeUpstream` is backed by `httpx.MockTransport`. The upstream bodies must be **async iterators**, because bytes content is pre-read by httpx and breaks `aiter_raw` (`StreamConsumed`).
- Real end-to-end checks (done manually, see `progress.md`) run the gateway from `.venv` against the real scribus-mcp, both via `bin/host-mcp` and in the built image.
