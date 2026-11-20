"""Command line entry point: ``mcp-oauth-gateway serve | token``."""

from __future__ import annotations

import argparse
import json
import sys

from .config import EDITOR_PATH, Settings
from .oauth import OAuthServer


def _serve(args: argparse.Namespace, settings: Settings) -> int:
    import logging

    import uvicorn

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    from .app import create_app

    # proxy_headers stays OFF: uvicorn would replace the client address with the FIRST
    # X-Forwarded-For hop, which the client itself controls (ngrok appends to the end).
    # The gateway reads the last hop from trusted proxies instead (network.py).
    uvicorn.run(
        create_app(settings),
        host=args.host or settings.host,
        port=args.port or settings.port,
        proxy_headers=False,
        log_level=args.log_level,
    )
    return 0


def _token(args: argparse.Namespace, settings: Settings) -> int:
    oauth = OAuthServer(settings)
    # The token is bound (aud) to one resource URL: the public one, or the local port.
    issuer = (args.public_url or settings.public_url or f"http://127.0.0.1:{settings.port}").rstrip(
        "/"
    )
    resource = "/" + args.resource.strip("/")
    token = oauth.mint_access_token(
        ttl=args.ttl, subject=args.subject, issuer=issuer, audience=f"{issuer}{resource}"
    )
    if args.json:
        print(
            json.dumps(
                {
                    "access_token": token,
                    "token_type": "Bearer",
                    "expires_in": args.ttl or settings.access_token_ttl,
                }
            )
        )
    else:
        print(token)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-oauth-gateway", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the OAuth gateway")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=_serve)

    token = sub.add_parser("token", help="mint an access token for the owner (no browser flow)")
    token.add_argument("--ttl", type=int, help="lifetime in seconds (default ACCESS_TOKEN_TTL)")
    token.add_argument("--subject", default="owner")
    token.add_argument("--public-url", help="issuer/audience, default PUBLIC_URL")
    token.add_argument(
        "--resource",
        default=EDITOR_PATH,
        help="resource path: /editor/mcp, /assets/mcp or /designcraft/mcp",
    )
    token.add_argument("--json", action="store_true", help="print an OAuth token response")
    token.set_defaults(func=_token)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
