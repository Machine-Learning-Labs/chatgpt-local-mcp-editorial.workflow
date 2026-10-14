from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app

from .conftest import make_settings


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_protected_resource_metadata(client):
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/editor/mcp",
    ):
        body = client.get(path).json()
        assert body["resource"] == "https://gw.example.test/editor/mcp"
        assert body["authorization_servers"] == ["https://gw.example.test"]


def test_authorization_server_metadata(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == "https://gw.example.test"
    assert body["token_endpoint"] == "https://gw.example.test/token"
    assert body["registration_endpoint"] == "https://gw.example.test/register"
    assert body["code_challenge_methods_supported"] == ["S256"]


def test_issuer_follows_forwarded_headers(client):
    body = client.get(
        "/.well-known/oauth-authorization-server",
        headers={
            "x-forwarded-proto": "https",
            "host": "abc.ngrok-free.app",
        },
    ).json()
    assert body["issuer"] == "https://abc.ngrok-free.app"


def test_issuer_uses_host_and_only_trusted_forwarded_proto():
    """ngrok appends to X-Forwarded-Proto and passes a client-supplied X-Forwarded-Host
    through, so the issuer is Host + the LAST proto hop, and only from a trusted peer."""
    from starlette.requests import Request

    from mcp_oauth_gateway.oauth import base_url

    settings = make_settings()

    def req(peer: str, headers: dict) -> Request:
        return Request(
            {
                "type": "http",
                "scheme": "http",
                "server": ("127.0.0.1", 8080),
                "path": "/",
                "query_string": b"",
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                "client": (peer, 1),
            }
        )

    ngrok = {
        "host": "abc.ngrok-free.app",
        "x-forwarded-proto": "http, https",
        "x-forwarded-host": "evil.example",
    }
    assert base_url(req("127.0.0.1", ngrok), settings) == "https://abc.ngrok-free.app"
    # an untrusted peer cannot upgrade the scheme, nor rename the host
    direct = {"host": "127.0.0.1:8080", "x-forwarded-proto": "https", "x-forwarded-host": "e"}
    assert base_url(req("198.51.100.1", direct), settings) == "http://127.0.0.1:8080"


def test_public_url_overrides_headers():
    app = create_app(make_settings(public_url="https://fixed.example"))
    with TestClient(app) as client:
        body = client.get(
            "/.well-known/oauth-authorization-server", headers={"host": "other.example"}
        ).json()
    assert body["issuer"] == "https://fixed.example"


def test_cors_preflight_exposes_session_header(client):
    response = client.options(
        "/editor/mcp",
        headers={
            "origin": "https://claude.ai",
            "access-control-request-method": "POST",
            "access-control-request-headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] in {"*", "https://claude.ai"}


def test_editor_path_replaces_bare_mcp(client):
    assert client.post("/mcp", json={}).status_code == 404
    assert client.get("/.well-known/oauth-protected-resource/mcp").status_code == 404
    bare = client.get("/.well-known/oauth-protected-resource").json()
    assert bare["resource"] == "https://gw.example.test/editor/mcp"
    assert client.get("/").json()["editor"] == "/editor/mcp"
