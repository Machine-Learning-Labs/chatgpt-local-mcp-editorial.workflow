"""ASGI application wiring: OAuth endpoints + protected /mcp proxy."""

from __future__ import annotations

import contextlib

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import __version__
from .config import Settings
from .oauth import OAuthServer
from .proxy import McpProxy

UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)


def create_app(
    settings: Settings | None = None, upstream_transport: httpx.AsyncBaseTransport | None = None
) -> Starlette:
    settings = settings or Settings.from_env()
    oauth = OAuthServer(settings)
    state: dict[str, httpx.AsyncClient] = {}

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with httpx.AsyncClient(
            transport=upstream_transport, timeout=UPSTREAM_TIMEOUT, follow_redirects=False
        ) as client:
            state["client"] = client
            yield
        state.clear()

    proxy = McpProxy(oauth, lambda: state["client"])

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    async def root(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "service": "mcp-oauth-gateway",
                "mcp": "/mcp",
                "metadata": "/.well-known/oauth-authorization-server",
            }
        )

    methods = ["GET", "POST", "DELETE"]
    routes = [
        Route("/", root),
        Route("/healthz", healthz),
        Route("/.well-known/oauth-protected-resource", oauth.protected_resource_metadata),
        Route("/.well-known/oauth-protected-resource/mcp", oauth.protected_resource_metadata),
        Route("/.well-known/oauth-authorization-server", oauth.authorization_server_metadata),
        Route("/.well-known/oauth-authorization-server/mcp", oauth.authorization_server_metadata),
        Route("/.well-known/openid-configuration", oauth.authorization_server_metadata),
        Route("/register", oauth.register, methods=["POST"]),
        Route("/authorize", oauth.authorize, methods=["GET", "POST"]),
        Route("/token", oauth.token, methods=["POST"]),
        Route("/mcp", proxy.handle, methods=methods),
        Route("/mcp/{path:path}", proxy.handle, methods=methods),
    ]
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id", "WWW-Authenticate", "Mcp-Protocol-Version"],
        )
    ]
    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
    app.state.oauth = oauth
    return app
