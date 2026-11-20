"""OAuth 2.1 authorization server tailored to the MCP authorization spec.

Implements:
- RFC 9728 protected resource metadata
- RFC 8414 authorization server metadata
- RFC 7591 dynamic client registration (stateless: the client_id is a signed token)
- Authorization code + PKCE (S256 only); refresh tokens are re-issued on use (stateless,
  so the previous one stays valid until it expires: see docs/security.md)
- RFC 9207 ``iss`` in authorization responses, RFC 8707 resource/audience binding
"""

from __future__ import annotations

import base64
import hmac
import re
import time
from collections import defaultdict, deque
from urllib.parse import unquote_plus, urlencode, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .config import ASSETS_PATH, DESIGNCRAFT_PATH, EDITOR_PATH, Settings
from .network import client_ip, forwarded_proto
from .pages import consent_page, error_page
from .tokens import Signer, TokenError, pkce_s256

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
FORBIDDEN_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob"}
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
# RFC 7636 §4.1: 43-128 unreserved characters.
CODE_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def base_url(request: Request, settings: Settings) -> str:
    """Public origin of the gateway: PUBLIC_URL, or scheme + ``Host`` of the request.

    ``Host`` is what ngrok routes on and forwards unchanged. ``X-Forwarded-Host`` is
    ignored on purpose (ngrok passes a client-supplied one through), and
    ``X-Forwarded-Proto`` counts only from a trusted proxy (network.py).
    """
    if settings.public_url:
        return settings.public_url
    host = (request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{forwarded_proto(request, settings)}://{host}"


def valid_redirect_uri(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if not scheme or scheme in FORBIDDEN_SCHEMES or parts.fragment:
        return False
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return (parts.hostname or "") in LOOPBACK_HOSTS
    return True  # private-use URI scheme for native apps (RFC 8252 §7.1)


def redirect_matches(registered: list[str], requested: str) -> bool:
    if requested in registered:
        return True
    # RFC 8252 §7.3: loopback redirects may use any port.
    try:
        req = urlsplit(requested)
    except ValueError:
        return False
    if req.scheme != "http" or (req.hostname or "") not in LOOPBACK_HOSTS:
        return False
    for uri in registered:
        reg = urlsplit(uri)
        if (reg.scheme, reg.hostname, reg.path) == (req.scheme, req.hostname, req.path):
            return True
    return False


def redirect_allowed(uri: str, prefixes: tuple[str, ...]) -> bool:
    """Exact scheme/host(/port) match plus path prefix (no naive string prefix matching)."""
    if not prefixes:
        return True
    req = urlsplit(uri)
    for prefix in prefixes:
        allowed = urlsplit(prefix)
        if (req.scheme, req.hostname) != (allowed.scheme, allowed.hostname):
            continue
        if allowed.port is not None and req.port != allowed.port:
            continue
        if req.path.startswith(allowed.path):
            return True
    return False


def same_resource(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.rstrip("/") == b.rstrip("/")


def oauth_error(error: str, description: str, status: int = 400, **headers: str) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={**NO_STORE, **headers},
    )


class RateLimiter:
    """Sliding-window counter of failed password attempts per client IP."""

    def __init__(self, limit: int = 5, window: float = 600.0) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def blocked(self, key: str, now: float | None = None) -> bool:
        return len(self._prune(key, now or time.monotonic())) >= self.limit

    def fail(self, key: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        self._prune(key, now).append(now)


class UsedCodes:
    """Single-use enforcement for authorization codes (in-memory, expires with the code)."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def consume(self, jti: str, exp: float) -> bool:
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if jti in self._seen:
            return False
        self._seen[jti] = exp
        return True


class OAuthServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.signer = Signer(settings.secret)
        self.used_codes = UsedCodes()
        self.limiter = RateLimiter()

    # ------------------------------------------------------------------ metadata
    @property
    def resources(self) -> dict[str, str]:
        """Protected resources served by this gateway: path → display name."""
        found = {EDITOR_PATH: "Scribus editor"}
        if self.settings.assets_upstream_url:
            found[ASSETS_PATH] = "Editorial Assets"
        if self.settings.designcraft_upstream_url:
            found[DESIGNCRAFT_PATH] = "DesignCraft"
        return found

    def resource_url(self, request: Request, path: str = EDITOR_PATH) -> str:
        return f"{base_url(request, self.settings)}{path}"

    def known_resource(self, request: Request, resource: str) -> bool:
        return any(same_resource(resource, self.resource_url(request, p)) for p in self.resources)

    async def protected_resource_metadata(self, request: Request) -> Response:
        issuer = base_url(request, self.settings)
        # /.well-known/oauth-protected-resource[/<resource path>]; bare = the editor
        path = request.url.path.removeprefix("/.well-known/oauth-protected-resource") or EDITOR_PATH
        if path not in self.resources:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(
            {
                "resource": f"{issuer}{path}",
                "authorization_servers": [issuer],
                "bearer_methods_supported": ["header"],
                "scopes_supported": list(self.settings.scopes),
                "resource_name": self.resources[path],
            }
        )

    async def authorization_server_metadata(self, request: Request) -> Response:
        issuer = base_url(request, self.settings)
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "registration_endpoint": f"{issuer}/register",
                "scopes_supported": list(self.settings.scopes),
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True,
                "token_endpoint_auth_methods_supported": [
                    "none",
                    "client_secret_post",
                    "client_secret_basic",
                ],
            }
        )

    # -------------------------------------------------------------- registration
    async def register(self, request: Request) -> Response:
        try:
            meta = await request.json()
        except ValueError:
            return oauth_error("invalid_client_metadata", "body must be JSON")
        if not isinstance(meta, dict):
            return oauth_error("invalid_client_metadata", "body must be a JSON object")
        redirect_uris = meta.get("redirect_uris")
        if (
            not isinstance(redirect_uris, list)
            or not redirect_uris
            or not all(isinstance(u, str) and valid_redirect_uri(u) for u in redirect_uris)
        ):
            return oauth_error(
                "invalid_redirect_uri",
                "redirect_uris must use https, loopback http or a private-use scheme",
            )
        rejected = [
            u
            for u in redirect_uris
            if not redirect_allowed(u, self.settings.allowed_redirect_prefixes)
        ]
        if rejected:
            return oauth_error(
                "invalid_redirect_uri",
                f"redirect_uri not allowed by this gateway: {rejected[0]} "
                "(see GATEWAY_ALLOWED_REDIRECTS)",
            )
        auth_method = meta.get("token_endpoint_auth_method", "none")
        if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            return oauth_error("invalid_client_metadata", "unsupported token_endpoint_auth_method")
        grant_types = meta.get("grant_types") or ["authorization_code", "refresh_token"]
        if "authorization_code" not in grant_types:
            return oauth_error("invalid_client_metadata", "authorization_code grant is required")
        client_name = str(meta.get("client_name") or "MCP client")[:120]

        client_id = self.signer.issue(
            "client",
            None,
            redirect_uris=redirect_uris,
            name=client_name,
            auth=auth_method,
        )
        body = {
            "client_id": client_id,
            "client_id_issued_at": int(time.time()),
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": auth_method,
        }
        if auth_method != "none":
            body["client_secret"] = self.signer.derive("client-secret", client_id)
            body["client_secret_expires_at"] = 0
        return JSONResponse(body, status_code=201, headers=NO_STORE)

    def _client(self, client_id: str | None) -> dict | None:
        if not client_id:
            return None
        try:
            return self.signer.decode(client_id, typ="client")
        except TokenError:
            return None

    # ------------------------------------------------------------- authorization
    async def authorize(self, request: Request) -> Response:
        if request.method == "POST":
            return await self._authorize_decision(request)

        q = request.query_params
        client = self._client(q.get("client_id"))
        if client is None:
            return HTMLResponse(error_page("Unknown client_id. Register the client first."), 400)
        redirect_uri = q.get("redirect_uri") or (
            client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else ""
        )
        if not redirect_matches(client["redirect_uris"], redirect_uri):
            return HTMLResponse(error_page("redirect_uri does not match the registration."), 400)

        state = q.get("state")
        issuer = base_url(request, self.settings)

        def fail(error: str, description: str) -> Response:
            return _redirect(
                redirect_uri, error=error, error_description=description, state=state, iss=issuer
            )

        if q.get("response_type") != "code":
            return fail("unsupported_response_type", "only response_type=code is supported")
        challenge = q.get("code_challenge")
        if not challenge or q.get("code_challenge_method", "plain") != "S256":
            return fail("invalid_request", "PKCE with code_challenge_method=S256 is required")
        scope = q.get("scope") or " ".join(self.settings.scopes)
        unknown = set(scope.split()) - set(self.settings.scopes)
        if unknown:
            return fail("invalid_scope", f"unknown scope(s): {' '.join(sorted(unknown))}")
        resource = q.get("resource")
        if resource and not self.known_resource(request, resource):
            return fail("invalid_target", "resource is not served by this authorization server")

        request_token = self.signer.issue(
            "authz_request",
            600,
            client_id=q["client_id"],
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=challenge,
            scope=scope,
            resource=resource,
            issuer=issuer,
        )
        if self.settings.auto_approve:
            return self._issue_code(self.signer.decode(request_token, typ="authz_request"))
        return HTMLResponse(
            consent_page(
                client_name=client.get("name", "MCP client"),
                redirect_uri=redirect_uri,
                scope=scope,
                request_token=request_token,
            ),
            headers=NO_STORE,
        )

    async def _authorize_decision(self, request: Request) -> Response:
        form = await request.form()
        try:
            req = self.signer.decode(str(form.get("request", "")), typ="authz_request")
        except TokenError:
            return HTMLResponse(error_page("Authorization request expired, start again."), 400)
        if form.get("decision") != "approve":
            return _redirect(
                req["redirect_uri"],
                error="access_denied",
                error_description="the owner denied access",
                state=req.get("state"),
                iss=req.get("issuer"),
            )

        # Keyed by the real client address (last trusted X-Forwarded-For hop), so a
        # spoofed header can't reset the counter.
        ip = client_ip(request, self.settings) or "unknown"
        if self.limiter.blocked(ip):
            return HTMLResponse(error_page("Too many failed attempts. Wait 10 minutes."), 429)
        password = str(form.get("password", ""))
        if not hmac.compare_digest(password.encode(), self.settings.owner_password.encode()):
            self.limiter.fail(ip)
            client = self._client(req["client_id"]) or {}
            return HTMLResponse(
                consent_page(
                    client_name=client.get("name", "MCP client"),
                    redirect_uri=req["redirect_uri"],
                    scope=req["scope"],
                    request_token=str(form.get("request")),
                    error="Wrong password.",
                ),
                status_code=401,
                headers=NO_STORE,
            )
        return self._issue_code(req)

    def _issue_code(self, req: dict) -> Response:
        code = self.signer.issue(
            "code",
            self.settings.code_ttl,
            client_id=req["client_id"],
            redirect_uri=req["redirect_uri"],
            code_challenge=req["code_challenge"],
            scope=req["scope"],
            resource=req.get("resource"),
        )
        return _redirect(
            req["redirect_uri"], code=code, state=req.get("state"), iss=req.get("issuer")
        )

    # -------------------------------------------------------------------- token
    async def token(self, request: Request) -> Response:
        form = await request.form()
        client_id, client_secret = form.get("client_id"), form.get("client_secret")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                raw = base64.b64decode(auth[6:]).decode()
                basic_id, _, basic_secret = raw.partition(":")
            except (ValueError, UnicodeDecodeError):
                return oauth_error("invalid_client", "malformed basic auth", 401)
            client_id, client_secret = unquote_plus(basic_id), unquote_plus(basic_secret)

        client = self._client(str(client_id) if client_id else None)
        if client is None:
            return oauth_error("invalid_client", "unknown client", 401)
        if client.get("auth", "none") != "none":
            expected = self.signer.derive("client-secret", str(client_id))
            if not client_secret or not hmac.compare_digest(str(client_secret), expected):
                return oauth_error("invalid_client", "bad client credentials", 401)

        grant = form.get("grant_type")
        if grant == "authorization_code":
            return self._grant_code(form, str(client_id), request)
        if grant == "refresh_token":
            return self._grant_refresh(form, str(client_id), request)
        return oauth_error("unsupported_grant_type", f"grant_type {grant!r} is not supported")

    def _grant_code(self, form, client_id: str, request: Request) -> Response:
        try:
            code = self.signer.decode(str(form.get("code", "")), typ="code")
        except TokenError as exc:
            return oauth_error("invalid_grant", f"invalid authorization code: {exc}")
        if code["client_id"] != client_id:
            return oauth_error("invalid_grant", "code was issued to another client")
        if form.get("redirect_uri") and form.get("redirect_uri") != code["redirect_uri"]:
            return oauth_error("invalid_grant", "redirect_uri mismatch")
        verifier = str(form.get("code_verifier", ""))
        if not CODE_VERIFIER.match(verifier):
            return oauth_error("invalid_grant", "code_verifier must be 43-128 unreserved chars")
        if not hmac.compare_digest(pkce_s256(verifier), code["code_challenge"]):
            return oauth_error("invalid_grant", "PKCE verification failed")
        if not self.used_codes.consume(code["jti"], code["exp"]):
            return oauth_error("invalid_grant", "authorization code already used")
        return self._token_response(client_id, code["scope"], code.get("resource"), request)

    def _grant_refresh(self, form, client_id: str, request: Request) -> Response:
        try:
            refresh = self.signer.decode(str(form.get("refresh_token", "")), typ="refresh")
        except TokenError as exc:
            return oauth_error("invalid_grant", f"invalid refresh token: {exc}")
        if refresh["client_id"] != client_id:
            return oauth_error("invalid_grant", "refresh token was issued to another client")
        scope = str(form.get("scope") or refresh["scope"])
        if not set(scope.split()) <= set(refresh["scope"].split()):
            return oauth_error("invalid_scope", "cannot widen scope on refresh")
        return self._token_response(client_id, scope, refresh.get("aud"), request)

    def _token_response(
        self, client_id: str, scope: str, resource: str | None, request: Request
    ) -> Response:
        issuer = base_url(request, self.settings)
        audience = resource or f"{issuer}{EDITOR_PATH}"
        access = self.mint_access_token(
            scope=scope, client_id=client_id, issuer=issuer, audience=audience
        )
        refresh = self.signer.issue(
            "refresh",
            self.settings.refresh_token_ttl,
            client_id=client_id,
            scope=scope,
            aud=audience,
            iss=issuer,
        )
        return JSONResponse(
            {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": self.settings.access_token_ttl,
                "refresh_token": refresh,
                "scope": scope,
            },
            headers=NO_STORE,
        )

    def mint_access_token(
        self,
        *,
        scope: str | None = None,
        client_id: str = "cli",
        issuer: str | None = None,
        audience: str | None = None,
        ttl: int | None = None,
        subject: str = "owner",
    ) -> str:
        issuer = issuer or self.settings.public_url or None
        return self.signer.issue(
            "access",
            ttl if ttl is not None else self.settings.access_token_ttl,
            sub=subject,
            client_id=client_id,
            scope=scope or " ".join(self.settings.scopes),
            iss=issuer,
            aud=audience or (f"{issuer}{EDITOR_PATH}" if issuer else None),
        )

    def verify_access_token(self, token: str, audience: str | None = None) -> dict:
        """Signature, type and expiry; plus ``aud`` when the expected resource is given."""
        claims = self.signer.decode(token, typ="access")
        if audience is not None and not same_resource(claims.get("aud"), audience):
            raise TokenError("token audience does not match this resource")
        return claims


def _redirect(uri: str, **params: str | None) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    separator = "&" if urlsplit(uri).query else "?"
    return RedirectResponse(f"{uri}{separator}{query}", status_code=302, headers=NO_STORE)
