# Security

This project puts a program that can run Scribus, and optionally arbitrary Python, on the public internet. The gateway is the only safeguard, so treat it accordingly.

The full threat model and the controls are in [docs/security.md](docs/security.md).

## Assumptions

- Your own desktop, one user. scribus-mcp and the assets server trust every local process (they listen on 127.0.0.1 without authentication). On a machine shared with other accounts, read "Other users on this machine" in [docs/security.md](docs/security.md).
- `EDITORIAL_ROOT` is a dedicated folder, never `$HOME`. The scripts refuse anything else.

## Recommendations

- Keep `GATEWAY_AUTO_APPROVE=false`, and use a long owner password (the generated one is 20 characters).
- Deny any consent request you did not start yourself. Anyone can register a client under any name.
- Keep the default `POLICY_DENY_TOOLS`.
- Restrict `GATEWAY_ALLOWED_CLIENT_CIDRS` to OpenAI's published connector ranges if you only use ChatGPT.
- Review the audit log with `make logs s=gateway`.
- Run `make rotate` if you suspect a token or the `.env` file has leaked.
- Keep dependencies pinned: after changing `pyproject.toml` or `SCRIBUS_MCP_VERSION`, run `make lock` and commit the result. CI audits the pinned sets with `pip-audit`.
- `make down` when you're not using it.

## Reporting a vulnerability

Please open a private security advisory on GitHub (*Security → Report a vulnerability*) instead of a public issue. Include steps to reproduce. We aim to answer within 7 days.
