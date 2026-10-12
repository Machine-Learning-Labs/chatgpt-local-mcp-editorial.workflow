import httpx
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.tokens import Signer

from .conftest import SECRET, full_flow, make_settings

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def test_missing_token_gets_challenge(client, upstream):
    response = client.post("/mcp", json=INIT)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert (
        'resource_metadata="https://gw.example.test/.well-known/oauth-protected-resource/mcp"'
        in challenge
    )
    assert upstream.requests == []


def test_invalid_token_rejected(client, upstream):
    forged = Signer("z" * 48).issue("access", 60, scope="mcp")
    response = client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert upstream.requests == []


def test_refresh_token_not_accepted_as_access(client):
    tokens = full_flow(client)
    response = client.post(
        "/mcp", json=INIT, headers={"authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


def test_expired_token_rejected(client):
    expired = Signer(SECRET).issue("access", 10, now=0, scope="mcp")
    response = client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_scope_required(client):
    token = Signer(SECRET).issue("access", 60, scope="other")
    response = client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_proxies_post_with_oauth_token(client, upstream):
    tokens = full_flow(client)
    response = client.post(
        "/mcp",
        json=INIT,
        headers={
            "authorization": f"Bearer {tokens['access_token']}",
            "accept": "application/json, text/event-stream",
            "mcp-session-id": "sess-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"] == {"echo": "initialize"}
    assert response.headers["mcp-session-id"] == "sess-1"
    forwarded = upstream.requests[-1]
    assert str(forwarded.url) == "http://upstream:8000/mcp"
    assert "authorization" not in forwarded.headers  # token never reaches the MCP
    assert forwarded.headers["mcp-session-id"] == "sess-1"
    assert forwarded.headers["x-mcp-subject"] == "owner"


def test_proxies_sse_get_and_subpath(client, upstream):
    token = client.app.state.oauth.mint_access_token()
    response = client.get("/mcp/stream?x=1", headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"event: message" in response.content
    assert str(upstream.requests[-1].url) == "http://upstream:8000/mcp/stream?x=1"


def test_delete_session(client, upstream):
    token = client.app.state.oauth.mint_access_token()
    client.delete("/mcp", headers={"authorization": f"Bearer {token}"})
    assert upstream.requests[-1].method == "DELETE"


def test_upstream_down_returns_502():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    app = create_app(make_settings(), upstream_transport=httpx.MockTransport(boom))
    with TestClient(app) as client:
        token = app.state.oauth.mint_access_token()
        response = client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 502
    assert response.json()["error"] == "bad_gateway"


def test_origin_not_forwarded(client, upstream):
    token = client.app.state.oauth.mint_access_token()
    client.post(
        "/mcp",
        json=INIT,
        headers={"authorization": f"Bearer {token}", "origin": "https://claude.ai"},
    )
    assert "origin" not in upstream.requests[-1].headers


def test_upstream_host_header_override(upstream):
    settings = make_settings(upstream_host_header="localhost:8000")
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    with TestClient(app) as client:
        token = app.state.oauth.mint_access_token()
        client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {token}"})
    assert upstream.requests[-1].headers["host"] == "localhost:8000"
    assert str(upstream.requests[-1].url) == "http://upstream:8000/mcp"


def test_host_header_defaults_to_upstream(client, upstream):
    token = client.app.state.oauth.mint_access_token()
    client.post("/mcp", json=INIT, headers={"authorization": f"Bearer {token}"})
    assert upstream.requests[-1].headers["host"] == "upstream:8000"
