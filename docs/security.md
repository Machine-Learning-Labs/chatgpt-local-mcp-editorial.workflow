# Security model

The asset being protected is your desktop session. An authorized MCP client can drive Scribus, and in host mode Scribus runs as **you**. The gateway is the only door, so every control lives there or in front of it.

## Threats considered

| Threat | Controls |
|---|---|
| A stranger finds the ngrok URL | OAuth 2.1. Every new client must be approved on the consent page with `GATEWAY_OWNER_PASSWORD`, and failed attempts are rate-limited (5 every 10 minutes per IP). Optionally, `GATEWAY_ALLOWED_CLIENT_CIDRS`. |
| A malicious client registers itself | `GATEWAY_ALLOWED_REDIRECTS` restricts DCR redirect URIs by exact scheme and host, then path prefix (ChatGPT, Claude and loopback by default). |
| A stolen authorization code or token is replayed | PKCE S256 is mandatory. Codes are single-use and last 120 s. Tokens are audience-bound (RFC 8707 `resource` becomes `aud`, which the proxy checks). RFC 9207 `iss` protects against mix-up attacks. `make rotate` revokes everything. |
| Prompt injection makes the model touch your files | **Path jail.** Every path argument must resolve inside `EDITORIAL_ROOT` (`realpath`, so symlinks, `..`, `~` and `file://` don't help). |
| Prompt injection runs code | **Tool deny list.** The policy hides and refuses `run_script`, `install_custom_font`, `set_js_action` and `create_pdf_push_button`. `SCRIBUS_MCP_RUN_SCRIPT` is forced to `0`. |
| Something on the LAN reaches the MCP | scribus-mcp, the gateway and the ngrok inspector all listen on 127.0.0.1. The bridge listens on 127.0.0.1 too, and requires a token from a 0600 file. `make check-live` verifies the bindings. |
| The token leaks to the MCP | The proxy strips the `Authorization`, `Cookie` and `Origin` headers. |
| Oversized requests or DoS | Body caps: `/mcp` 4 MB (`GATEWAY_MAX_BODY_BYTES`), `/token` and `/register` 64 KB. |
| Clickjacking or leaks from the consent page | CSP `default-src 'none'`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `no-store`. |
| A container escape escalates privileges | Containers run with `cap_drop: ALL` and `no-new-privileges`. The gateway has a read-only root filesystem and mounts the folder read-only. |
| A compromised scribus-mcp service | It runs as a systemd user unit with `NoNewPrivileges`, `UMask=0077`, `RestrictAddressFamilies`, `RestrictSUIDSGID` and `LockPersonality`, from a dedicated venv with a fixed `PATH`. |

Every tool call is written to the audit log (`make logs s=gateway`), allowed or denied, with the subject, client, tool and resolved paths. Argument contents are never logged.

## Restricting callers to ChatGPT's IPs

OpenAI publishes the egress ranges its connectors use. See [Authentication for plugins](https://developers.openai.com/plugins/build/auth), section "Client identification". Put them in `GATEWAY_ALLOWED_CLIENT_CIDRS`, comma separated. This allowlist applies to `/mcp`, `/token` and `/register`. Your browser still reaches `/authorize`.

The client IP is read from the last `X-Forwarded-For` hop, and only when the peer is a trusted proxy (`GATEWAY_TRUSTED_PROXIES`, which is loopback in host mode). A client therefore can't spoof it.

## Residual risks (accepted)

- Inside `EDITORIAL_ROOT`, an authorized client can overwrite or delete your documents. Keep backups or use git for that folder.
- `render_page_to_image` and the export tools return the content of documents inside the root to the client. That's the whole point of the tool.
- Tokens can't be revoked one at a time, because they're stateless. `make rotate` revokes all of them.
- On the free ngrok plan, the consent page shows the ngrok interstitial first.
- In host mode, scribus-mcp has no filesystem sandbox of its own. User units can't use `ProtectHome` without breaking the GUI sockets. The path jail in the gateway is the control that applies.
