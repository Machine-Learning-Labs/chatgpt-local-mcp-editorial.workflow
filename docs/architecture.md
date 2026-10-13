# Architecture

```
host mode (default)
MCP client ─HTTPS─▶ ngrok edge ─▶ ngrok agent ─▶ gateway 127.0.0.1:8080 ─▶ scribus-mcp 127.0.0.1:8765 ─▶ bridge in your Scribus
                                  (container,     (container, host net)     (systemd user unit)
                                   host net)

container mode
MCP client ─HTTPS─▶ ngrok edge ─▶ ngrok agent ─▶ gateway:8080 ─▶ scribus-mcp:8000 ─▶ headless Scribus (Xvfb)
                                  (bridge network; only the gateway publishes 127.0.0.1:8080)
```

A third container, **assets** (`src/editorial_assets`), is a second protected resource at `/assets/mcp`. It runs on host networking with loopback `127.0.0.1:8766` in host mode, and as `assets:8766` in container mode. The gateway also passes `/upload/<token>` through to it without a bearer: the signed single-use token is the capability. See [assets-connector.md](assets-connector.md).

The gateway (`src/mcp_oauth_gateway`) does three jobs:

1. **OAuth 2.1 authorization server.** It implements RFC 8414 metadata, RFC 7591 DCR, PKCE S256, RFC 9207 `iss` and refresh rotation.
2. **Resource server.** On every `/editor/mcp` and `/assets/mcp` request it checks the bearer token (signature, `typ`, expiry, audience, scope) and the client IP allowlist.
3. **Policy enforcement point.** It reads the JSON-RPC traffic (`policy.py`, `proxy.py`), refuses denied tools and paths outside `EDITORIAL_ROOT`, and rewrites `tools/list` and `initialize`.

## OAuth flow (MCP authorization spec 2025-06-18)

1. The client sends `POST /editor/mcp` without a token. The gateway answers `401` with `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/editor/mcp"`.
2. The client reads the protected resource metadata (RFC 9728), then the authorization server metadata (RFC 8414) at `/.well-known/oauth-authorization-server`. There is no OIDC.
3. The client calls `POST /register` (DCR). Its redirect URIs must match `GATEWAY_ALLOWED_REDIRECTS`. The `client_id` it receives is a signed token, so the gateway stores nothing.
4. The browser opens `GET /authorize` with PKCE S256 and an optional `resource`, which must be one of this gateway's resources (`/editor/mcp` or `/assets/mcp`). The owner approves on the consent page with `GATEWAY_OWNER_PASSWORD`.
5. The gateway redirects with `code`, `state` and `iss` (RFC 9207). Errors are redirected with `iss` too.
6. The client calls `POST /token` with the code and verifier. It gets an access token with `aud` set to the resource (1 h) and a refresh token (30 d, rotated on use).
7. The client calls `/editor/mcp` with the bearer token, and the proxy streams the traffic to scribus-mcp. The `Authorization`, `Cookie` and `Origin` headers are removed, and `Host` is set to localhost for FastMCP.

## Policy on the JSON-RPC stream

| Message | Gateway action |
|---|---|
| `tools/call` to a denied tool, or with a path outside the root | Answered by the gateway as `result.isError=true` with the reason. It never reaches the upstream. Audit log: `deny`. |
| `tools/call`, allowed | Path arguments are rewritten to their resolved absolute form, then forwarded. Audit log: `call` with the paths. |
| `tools/list` response (JSON or SSE) | Buffered (max 16 MB). Denied tools are removed and `securitySchemes` is added to each tool. |
| `initialize` response | The path rule is appended to `instructions`, so the model knows where it may write. |
| Anything else | Streamed through untouched, SSE included. |

The path jail needs the gateway to see the real filesystem so it can resolve symlinks. That's why `EDITORIAL_ROOT` is mounted read-only at the **same absolute path** in the gateway, the same path the MCP and your Scribus use.

## Design decisions

| Decision | Why |
|---|---|
| Use scribus-mcp from upstream and don't write our own MCP | The repo keeps one responsibility: exposing an MCP safely. |
| Enforce policy in the gateway, not in the MCP | It's upstream-agnostic, testable, and works the same in both modes. scribus-mcp has no path restrictions of its own. |
| Host mode puts the gateway and ngrok on the host network | The bridge only listens on host loopback. This is the only way to keep **everything** on 127.0.0.1 without exposing scribus-mcp to the LAN. |
| scribus-mcp runs in a dedicated uv venv under systemd `--user`, transient by default | Isolated from conda and the system Python. `make down` leaves nothing behind. Hardened with systemd properties. |
| Stateless HS256 tokens | No database. `make rotate` is the kill switch. |
| The issuer comes from proxy headers | Random ngrok URLs work without configuration. `PUBLIC_URL` pins the issuer when needed. |

## Multiple protected resources

Each resource has its own protected resource metadata (`/.well-known/oauth-protected-resource/<path>`), its own `WWW-Authenticate` challenge and its own audience. A token for `/mcp` gets a 401 on `/assets/mcp`, and vice versa. Both resources share one authorization server, one consent password and one signing key.

## Known limits

- Single replica. The used-code set and the rate limiter live in memory.
- Tokens can't be revoked one at a time.
- Container mode can't drive the desktop Scribus (see [scribus-mcp.md](scribus-mcp.md)).
- Images from ChatGPT reach Scribus through `EDITORIAL_ROOT/inbox` by hand for now ([host-mode.md](host-mode.md)).
