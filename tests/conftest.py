from __future__ import annotations

import json
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.config import Settings
from mcp_oauth_gateway.tokens import pkce_s256

SECRET = "x" * 48
PASSWORD = "correct horse battery staple"
REDIRECT = "http://127.0.0.1:33418/callback"


class FakeUpstream:
    """Records what the gateway forwards and answers like a Streamable HTTP MCP."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.tools = ["create_document", "load_image", "run_script", "set_js_action"]
        self.sse = False
        self.eol = "\n"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_stream(b"event: message\ndata: {}\n\n"),
            )
        body = json.loads(request.content or b"{}")
        result = {"echo": body.get("method"), "params": body.get("params")}
        if body.get("method") == "tools/list":
            result = {"tools": [{"name": n, "inputSchema": {}} for n in self.tools]}
        elif body.get("method") == "initialize":
            result = {"serverInfo": {"name": "fake"}, "instructions": "Fake MCP."}
        payload = {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
        if self.sse:
            eol = self.eol
            data = f"event: message{eol}data: {json.dumps(payload)}{eol}{eol}".encode()
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream", "mcp-session-id": "sess-1"},
                content=_stream(data),
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "mcp-session-id": "sess-1"},
            content=_stream(json.dumps(payload).encode()),
        )


async def _stream(data: bytes):
    """Real network responses are lazy; bytes content would be pre-read by httpx."""
    yield data


def make_settings(**overrides) -> Settings:
    values = dict(secret=SECRET, owner_password=PASSWORD, upstream_url="http://upstream:8000/mcp")
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def client(settings, upstream):
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url="https://gw.example.test") as test_client:
        yield test_client


BASE = "https://gw.example.test"


def token_for(app, base: str = BASE, **kwargs) -> str:
    """Access token bound to the test client's resource URL (aud is enforced)."""
    return app.state.oauth.mint_access_token(issuer=base, **kwargs)


def bearer(app, base: str = BASE) -> dict:
    return {"authorization": f"Bearer {token_for(app, base)}"}


def register(client, redirect=REDIRECT, **extra) -> dict:
    response = client.post(
        "/register", json={"redirect_uris": [redirect], "client_name": "Test", **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client, reg: dict, verifier: str, redirect=REDIRECT, password=PASSWORD) -> dict:
    """Run the consent screen and return the redirect's query parameters."""
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": redirect,
            "code_challenge": pkce_s256(verifier),
            "code_challenge_method": "S256",
            "state": "st4te",
            "scope": "mcp",
        },
    )
    assert response.status_code == 200, response.text
    request_token = response.text.split('name=request value="')[1].split('"')[0]
    response = client.post(
        "/authorize",
        data={
            "request": request_token,
            "password": password,
            "decision": "approve",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    return {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}


def full_flow(client) -> dict:
    reg = register(client)
    verifier = secrets.token_urlsafe(48)
    params = authorize(client, reg, verifier)
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": params["code"],
            "redirect_uri": REDIRECT,
            "client_id": reg["client_id"],
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return {"registration": reg, **response.json()}
