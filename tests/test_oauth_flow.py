import base64
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from mcp_oauth_gateway.app import create_app
from mcp_oauth_gateway.oauth import RateLimiter, redirect_matches, valid_redirect_uri
from mcp_oauth_gateway.tokens import pkce_s256

from .conftest import REDIRECT, authorize, full_flow, make_settings, register


# ----------------------------------------------------------------------------- registration
@pytest.mark.parametrize(
    "uri,ok",
    [
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("http://localhost:3000/cb", True),
        ("http://127.0.0.1/cb", True),
        ("cursor://anysphere.cursor-retrieval/oauth/callback", True),
        ("http://evil.example/cb", False),
        ("javascript:alert(1)", False),
        ("https://claude.ai/cb#frag", False),
        ("https:///nohost", False),
    ],
)
def test_valid_redirect_uri(uri, ok):
    assert valid_redirect_uri(uri) is ok


def test_loopback_port_flexibility():
    assert redirect_matches(["http://127.0.0.1:1111/cb"], "http://127.0.0.1:2222/cb")
    assert not redirect_matches(["http://127.0.0.1:1111/cb"], "http://127.0.0.1:2222/other")
    assert not redirect_matches(["https://a.example/cb"], "https://a.example/cb2")


def test_register_rejects_bad_metadata(client):
    assert client.post("/register", json={"redirect_uris": ["http://evil/cb"]}).status_code == 400
    assert client.post("/register", json={}).status_code == 400
    assert client.post("/register", content=b"nope").status_code == 400
    assert (
        client.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT],
                "token_endpoint_auth_method": "private_key_jwt",
            },
        ).status_code
        == 400
    )


def test_public_client_has_no_secret(client):
    reg = register(client)
    assert reg["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in reg


# ----------------------------------------------------------------------------- happy path
def test_full_authorization_code_flow(client):
    tokens = full_flow(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == "mcp"
    claims = client.app.state.oauth.verify_access_token(tokens["access_token"])
    assert claims["aud"] == "https://gw.example.test/editor/mcp"


def test_state_is_returned(client):
    params = authorize(client, register(client), secrets.token_urlsafe(48))
    assert params["state"] == "st4te"


def test_refresh_token_grant(client):
    tokens = full_flow(client)
    response = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["registration"]["client_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["access_token"] != tokens["access_token"]


def test_refresh_cannot_widen_scope(client):
    tokens = full_flow(client)
    response = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["registration"]["client_id"],
            "scope": "mcp admin",
        },
    )
    assert response.json()["error"] == "invalid_scope"


def test_confidential_client_basic_auth(client):
    reg = register(client, token_endpoint_auth_method="client_secret_basic")
    verifier = secrets.token_urlsafe(48)
    code = authorize(client, reg, verifier)["code"]
    basic = base64.b64encode(f"{reg['client_id']}:{reg['client_secret']}".encode()).decode()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT,
    }
    bad = client.post("/token", data=data, headers={"authorization": "Basic Zm9vOmJhcg=="})
    assert bad.status_code == 401
    ok = client.post("/token", data=data, headers={"authorization": f"Basic {basic}"})
    assert ok.status_code == 200, ok.text


def test_auto_approve_skips_consent():
    app = create_app(make_settings(auto_approve=True, owner_password=""))
    with TestClient(app) as client:
        reg = register(client)
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": reg["client_id"],
                "redirect_uri": REDIRECT,
                "code_challenge": pkce_s256("v" * 50),
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "code=" in response.headers["location"]


# ----------------------------------------------------------------------------- failures
def test_code_is_single_use(client):
    reg = register(client)
    verifier = secrets.token_urlsafe(48)
    code = authorize(client, reg, verifier)["code"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": reg["client_id"],
        "code_verifier": verifier,
        "redirect_uri": REDIRECT,
    }
    assert client.post("/token", data=data).status_code == 200
    replay = client.post("/token", data=data)
    assert replay.status_code == 400 and "already used" in replay.json()["error_description"]


def test_wrong_pkce_verifier(client):
    reg = register(client)
    code = authorize(client, reg, "a" * 50)["code"]
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": reg["client_id"],
            "code_verifier": "b" * 50,
        },
    )
    assert response.json()["error"] == "invalid_grant"


def test_code_bound_to_client(client):
    reg_a, reg_b = register(client), register(client)
    verifier = secrets.token_urlsafe(48)
    code = authorize(client, reg_a, verifier)["code"]
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": reg_b["client_id"],
            "code_verifier": verifier,
        },
    )
    assert response.json()["error"] == "invalid_grant"


def test_unknown_client_at_token(client):
    response = client.post(
        "/token", data={"grant_type": "authorization_code", "client_id": "forged"}
    )
    assert response.status_code == 401


def test_unsupported_grant(client):
    reg = register(client)
    response = client.post("/token", data={"grant_type": "password", "client_id": reg["client_id"]})
    assert response.json()["error"] == "unsupported_grant_type"


def test_authorize_requires_pkce(client):
    reg = register(client)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error=invalid_request" in response.headers["location"]


def test_authorize_unknown_client_does_not_redirect(client):
    response = client.get(
        "/authorize", params={"client_id": "nope", "redirect_uri": REDIRECT}, follow_redirects=False
    )
    assert response.status_code == 400


def test_authorize_rejects_unregistered_redirect(client):
    reg = register(client)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": "https://attacker.example/cb",
            "code_challenge": "x",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_authorize_rejects_unknown_scope(client):
    reg = register(client)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": "x",
            "code_challenge_method": "S256",
            "scope": "mcp admin",
        },
        follow_redirects=False,
    )
    assert "error=invalid_scope" in response.headers["location"]


def _consent_token(client, reg):
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "state": "s",
        },
    )
    return response.text.split('name=request value="')[1].split('"')[0]


def test_wrong_password_shows_form_again(client):
    token = _consent_token(client, register(client))
    response = client.post(
        "/authorize", data={"request": token, "password": "bad", "decision": "approve"}
    )
    assert response.status_code == 401 and "Wrong password" in response.text


def test_deny_redirects_with_access_denied(client):
    token = _consent_token(client, register(client))
    response = client.post(
        "/authorize", data={"request": token, "decision": "deny"}, follow_redirects=False
    )
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["s"]


def test_password_bruteforce_is_rate_limited(client):
    token = _consent_token(client, register(client))
    for _ in range(5):
        client.post("/authorize", data={"request": token, "password": "x", "decision": "approve"})
    response = client.post(
        "/authorize", data={"request": token, "password": "x", "decision": "approve"}
    )
    assert response.status_code == 429


def test_rate_limit_key_ignores_spoofed_forwarded_for(client):
    """The limiter is keyed by the real client address (TestClient's peer is not a trusted
    proxy), so varying X-Forwarded-For on every attempt does not reset the counter."""
    token = _consent_token(client, register(client))
    for i in range(5):
        client.post(
            "/authorize",
            data={"request": token, "password": "x", "decision": "approve"},
            headers={"x-forwarded-for": f"198.51.100.{i}"},
        )
    response = client.post(
        "/authorize",
        data={"request": token, "password": "x", "decision": "approve"},
        headers={"x-forwarded-for": "198.51.100.99"},
    )
    assert response.status_code == 429


def test_consent_page_warns_about_requests_you_did_not_start(client):
    reg = register(client, client_name="Totally ChatGPT")
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
        },
    )
    assert "Totally ChatGPT" in response.text
    assert "did not start this connection" in response.text


def test_malformed_code_verifier_is_invalid_grant(client):
    """RFC 7636 charset/length is checked first: no 500 on a non-ASCII verifier."""
    reg = register(client)
    params = authorize(client, reg, secrets.token_urlsafe(48))
    for bad in ("ñ" * 50, "short", ""):
        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": params["code"],
                "client_id": reg["client_id"],
                "code_verifier": bad,
            },
        )
        assert response.status_code == 400, bad
        assert response.json()["error"] == "invalid_grant"


def test_rate_limiter_window():
    limiter = RateLimiter(limit=2, window=10)
    limiter.fail("ip", now=100)
    limiter.fail("ip", now=101)
    assert limiter.blocked("ip", now=105)
    assert not limiter.blocked("ip", now=112)


def test_tampered_consent_request_rejected(client):
    response = client.post(
        "/authorize", data={"request": "a.b.c", "password": "x", "decision": "approve"}
    )
    assert response.status_code == 400


# ----------------------------------------------------------------------------- hardening
def test_metadata_advertises_rfc9207(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["authorization_response_iss_parameter_supported"] is True


def test_openid_configuration_not_served(client):
    assert client.get("/.well-known/openid-configuration").status_code == 404


def test_iss_returned_on_success_and_error(client):
    params = authorize(client, register(client), secrets.token_urlsafe(48))
    assert params["iss"] == "https://gw.example.test"
    reg = register(client)
    response = client.get(
        "/authorize",
        params={"response_type": "code", "client_id": reg["client_id"], "redirect_uri": REDIRECT},
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(response.headers["location"]).query)["iss"] == [
        "https://gw.example.test"
    ]


def test_iss_returned_on_deny(client):
    token = _consent_token(client, register(client))
    response = client.post(
        "/authorize", data={"request": token, "decision": "deny"}, follow_redirects=False
    )
    assert parse_qs(urlsplit(response.headers["location"]).query)["iss"] == [
        "https://gw.example.test"
    ]


def test_foreign_resource_is_rejected(client):
    reg = register(client)
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": reg["client_id"],
            "redirect_uri": REDIRECT,
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "resource": "https://other.example/editor/mcp",
        },
        follow_redirects=False,
    )
    assert "error=invalid_target" in response.headers["location"]


def test_resource_becomes_token_audience(client):
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
            "resource": "https://gw.example.test/editor/mcp/",
        },
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "uri,ok",
    [
        ("https://chatgpt.com/connector/oauth/abc", True),
        ("https://chatgpt.com.evil.example/cb", False),
        ("https://evil.example/https://chatgpt.com/", False),
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("http://localhost:6274/oauth/callback", True),
        ("cursor://anysphere/oauth", False),
    ],
)
def test_registration_redirect_allowlist(client, uri, ok):
    response = client.post("/register", json={"redirect_uris": [uri]})
    assert (response.status_code == 201) is ok, response.text


def test_redirect_allowlist_can_be_disabled():
    app = create_app(make_settings(allowed_redirect_prefixes=()))
    with TestClient(app) as client:
        response = client.post("/register", json={"redirect_uris": ["https://any.example/cb"]})
    assert response.status_code == 201
