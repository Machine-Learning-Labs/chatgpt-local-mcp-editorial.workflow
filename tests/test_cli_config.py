import json

import pytest

from mcp_oauth_gateway.cli import main
from mcp_oauth_gateway.config import Settings
from mcp_oauth_gateway.tokens import Signer

from .conftest import SECRET


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_SECRET", SECRET)
    monkeypatch.setenv("GATEWAY_OWNER_PASSWORD", "pw")
    monkeypatch.delenv("PUBLIC_URL", raising=False)


def test_settings_from_env():
    settings = Settings.from_env(
        {
            "GATEWAY_SECRET": SECRET,
            "GATEWAY_OWNER_PASSWORD": "pw",
            "PUBLIC_URL": "https://x.example/",
            "ACCESS_TOKEN_TTL": "60",
            "GATEWAY_AUTO_APPROVE": "yes",
            "GATEWAY_CORS_ORIGINS": "https://a, https://b",
        }
    )
    assert settings.public_url == "https://x.example"
    assert settings.access_token_ttl == 60
    assert settings.auto_approve is True
    assert settings.cors_origins == ("https://a", "https://b")


def test_short_secret_rejected():
    with pytest.raises(ValueError, match="GATEWAY_SECRET"):
        Settings.from_env({"GATEWAY_SECRET": "short", "GATEWAY_OWNER_PASSWORD": "pw"})


def test_password_required_without_auto_approve():
    with pytest.raises(ValueError, match="OWNER_PASSWORD"):
        Settings.from_env({"GATEWAY_SECRET": SECRET})


def test_cli_token(env, capsys):
    assert main(["token", "--ttl", "120", "--public-url", "https://t.example"]) == 0
    claims = Signer(SECRET).decode(capsys.readouterr().out.strip(), typ="access")
    assert claims["exp"] - claims["iat"] == 120
    assert claims["aud"] == "https://t.example/mcp"
    assert claims["scope"] == "mcp"


def test_cli_token_json(env, capsys):
    assert main(["token", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600


def test_cli_config_error(monkeypatch, capsys):
    monkeypatch.delenv("GATEWAY_SECRET", raising=False)
    assert main(["token"]) == 2
    assert "configuration error" in capsys.readouterr().err
