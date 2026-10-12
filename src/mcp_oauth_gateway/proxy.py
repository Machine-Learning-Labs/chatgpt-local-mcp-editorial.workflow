"""Bearer-protected streaming reverse proxy to the upstream MCP (Streamable HTTP / SSE)."""

from __future__ import annotations

import logging

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .oauth import OAuthServer, base_url
from .tokens import TokenError

log = logging.getLogger(__name__)

# Hop-by-hop headers (RFC 9110 §7.6.1) plus the ones the proxy rewrites itself.
_DROP_REQUEST = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "authorization",
    "content-length",
    "cookie",
    # The gateway handles CORS itself; a browser Origin would trip the upstream's
    # DNS-rebinding protection (FastMCP answers 403).
    "origin",
}
_DROP_RESPONSE = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


class McpProxy:
    def __init__(self, oauth: OAuthServer, client_factory) -> None:
        self.oauth = oauth
        self.upstream = oauth.settings.upstream_url.rstrip("/")
        self._client_factory = client_factory

    def _unauthorized(self, request: Request, error: str | None = None) -> Response:
        metadata = (
            f"{base_url(request, self.oauth.settings)}/.well-known/oauth-protected-resource/mcp"
        )
        challenge = f'Bearer resource_metadata="{metadata}"'
        if error:
            challenge += f', error="invalid_token", error_description="{error}"'
        return JSONResponse(
            {
                "error": "invalid_token" if error else "unauthorized",
                "error_description": error or "Bearer token required",
            },
            status_code=401,
            headers={"WWW-Authenticate": challenge},
        )

    async def handle(self, request: Request) -> Response:
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return self._unauthorized(request)
        try:
            claims = self.oauth.verify_access_token(token.strip())
        except TokenError as exc:
            return self._unauthorized(request, str(exc))
        if "mcp" not in claims.get("scope", "").split():
            return JSONResponse(
                {"error": "insufficient_scope"},
                status_code=403,
                headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
            )

        suffix = request.path_params.get("path", "")
        url = self.upstream + (f"/{suffix}" if suffix else "")
        if request.url.query:
            url += f"?{request.url.query}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST}
        headers["x-forwarded-for"] = request.client.host if request.client else ""
        headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
        headers["x-mcp-subject"] = str(claims.get("sub", ""))
        if self.oauth.settings.upstream_host_header:
            # FastMCP bound to localhost only accepts Host: localhost/127.0.0.1 (else 421).
            headers["host"] = self.oauth.settings.upstream_host_header

        client: httpx.AsyncClient = self._client_factory()
        upstream_request = client.build_request(
            request.method,
            url,
            headers=headers,
            content=await request.body(),
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            log.warning("upstream MCP unreachable: %s", exc)
            return JSONResponse(
                {"error": "bad_gateway", "error_description": f"upstream MCP unreachable: {exc}"},
                status_code=502,
            )
        response_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE
        }
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(upstream.aclose),
        )
