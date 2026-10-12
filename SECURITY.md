# Security

This project puts a program that can run Scribus, and optionally arbitrary Python, on the public internet. The gateway is the only safeguard, so treat it accordingly.

The full threat model and the controls are in [docs/security.md](docs/security.md).

## Recommendations

- Keep `GATEWAY_AUTO_APPROVE=false`, and use a long owner password (the generated one is 20 characters).
- Keep the default `POLICY_DENY_TOOLS`. Point `EDITORIAL_ROOT` at a dedicated folder, never at `$HOME`.
- Restrict `GATEWAY_ALLOWED_CLIENT_CIDRS` to OpenAI's published connector ranges if you only use ChatGPT.
- Review the audit log with `make logs s=gateway`.
- Run `make rotate` if you suspect a token or the `.env` file has leaked.
- `make down` when you're not using it.

## Reporting a vulnerability

Please open a private security advisory on GitHub (*Security → Report a vulnerability*) instead of a public issue. Include steps to reproduce. We aim to answer within 7 days.
