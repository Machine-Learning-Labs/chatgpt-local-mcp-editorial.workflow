"""``editorial-assets serve``: run the assets MCP server (behind the OAuth gateway)."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import AssetsSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="editorial-assets", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the MCP server (Streamable HTTP on /mcp)")
    serve.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    try:
        settings = AssetsSettings.from_env()
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    import uvicorn

    from .server import build_asgi

    app = build_asgi(settings)
    uvicorn.run(
        app, host=settings.host, port=settings.port, log_level=args.log_level, proxy_headers=False
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
