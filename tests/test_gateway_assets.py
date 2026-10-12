import json
import secrets

import httpx
import pytest
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.tokens import pkce_s256

from .conftest import BASE, REDIRECT, _stream, make_settings, register, token_for

ASSETS = f"{BASE}/assets/mcp"


class Upstreams:
    """Two fake upstreams: scribus (upstream:8000) and assets (assets:8766)."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.startswith("/upload/"):
            return httpx.Response(200, html=f"<p>{request.method} upload ok</p>")
        body = json.loads(request.content or b"{}")
        if body.get("method") == "tools/list":
            tool = {
                "name": "import_image",
                "inputSchema": {},
                "_meta": {"openai/fileParams": ["image"]},
            }
            result = {"tools": [tool]}
        else:
            result = {"host": request.url.host, "params": body.get("params")}
        payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_stream(payload)
        )


@pytest.fixture
def upstreams():
    return Upstreams()


@pytest.fixture
def client(upstreams):
    settings = make_settings(
        assets_upstream_url="http://assets:8766/mcp",
        assets_upstream_host_header="localhost:8766",
        assets_max_upload_bytes=1000,
    )
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstreams))
    with TestClient(app, base_url=BASE) as test_client:
        yield test_client


def auth(app, path):
    return {"authorization": f"Bearer {token_for(app, audience=BASE + path)}"}


def test_protected_resource_metadata_per_resource(client):
    assets = client.get("/.well-known/oauth-protected-resource/assets/mcp").json()
    assert assets["resource"] == ASSETS and assets["resource_name"] == "Editorial Assets"
    scribus = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert scribus["resource"] == f"{BASE}/mcp"
    assert client.get("/.well-known/oauth-authorization-server/assets/mcp").status_code == 200


def test_assets_disabled_by_default():
    with TestClient(create_app(make_settings()), base_url=BASE) as client:
        assert client.get("/.well-known/oauth-protected-resource/assets/mcp").status_code == 404
        assert client.post("/assets/mcp", json={}).status_code == 404
        assert client.get("/upload/x").status_code == 404


def test_challenge_points_to_assets_metadata(client):
    response = client.post("/assets/mcp", json={})
    assert response.status_code == 401
    assert "oauth-protected-resource/assets/mcp" in response.headers["www-authenticate"]


def test_tokens_are_not_interchangeable_between_resources(client, upstreams):
    scribus_token = auth(client.app, "/mcp")
    assets_token = auth(client.app, "/assets/mcp")
    assert client.post("/assets/mcp", json={}, headers=scribus_token).status_code == 401
    assert client.post("/mcp", json={}, headers=assets_token).status_code == 401
    assert upstreams.requests == []


def test_authorize_accepts_assets_resource(client):
    reg = register(client)
    verifier = secrets.token_urlsafe(48)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": pkce_s256(verifier),
            "code_challenge_method": "S256",
            "resource": ASSETS,
        },
    )
    assert response.status_code == 200  # consent page, not invalid_target


def test_assets_proxy_routes_to_assets_upstream(client, upstreams):
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "list_assets", "arguments": {"folder": "libro/assets"}},
    }
    response = client.post("/assets/mcp", json=call, headers=auth(client.app, "/assets/mcp"))
    assert response.status_code == 200
    forwarded = upstreams.requests[-1]
    assert str(forwarded.url) == "http://assets:8766/mcp"
    assert forwarded.headers["host"] == "localhost:8766"
    assert forwarded.headers["x-forwarded-host"] == "gw.example.test"
    assert forwarded.headers["x-forwarded-proto"] == "https"
    assert "authorization" not in forwarded.headers


def test_tools_list_keeps_file_params_meta(client):
    listing = client.post(
        "/assets/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=auth(client.app, "/assets/mcp"),
    ).json()
    meta = listing["result"]["tools"][0]["_meta"]
    assert meta["openai/fileParams"] == ["image"]
    assert meta["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]


def test_upload_passthrough_without_bearer(client, upstreams):
    page = client.get("/upload/tok123")
    assert page.status_code == 200 and "GET upload ok" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-frame-options"] == "DENY"
    forwarded = upstreams.requests[-1]
    assert str(forwarded.url) == "http://assets:8766/upload/tok123"
    assert forwarded.headers["host"] == "localhost:8766"
    posted = client.post("/upload/tok123", files={"file": ("a.png", b"x" * 100, "image/png")})
    assert "POST upload ok" in posted.text


def test_upload_body_cap(client, upstreams):
    response = client.post("/upload/tok", files={"file": ("a.png", b"x" * 5000, "image/png")})
    assert response.status_code == 413
    assert upstreams.requests == []


def test_upload_route_only_accepts_single_segment(client):
    assert client.get("/upload/a/../../mcp").status_code in (404, 401)
