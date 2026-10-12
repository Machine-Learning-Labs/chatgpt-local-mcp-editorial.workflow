# Architecture

```
MCP client ──HTTPS──▶ ngrok edge ──▶ ngrok agent ──HTTP──▶ gateway:8080 ──HTTP──▶ scribus-mcp:8000/mcp
(claude.ai, Claude Code,             (container)           (container)            (container, or the host
 ChatGPT, Inspector…)                                                              in host mode)
```

## OAuth flow (MCP authorization spec, 2025-06-18)

1. The client sends `POST /mcp` without a token. The gateway answers `401` with
   `WWW-Authenticate: Bearer resource_metadata="<origin>/.well-known/oauth-protected-resource/mcp"`.
2. The client reads the **protected resource metadata** (RFC 9728) and finds the authorization server, which is the gateway itself.
3. The client reads `/.well-known/oauth-authorization-server` (RFC 8414).
4. The client registers itself at `POST /register` (RFC 7591). The returned `client_id` is a signed token that holds the client's redirect URIs and name, so the gateway stores nothing.
5. The client sends the user's browser to `GET /authorize` with PKCE S256. The gateway shows a consent page with the client name and its redirect URI, and the owner approves with `GATEWAY_OWNER_PASSWORD`.
6. The gateway redirects back with a single-use code that is valid for 120 s. The client calls `POST /token` with the code and `code_verifier`, and gets an access token (1 h) and a refresh token (30 d, rotated on use).
7. The client calls `/mcp` with `Authorization: Bearer …`. The gateway checks the signature, `typ=access`, expiry and the `mcp` scope. It then streams the request to the upstream (JSON or SSE, both directions) with the Authorization header **removed**.

`bin/token` skips steps 1–6. It mints an access token directly with the signing key, for clients that only accept static headers.

## Design decisions

| Decision | Why |
|---|---|
| Use scribus-mcp from upstream and don't write our own MCP | The repo keeps one responsibility: exposing an MCP safely. Scribus features are maintained upstream. |
| One component is both the authorization server and the resource server | It's a single-owner local tool. A separate IdP such as Keycloak or Auth0 would add operational weight for no benefit. |
| Stateless HS256 tokens (stdlib) | No database, no volume, and restarts are harmless. Rotating the key is the kill switch. |
| The issuer comes from `X-Forwarded-Proto` + `Host` | Random ngrok URLs work without extra configuration. `PUBLIC_URL` pins the issuer when needed. |
| Rewrite `Host`, drop `Origin` | FastMCP's DNS-rebinding guard accepts only localhost. The gateway already authenticates the caller and handles CORS. |
| Consent requires a password | DCR is open by design (MCP clients need it). The password stops strangers who find the URL. |
| Compose profiles for the mode | In `host` mode the `scribus-mcp` service doesn't exist, and the gateway reaches `host.docker.internal`. |

## Known limits

- Single replica. The used-code set and the rate limiter live in memory.
- Tokens can't be revoked one by one. `make rotate` revokes all of them.
- `aud` is set but isn't enforced, because the gateway protects exactly one resource.
- On the free ngrok plan, the browser sees an ngrok interstitial page the first time it opens `/authorize`. API clients aren't affected.
