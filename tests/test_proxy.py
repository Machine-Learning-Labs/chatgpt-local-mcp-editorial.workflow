import ipaddress
import json

import httpx
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.tokens import Signer

from .conftest import BASE, SECRET, bearer, full_flow, make_settings, token_for

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def call(tool, **arguments):
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


# ----------------------------------------------------------------------------- auth
def test_missing_token_gets_challenge(client, upstream):
    response = client.post("/editor/mcp", json=INIT)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert (
        f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/editor/mcp"' in challenge
    )
    assert upstream.requests == []


def test_invalid_token_rejected(client, upstream):
    forged = Signer("z" * 48).issue("access", 60, scope="mcp", aud=f"{BASE}/editor/mcp")
    response = client.post("/editor/mcp", json=INIT, headers={"authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert upstream.requests == []


def test_refresh_token_not_accepted_as_access(client):
    tokens = full_flow(client)
    response = client.post(
        "/editor/mcp", json=INIT, headers={"authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


def test_expired_token_rejected(client):
    expired = Signer(SECRET).issue("access", 10, now=0, scope="mcp", aud=f"{BASE}/editor/mcp")
    response = client.post("/editor/mcp", json=INIT, headers={"authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_scope_required(client):
    token = Signer(SECRET).issue("access", 60, scope="other", aud=f"{BASE}/editor/mcp")
    response = client.post("/editor/mcp", json=INIT, headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_audience_must_match_resource(client, upstream):
    other = token_for(client.app, base="https://other.example")
    response = client.post("/editor/mcp", json=INIT, headers={"authorization": f"Bearer {other}"})
    assert response.status_code == 401
    assert "audience" in response.json()["error_description"]
    missing = Signer(SECRET).issue("access", 60, scope="mcp")
    response = client.post("/editor/mcp", json=INIT, headers={"authorization": f"Bearer {missing}"})
    assert response.status_code == 401
    assert upstream.requests == []


# ----------------------------------------------------------------------------- proxying
def test_proxies_post_with_oauth_token(client, upstream):
    tokens = full_flow(client)
    response = client.post(
        "/editor/mcp",
        json=call("create_document"),
        headers={
            "authorization": f"Bearer {tokens['access_token']}",
            "accept": "application/json, text/event-stream",
            "mcp-session-id": "sess-1",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["echo"] == "tools/call"
    assert response.headers["mcp-session-id"] == "sess-1"
    forwarded = upstream.requests[-1]
    assert str(forwarded.url) == "http://upstream:8000/mcp"
    assert "authorization" not in forwarded.headers  # token never reaches the MCP
    assert forwarded.headers["mcp-session-id"] == "sess-1"
    assert forwarded.headers["x-mcp-subject"] == "owner"


def test_proxies_sse_get_and_subpath(client, upstream):
    response = client.get("/editor/mcp/stream?x=1", headers=bearer(client.app))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"event: message" in response.content
    assert str(upstream.requests[-1].url) == "http://upstream:8000/mcp/stream?x=1"


def test_delete_session(client, upstream):
    client.delete("/editor/mcp", headers=bearer(client.app))
    assert upstream.requests[-1].method == "DELETE"


def test_upstream_down_returns_502():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    app = create_app(make_settings(), upstream_transport=httpx.MockTransport(boom))
    with TestClient(app, base_url=BASE) as client:
        response = client.post("/editor/mcp", json=INIT, headers=bearer(app))
    assert response.status_code == 502
    assert response.json()["error"] == "bad_gateway"


def test_origin_not_forwarded(client, upstream):
    client.post(
        "/editor/mcp", json=INIT, headers={**bearer(client.app), "origin": "https://claude.ai"}
    )
    assert "origin" not in upstream.requests[-1].headers


def test_upstream_host_header_override(upstream):
    settings = make_settings(upstream_host_header="localhost:8000")
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url=BASE) as client:
        client.post("/editor/mcp", json=INIT, headers=bearer(app))
    assert upstream.requests[-1].headers["host"] == "localhost:8000"
    assert str(upstream.requests[-1].url) == "http://upstream:8000/mcp"


def test_host_header_defaults_to_upstream(client, upstream):
    client.post("/editor/mcp", json=INIT, headers=bearer(client.app))
    assert upstream.requests[-1].headers["host"] == "upstream:8000"


def test_body_size_limit(upstream):
    app = create_app(
        make_settings(max_body_bytes=100), upstream_transport=httpx.MockTransport(upstream)
    )
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/editor/mcp",
            content=b"x" * 200,
            headers={**bearer(app), "content-type": "application/json"},
        )
    assert response.status_code == 413
    assert upstream.requests == []


def test_invalid_json_is_rejected(client, upstream):
    response = client.post(
        "/editor/mcp",
        content=b"{nope",
        headers={**bearer(client.app), "content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700
    assert upstream.requests == []


# ----------------------------------------------------------------------------- policy
def _policy_client(upstream, tmp_path, **overrides):
    root = tmp_path / "Editorial"
    (root / "inbox").mkdir(parents=True)
    settings = make_settings(policy_root=str(root), **overrides)
    app = create_app(settings, upstream_transport=httpx.MockTransport(upstream))
    return app, root


def test_tools_list_filters_denied_tools_and_adds_security_schemes(client, upstream):
    response = client.post("/editor/mcp", json=LIST, headers=bearer(client.app))
    tools = response.json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names == ["create_document", "load_image"]  # run_script, set_js_action hidden
    scheme = [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools[0]["securitySchemes"] == scheme
    assert tools[0]["_meta"]["securitySchemes"] == scheme


def test_tools_list_rewritten_in_sse_responses(client, upstream):
    upstream.sse = True
    response = client.post("/editor/mcp", json=LIST, headers=bearer(client.app))
    assert response.status_code == 200
    data = [ln for ln in response.text.splitlines() if ln.startswith("data:")]
    names = [t["name"] for t in json.loads(data[0][5:])["result"]["tools"]]
    assert "run_script" not in names and "load_image" in names


def test_sse_rewrite_preserves_crlf_and_streams_without_length(client, upstream):
    upstream.sse = True
    upstream.eol = "\r\n"  # FastMCP's framing
    response = client.post("/editor/mcp", json=LIST, headers=bearer(client.app))
    assert response.status_code == 200
    assert "content-length" not in response.headers
    body = response.content
    assert body.startswith(b"event: message\r\ndata: ")
    assert body.endswith(b"\r\n\r\n")
    assert body.count(b"\r\n") == 3 and body.count(b"\n") == 3  # no bare LF
    assert len(response.headers.get_list("date")) <= 1  # upstream date not duplicated


def test_allow_list_restricts_tools(upstream):
    app = create_app(
        make_settings(allow_tools=("load_image",)), upstream_transport=httpx.MockTransport(upstream)
    )
    with TestClient(app, base_url=BASE) as client:
        names = [
            t["name"]
            for t in client.post("/editor/mcp", json=LIST, headers=bearer(app)).json()["result"][
                "tools"
            ]
        ]
        refused = client.post("/editor/mcp", json=call("create_document"), headers=bearer(app))
    assert names == ["load_image"]
    assert refused.json()["result"]["isError"] is True


def test_denied_tool_call_never_reaches_upstream(client, upstream):
    response = client.post(
        "/editor/mcp", json=call("run_script", code="import os"), headers=bearer(client.app)
    )
    body = response.json()
    assert response.status_code == 200
    assert body["id"] == 3 and body["result"]["isError"] is True
    assert "disabled" in body["result"]["content"][0]["text"]
    assert upstream.requests == []


def test_path_inside_root_is_forwarded_resolved(upstream, tmp_path):
    app, root = _policy_client(upstream, tmp_path)
    with TestClient(app, base_url=BASE) as client:
        response = client.post(
            "/editor/mcp",
            json=call("load_image", name="img", path="inbox/../inbox/photo.png"),
            headers=bearer(app),
        )
    assert response.status_code == 200
    forwarded = json.loads(upstream.requests[-1].content)
    assert forwarded["params"]["arguments"]["path"] == str(root / "inbox" / "photo.png")


def test_paths_outside_root_are_refused(upstream, tmp_path):
    app, root = _policy_client(upstream, tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    (root / "escape").symlink_to(tmp_path)
    bad_values = [
        "/etc/passwd",
        str(root) + "/../secret.png",
        "../secret.png",
        "~/.ssh/id_rsa",
        "file:///etc/passwd",
        str(root / "escape" / "secret.png"),  # symlink pointing outside the root
        str(root) + "-evil/x.sla",  # sibling folder sharing the prefix
    ]
    with TestClient(app, base_url=BASE) as client:
        for value in bad_values:
            response = client.post(
                "/editor/mcp", json=call("save_document_as", path=value), headers=bearer(app)
            )
            assert response.json()["result"]["isError"] is True, value
    assert upstream.requests == []


def test_nested_and_alternative_path_arguments_are_checked(upstream, tmp_path):
    app, _ = _policy_client(upstream, tmp_path)
    with TestClient(app, base_url=BASE) as client:
        for args in (
            {"image_path": "/etc/hosts"},
            {"font_path": "/usr/share/fonts/x.ttf"},
            {"target_dir": "/var/tmp"},  # noqa: S108
            {"items": [{"path": "/etc/hosts"}]},
        ):
            response = client.post(
                "/editor/mcp", json=call("create_text_with_image", **args), headers=bearer(app)
            )
            assert response.json()["result"]["isError"] is True, args
    assert upstream.requests == []


def test_initialize_instructions_mention_root(upstream, tmp_path):
    app, root = _policy_client(upstream, tmp_path)
    with TestClient(app, base_url=BASE) as client:
        result = client.post("/editor/mcp", json=INIT, headers=bearer(app)).json()["result"]
    assert result["instructions"].startswith("Fake MCP.")
    assert str(root) in result["instructions"]


def test_batch_with_denied_call_is_rejected(client, upstream):
    batch = [INIT, call("run_script")]
    response = client.post("/editor/mcp", json=batch, headers=bearer(client.app))
    assert response.status_code == 400
    assert upstream.requests == []


# ----------------------------------------------------------------------------- network
def _ip_app(upstream):
    settings = make_settings(allowed_client_cidrs=(ipaddress.ip_network("203.0.113.0/24"),))
    return create_app(settings, upstream_transport=httpx.MockTransport(upstream))


def test_client_ip_allowlist_on_mcp(upstream):
    app = _ip_app(upstream)
    with TestClient(app, base_url=BASE) as client:
        # TestClient's peer is "testclient" (not a trusted proxy) → XFF ignored → denied
        denied = client.post(
            "/editor/mcp", json=INIT, headers={**bearer(app), "x-forwarded-for": "203.0.113.5"}
        )
    assert denied.status_code == 403
    assert upstream.requests == []


def test_client_ip_uses_last_forwarded_hop_from_trusted_proxy(upstream):
    from starlette.requests import Request

    from mcp_oauth_gateway.proxy import client_ip

    settings = make_settings()

    def req(peer, xff):
        scope = {
            "type": "http",
            "headers": [(b"x-forwarded-for", xff.encode())],
            "client": (peer, 1234),
        }
        return Request(scope)

    # spoofed first hop is ignored; ngrok's appended address wins
    assert client_ip(req("127.0.0.1", "6.6.6.6, 203.0.113.5"), settings) == "203.0.113.5"
    # untrusted peer: header ignored entirely
    assert client_ip(req("198.51.100.1", "203.0.113.5"), settings) == "198.51.100.1"


def test_token_endpoint_ip_allowlist(upstream):
    app = _ip_app(upstream)
    with TestClient(app, base_url=BASE) as client:
        assert client.post("/token", data={"grant_type": "x"}).status_code == 403
        assert client.post("/register", json={}).status_code == 403
        # browser-facing endpoints stay reachable
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200


def test_security_headers(client):
    response = client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_machine_endpoint_body_cap(client):
    response = client.post(
        "/register", content=b"x" * (65 * 1024), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
