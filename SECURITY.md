# Security

This project puts a program that can run Scribus, and optionally arbitrary Python, on the public internet. The gateway is the only safeguard, so treat it accordingly.

## Recommendations

- Keep `GATEWAY_AUTO_APPROVE=false`, and use a long owner password (the generated one is 20 characters).
- Keep `SCRIBUS_MCP_RUN_SCRIPT=0` unless you have a specific need.
- Mount only the folder you want to share as `WORKSPACE_DIR`.
- In host mode, firewall `HOST_MCP_PORT`, because scribus-mcp itself has no authentication.
- Run `make rotate` if you suspect a token or the `.env` file has leaked.
- `make down` when you're not using it.

## Reporting a vulnerability

Please open a private security advisory on GitHub (*Security → Report a vulnerability*) instead of a public issue. Include steps to reproduce. We aim to answer within 7 days.
