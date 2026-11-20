# Security model

The asset being protected is your desktop session. An authorized MCP client can drive Scribus (and, if enabled, a headless DesignCraft), and in host mode both run as **you**. The gateway is the only door, so every control lives there or in front of it.

## Assumptions

- **One user, one machine.** The stack is meant for your own desktop. scribus-mcp, the assets server and the DesignCraft bridge listen on 127.0.0.1 without authentication of their own, so they trust every local process. See [Other users on this machine](#other-users-on-this-machine).
- `EDITORIAL_ROOT` is a dedicated folder. `bin/setup` and `bin/check` refuse `/`, `$HOME` and any parent of `$HOME`.
- The tunnel is the ngrok agent, which appends to `X-Forwarded-For` and `X-Forwarded-Proto`, and forwards `Host` unchanged. Behind a different reverse proxy, set `PUBLIC_URL` and `GATEWAY_TRUSTED_PROXIES`.

## Threats considered

| Threat | Controls |
|---|---|
| A stranger finds the ngrok URL | OAuth 2.1. Every new client must be approved on the consent page with `GATEWAY_OWNER_PASSWORD`, and failed attempts are rate-limited (5 every 10 minutes per client IP). Optionally, `GATEWAY_ALLOWED_CLIENT_CIDRS`. |
| A malicious client registers itself | `GATEWAY_ALLOWED_REDIRECTS` restricts DCR redirect URIs by exact scheme and host, then path prefix (ChatGPT, Claude and loopback by default). Anyone can still register a client with any name and send you its consent link, so the consent page says so: deny anything you did not start yourself. |
| A stolen authorization code or token is replayed | PKCE S256 is mandatory and the verifier is validated against RFC 7636 before use. Codes are single-use and last 120 s. Tokens are audience-bound (RFC 8707 `resource` becomes `aud`, which the proxy checks). RFC 9207 `iss` protects against mix-up attacks. `make rotate` revokes everything. |
| A request forges `X-Forwarded-*` headers | uvicorn's own proxy-header rewriting is **off**: it would hand the application the *first* `X-Forwarded-For` hop, which the client controls. The gateway reads the **last** hop of `X-Forwarded-For` and `X-Forwarded-Proto`, and only when the TCP peer is in `GATEWAY_TRUSTED_PROXIES` (loopback in host mode). `X-Forwarded-Host` is never used: the issuer is `PUBLIC_URL` or the `Host` header. This is what the IP allowlist and the password rate limit rely on. |
| Prompt injection makes the model touch your files | **Path jail.** Every path argument must resolve inside `EDITORIAL_ROOT` (`realpath`, so symlinks, `..`, `~` and `file://` don't help). |
| Prompt injection runs code | **Tool deny list.** The policy hides and refuses `run_script`, `install_custom_font`, `set_js_action` and `create_pdf_push_button`. `SCRIBUS_MCP_RUN_SCRIPT` is forced to `0`. |
| Prompt injection drives DesignCraft outside the folder, prints, or reads the clipboard | The headless engine confines every file it reads or writes to `EDITORIAL_ROOT` itself (`--automation-read-root` / `--automation-write-root`, links followed). The gateway fails closed on top of that: an allow-list of tools (`key` is hidden because it runs command shortcuts), an allow-list of command namespaces, a deny list (`file.print`, system-clipboard paste, `script.run`…), strict `execute`/`batch` shapes (no `script` text), literal paths, and no JSON-RPC batches. The CLI runs with a private `HOME` and no display. Live window mode, which DesignCraft does not confine, is not supported. Details: [designcraft.md](designcraft.md). |
| A DesignCraft upgrade adds commands nobody reviewed | The service refuses to start unless `designcraft-cli --version` is `DESIGNCRAFT_VERSION`. `bin/designcraft-audit` lists what changed since the reviewed snapshot. New tools and namespaces are refused until they're reviewed. |
| A malicious file arrives through the assets connector | Downloads are restricted to OpenAI file hosts, are SSRF-guarded (public IPs only, every redirect re-checked) and have a size cap. Images are strictly validated (magic bytes, pixel cap checked on the header before anything is decoded, full decode, no trailing data), written only inside `EDITORIAL_ROOT`, and never overwrite anything. Upload links are signed, single-use and expire after 15 minutes. Details: [assets-connector.md](assets-connector.md). |
| A token for one connector is used on another | Audiences are separate per resource (`/editor/mcp`, `/assets/mcp` and `/designcraft/mcp`). |
| Something on the LAN reaches the MCP | scribus-mcp, the assets server, the DesignCraft bridge, the gateway and the ngrok agent API all listen on 127.0.0.1. The bridge listens on 127.0.0.1 too, and requires a token from a 0600 file. `make check-live` verifies the bindings. |
| The token leaks to the MCP | The proxy strips the `Authorization`, `Cookie` and `Origin` headers. |
| Something on this machine reads the tunnel's traffic | The ngrok agent runs with `--inspect=false`. Its traffic inspector would otherwise keep a copy of every request, bearer tokens and the consent password included, on an API with no authentication. |
| Oversized requests or DoS | Body caps are enforced while the body streams in, so a chunked request without `Content-Length` is cut off too: `/editor/mcp` and `/assets/mcp` 4 MB (`GATEWAY_MAX_BODY_BYTES`), `/upload` 31 MB, `/token`, `/register` and the consent POST 64 KB. The assets server has its own cap. Containers run with `mem_limit` and `pids_limit`. |
| Clickjacking or leaks from the consent page | CSP `default-src 'none'`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `no-store`. |
| A container escape escalates privileges | Containers run with `cap_drop: ALL` and `no-new-privileges`. The gateway has a read-only root filesystem and mounts the folder read-only. |
| A compromised scribus-mcp or DesignCraft service | Each runs as a systemd user unit with `NoNewPrivileges`, `UMask=0077`, `RestrictAddressFamilies`, `RestrictSUIDSGID` and `LockPersonality`, from a dedicated venv with a fixed `PATH`. The DesignCraft unit also has `MemoryMax`, `TasksMax`, and an environment reduced to a private `HOME` and `PATH`. |
| A malicious or hijacked dependency | Every Python dependency is pinned with hashes (`uv.lock` and `containers/*/requirements.txt`, regenerated by `make lock`). The host runtime and the images install with `--require-hashes`. CI runs `pip-audit` on every set, Dependabot proposes updates, GitHub Actions are pinned by commit, and the ngrok image is pinned to its major version. |

Every tool call is written to the audit log (`make logs s=gateway`), allowed or denied, with the subject, client, tool and resolved paths. Argument contents are never logged.

## Restricting callers to ChatGPT's IPs

OpenAI publishes the egress ranges its connectors use. See [Authentication for plugins](https://developers.openai.com/plugins/build/auth), section "Client identification". Put them in `GATEWAY_ALLOWED_CLIENT_CIDRS`, comma separated. This allowlist applies to `/editor/mcp`, `/assets/mcp`, `/designcraft/mcp`, `/token` and `/register`. Your browser still reaches `/authorize`.

The client IP is the last `X-Forwarded-For` hop, and only when the TCP peer is a trusted proxy (`GATEWAY_TRUSTED_PROXIES`, loopback in host mode). ngrok appends the real address after anything the client sent, so a client can't spoof it. uvicorn is started with `proxy_headers=False` on purpose; turning it on would reintroduce the spoof.

## Other users on this machine

In host mode scribus-mcp (`127.0.0.1:8765`), the assets server (`127.0.0.1:8766`) and the DesignCraft bridge (`127.0.0.1:8767`) have no authentication: the gateway is the only intended caller, but any local process can connect. For a process running as **you** that changes nothing, because it could already drive Scribus and edit your files directly. For **another account** on the same machine it does matter: that user could drive your Scribus session and read or write files in `EDITORIAL_ROOT` as you, without the gateway's path jail.

- `bin/check` warns when other login accounts exist.
- On a shared machine, prefer `MCP_MODE=container` (scribus-mcp is then reachable only on the compose network), or keep only your uid able to connect to those loopback ports. An nftables example, as root, with `1000` replaced by your uid:

  ```bash
  nft add table inet editorial
  nft add chain inet editorial out '{ type filter hook output priority 0; }'
  nft add rule inet editorial out oif lo tcp dport { 8765, 8766, 8767 } meta skuid != 1000 reject
  ```

  Rootless Podman maps the containers' root to your uid, so the gateway still gets through.

## Residual risks (accepted)

- Inside `EDITORIAL_ROOT`, an authorized client can overwrite or delete your documents. Keep backups or use git for that folder.
- `render_page_to_image` (Scribus), `render_page` (DesignCraft) and the export tools return the content of documents inside the root to the client. That's the whole point of the tool.
- Tokens can't be revoked one at a time, because they're stateless. A refresh token is re-issued on use, but the previous one stays valid until it expires (30 days by default, `REFRESH_TOKEN_TTL`). `make rotate` revokes all of them.
- Single-use upload links carry their token in the URL, so it appears in the uvicorn access logs. The link expires in 15 minutes and burns on first use.
- `create_uri_annotation` and `create_file_annotation` can put arbitrary links into an exported PDF. That's document content under your review, not system access.
- On the free ngrok plan, the consent page shows the ngrok interstitial first.
- In host mode, scribus-mcp has no filesystem sandbox of its own. User units can't use `ProtectHome` without breaking the GUI sockets. The path jail in the gateway is the control that applies.
