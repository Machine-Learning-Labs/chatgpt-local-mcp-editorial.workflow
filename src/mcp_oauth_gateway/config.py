"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SCOPE = "mcp"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    secret: str
    owner_password: str
    upstream_url: str = "http://scribus-mcp:8000/mcp"
    upstream_host_header: str = ""
    public_url: str = ""
    access_token_ttl: int = 3600
    refresh_token_ttl: int = 30 * 24 * 3600
    code_ttl: int = 120
    auto_approve: bool = False
    cors_origins: tuple[str, ...] = ("*",)
    scopes: tuple[str, ...] = field(default=(DEFAULT_SCOPE,))
    host: str = "0.0.0.0"  # noqa: S104 - runs inside a container
    port: int = 8080

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ValueError("GATEWAY_SECRET must be at least 32 characters (run bin/setup)")
        if not self.owner_password and not self.auto_approve:
            raise ValueError("GATEWAY_OWNER_PASSWORD is required unless GATEWAY_AUTO_APPROVE=true")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        origins = tuple(
            o.strip() for o in env.get("GATEWAY_CORS_ORIGINS", "*").split(",") if o.strip()
        )
        return cls(
            secret=env.get("GATEWAY_SECRET", ""),
            owner_password=env.get("GATEWAY_OWNER_PASSWORD", ""),
            upstream_url=env.get("UPSTREAM_URL", cls.upstream_url),
            upstream_host_header=env.get("UPSTREAM_HOST_HEADER", ""),
            public_url=env.get("PUBLIC_URL", "").rstrip("/"),
            access_token_ttl=_int(env.get("ACCESS_TOKEN_TTL"), cls.access_token_ttl),
            refresh_token_ttl=_int(env.get("REFRESH_TOKEN_TTL"), cls.refresh_token_ttl),
            code_ttl=_int(env.get("AUTH_CODE_TTL"), cls.code_ttl),
            auto_approve=_bool(env.get("GATEWAY_AUTO_APPROVE")),
            cors_origins=origins or ("*",),
            host=env.get("GATEWAY_HOST", cls.host),
            port=_int(env.get("GATEWAY_PORT_INTERNAL"), cls.port),
        )
