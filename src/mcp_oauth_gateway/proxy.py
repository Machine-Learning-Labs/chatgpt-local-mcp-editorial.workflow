"""Bearer-protected reverse proxy to the upstream MCP (Streamable HTTP / SSE).

Every request: client IP allowlist → bearer token (signature, type, expiry, audience,
scope) → body size limit → JSON-RPC policy (tool deny list, path jail) → upstream.
``tools/list`` and ``initialize`` responses are buffered and rewritten (denied tools
removed, ``securitySchemes`` added, path rules appended to the server instructions);
everything else is streamed untouched.
"""

from __future__ import annotations

import ipaddress
import json
import logging

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .oauth import OAuthServer, base_url
from .policy import Policy, PolicyError
from .tokens import TokenError

log = logging.getLogger(__name__)
audit = logging.getLogger("mcp_oauth_gateway.audit")

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
# Responses to these methods are small and get rewritten by the policy.
_REWRITE_METHODS = {"tools/list", "initialize"}
_MAX_REWRITE_BYTES = 16 * 1024 * 1024


def client_ip(request: Request, settings: Settings) -> str:
    """Peer address, or the address ngrok appended to X-Forwarded-For when the peer is trusted."""
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _in(peer, settings.trusted_proxy_cidrs):
        # The proxy appends the real client last; anything before it is client-controlled.
        return forwarded.split(",")[-1].strip()
    return peer


def ip_allowed(request: Request, settings: Settings) -> bool:
    if not settings.allowed_client_cidrs:
        return True
    return _in(client_ip(request, settings), settings.allowed_client_cidrs)


def _in(ip: str, networks) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in net for net in networks)


class McpProxy:
    def __init__(self, oauth: OAuthServer, client_factory) -> None:
        self.oauth = oauth
        self.settings = oauth.settings
        self.policy = Policy.from_settings(oauth.settings)
        self.upstream = oauth.settings.upstream_url.rstrip("/")
        self._client_factory = client_factory

    def _unauthorized(self, request: Request, error: str | None = None) -> Response:
        metadata = f"{base_url(request, self.settings)}/.well-known/oauth-protected-resource/mcp"
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
        if not ip_allowed(request, self.settings):
            audit.warning("deny ip=%s path=/mcp", client_ip(request, self.settings))
            return JSONResponse({"error": "forbidden"}, status_code=403)

        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return self._unauthorized(request)
        try:
            claims = self.oauth.verify_access_token(
                token.strip(), audience=self.oauth.resource_url(request)
            )
        except TokenError as exc:
            return self._unauthorized(request, str(exc))
        if "mcp" not in claims.get("scope", "").split():
            return JSONResponse(
                {"error": "insufficient_scope"},
                status_code=403,
                headers={"WWW-Authenticate": 'Bearer error="insufficient_scope"'},
            )

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.settings.max_body_bytes:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        body = await request.body()
        if len(body) > self.settings.max_body_bytes:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)

        rewrite = False
        if request.method == "POST" and body:
            try:
                body, rewrite, refusal = self._apply_policy(body, claims)
            except ValueError:
                return _jsonrpc_error(None, -32700, "parse error")
            if refusal is not None:
                return refusal

        return await self._forward(request, body, claims, rewrite)

    # ------------------------------------------------------------------ policy
    def _apply_policy(self, body: bytes, claims: dict) -> tuple[bytes, bool, Response | None]:
        payload = json.loads(body)
        messages = payload if isinstance(payload, list) else [payload]
        rewrite = False
        changed = False
        for message in messages:
            if not isinstance(message, dict):
                continue
            method = message.get("method")
            if method in _REWRITE_METHODS:
                rewrite = True
            if method != "tools/call":
                continue
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            try:
                new_params, paths = self.policy.apply_call(params)
            except PolicyError as exc:
                audit.warning(
                    "deny sub=%s client=%s tool=%s reason=%s",
                    claims.get("sub"),
                    _short(claims.get("client_id")),
                    name,
                    exc,
                )
                if isinstance(payload, list):
                    return body, False, _jsonrpc_error(None, -32600, str(exc))
                return body, False, _tool_refusal(message.get("id"), str(exc))
            audit.info(
                "call sub=%s client=%s tool=%s paths=%s",
                claims.get("sub"),
                _short(claims.get("client_id")),
                name,
                paths,
            )
            if new_params != params:
                message["params"] = new_params
                changed = True
        if changed:
            body = json.dumps(payload).encode()
        return body, rewrite, None

    def _rewrite_message(self, message: dict) -> dict:
        result = message.get("result")
        if not isinstance(result, dict):
            return message
        if "tools" in result:
            return {**message, "result": self.policy.filter_tools_result(result)}
        if "serverInfo" in result and self.policy.root:
            note = self.policy.instructions_note()
            return {
                **message,
                "result": {**result, "instructions": (result.get("instructions") or "") + note},
            }
        return message

    def _rewrite_body(self, content: bytes, content_type: str) -> bytes:
        if content_type.startswith("text/event-stream"):
            out = []
            for line in content.decode("utf-8").split("\n"):
                if line.startswith("data:"):
                    data = line[5:].strip()
                    try:
                        message = json.loads(data)
                    except ValueError:
                        out.append(line)
                        continue
                    if isinstance(message, dict):
                        message = self._rewrite_message(message)
                    line = "data: " + json.dumps(message)
                out.append(line)
            return "\n".join(out).encode("utf-8")
        if content_type.startswith("application/json"):
            payload = json.loads(content)
            if isinstance(payload, list):
                payload = [self._rewrite_message(m) if isinstance(m, dict) else m for m in payload]
            elif isinstance(payload, dict):
                payload = self._rewrite_message(payload)
            return json.dumps(payload).encode()
        return content

    # ----------------------------------------------------------------- forward
    async def _forward(
        self, request: Request, body: bytes, claims: dict, rewrite: bool
    ) -> Response:
        suffix = request.path_params.get("path", "")
        url = self.upstream + (f"/{suffix}" if suffix else "")
        if request.url.query:
            url += f"?{request.url.query}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST}
        headers["x-forwarded-for"] = client_ip(request, self.settings)
        headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
        headers["x-mcp-subject"] = str(claims.get("sub", ""))
        if self.settings.upstream_host_header:
            # FastMCP bound to localhost only accepts Host: localhost/127.0.0.1 (else 421).
            headers["host"] = self.settings.upstream_host_header

        client: httpx.AsyncClient = self._client_factory()
        upstream_request = client.build_request(request.method, url, headers=headers, content=body)
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
        if rewrite and upstream.status_code == 200:
            try:
                content = await _read_limited(upstream, _MAX_REWRITE_BYTES)
                content = self._rewrite_body(content, upstream.headers.get("content-type", ""))
            except (ValueError, UnicodeDecodeError):
                log.warning("could not rewrite upstream response; refusing to pass it unfiltered")
                return JSONResponse({"error": "bad_gateway"}, status_code=502)
            finally:
                await upstream.aclose()
            response_headers.pop("content-encoding", None)
            return Response(content, status_code=200, headers=response_headers)
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(upstream.aclose),
        )


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            raise ValueError("upstream response too large to rewrite")
        chunks.append(chunk)
    return b"".join(chunks)


def _tool_refusal(request_id, message: str) -> JSONResponse:
    """A tool result the model can read and recover from (not a transport error)."""
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": f"Refused: {message}"}],
                "isError": True,
            },
        }
    )


def _jsonrpc_error(request_id, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=400,
    )


def _short(value) -> str:
    text = str(value or "")
    return text if len(text) <= 16 else f"{text[:6]}…{text[-6:]}"
