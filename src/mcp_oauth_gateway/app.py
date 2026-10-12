"""ASGI application wiring: OAuth endpoints + protected /mcp proxy."""

from __future__ import annotations

import contextlib
import logging

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .config import Settings
from .oauth import OAuthServer
from .proxy import McpProxy, client_ip, ip_allowed

audit = logging.getLogger("mcp_oauth_gateway.audit")
UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=60.0, pool=10.0)
# Endpoints only machines call (ChatGPT/Claude backends): IP allowlist + small bodies.
_MACHINE_PATHS = {"/token", "/register"}
_MACHINE_MAX_BODY = 64 * 1024
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"content-security-policy",
        # No form-action: the consent form must be able to redirect to the client.
        b"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    ),
]


class GuardMiddleware:
    """Security headers on every response; IP allowlist and body cap on /token and /register."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] in _MACHINE_PATHS:
            request = Request(scope)
            length = request.headers.get("content-length", "")
            reason = None
            if not ip_allowed(request, self.settings):
                reason, status = "forbidden", 403
            elif length.isdigit() and int(length) > _MACHINE_MAX_BODY:
                reason, status = "payload_too_large", 413
            if reason:
                if status == 403:
                    audit.warning(
                        "deny ip=%s path=%s", client_ip(request, self.settings), scope["path"]
                    )
                await JSONResponse({"error": reason}, status_code=status)(scope, receive, send)
                return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _SECURITY_HEADERS if k not in names]
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)


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
        Route("/register", oauth.register, methods=["POST"]),
        Route("/authorize", oauth.authorize, methods=["GET", "POST"]),
        Route("/token", oauth.token, methods=["POST"]),
        Route("/mcp", proxy.handle, methods=methods),
        Route("/mcp/{path:path}", proxy.handle, methods=methods),
    ]
    middleware = [
        Middleware(GuardMiddleware, settings=settings),
        Middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id", "WWW-Authenticate", "Mcp-Protocol-Version"],
        ),
    ]
    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
    app.state.oauth = oauth
    return app
