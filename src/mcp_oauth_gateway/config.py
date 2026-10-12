"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field

DEFAULT_SCOPE = "mcp"

# Tools that can run code or touch Scribus' own configuration. Hidden and refused
# unless explicitly re-enabled through POLICY_DENY_TOOLS.
DEFAULT_DENY_TOOLS = (
    "run_script",  # arbitrary Python inside Scribus
    "install_custom_font",  # copies files into font dirs and edits Scribus prefs
    "set_js_action",  # embeds JavaScript into the document / exported PDFs
    "create_pdf_push_button",  # same, through a button action
)
# Clients that may register (DCR). Empty tuple = any valid redirect URI.
DEFAULT_REDIRECT_PREFIXES = (
    "https://chatgpt.com/",
    "https://claude.ai/",
    "https://claude.com/",
    "http://localhost",
    "http://127.0.0.1",
)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _list(value: str | None, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Comma/whitespace separated list; unset = default, "none" or "-" = empty."""
    if value is None:
        return default
    if value.strip().lower() in {"none", "-"}:
        return ()
    items = tuple(v.strip() for v in value.replace("\n", ",").split(",") if v.strip())
    return items or default


def _networks(values: tuple[str, ...]) -> tuple[Network, ...]:
    return tuple(ipaddress.ip_network(v, strict=False) for v in values)


@dataclass(frozen=True)
class Settings:
    secret: str
    owner_password: str
    upstream_url: str = "http://scribus-mcp:8000/mcp"
    upstream_host_header: str = ""
    # Second protected resource (Editorial Assets MCP) at /assets/mcp; empty = disabled.
    assets_upstream_url: str = ""
    assets_upstream_host_header: str = ""
    assets_max_upload_bytes: int = 31 * 1024 * 1024
    public_url: str = ""
    access_token_ttl: int = 3600
    refresh_token_ttl: int = 30 * 24 * 3600
    code_ttl: int = 120
    auto_approve: bool = False
    cors_origins: tuple[str, ...] = ("*",)
    scopes: tuple[str, ...] = field(default=(DEFAULT_SCOPE,))
    host: str = "0.0.0.0"  # noqa: S104 - runs inside a container
    port: int = 8080
    # --- OAuth hardening
    allowed_redirect_prefixes: tuple[str, ...] = DEFAULT_REDIRECT_PREFIXES
    # --- network hardening: only these client IPs may call /mcp and /token (empty = any).
    allowed_client_cidrs: tuple[Network, ...] = ()
    # Peers whose X-Forwarded-For is trusted (the ngrok agent).
    trusted_proxy_cidrs: tuple[Network, ...] = field(
        default_factory=lambda: _networks(("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12"))
    )
    max_body_bytes: int = 4 * 1024 * 1024
    # --- tool policy (src/mcp_oauth_gateway/policy.py)
    policy_root: str = ""
    deny_tools: tuple[str, ...] = DEFAULT_DENY_TOOLS
    allow_tools: tuple[str, ...] = ()  # non-empty = only these tools

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ValueError("GATEWAY_SECRET must be at least 32 characters (run bin/setup)")
        if not self.owner_password and not self.auto_approve:
            raise ValueError("GATEWAY_OWNER_PASSWORD is required unless GATEWAY_AUTO_APPROVE=true")
        if self.policy_root and not self.policy_root.startswith("/"):
            raise ValueError("POLICY_ROOT must be an absolute path")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        trusted = _list(env.get("GATEWAY_TRUSTED_PROXIES"))
        extra = {"trusted_proxy_cidrs": _networks(trusted)} if trusted else {}
        return cls(
            secret=env.get("GATEWAY_SECRET", ""),
            owner_password=env.get("GATEWAY_OWNER_PASSWORD", ""),
            upstream_url=env.get("UPSTREAM_URL", cls.upstream_url),
            upstream_host_header=env.get("UPSTREAM_HOST_HEADER", ""),
            assets_upstream_url=env.get("ASSETS_UPSTREAM_URL", "").rstrip("/"),
            assets_upstream_host_header=env.get("ASSETS_UPSTREAM_HOST_HEADER", ""),
            assets_max_upload_bytes=_int(
                env.get("ASSETS_MAX_UPLOAD_BYTES"), cls.assets_max_upload_bytes
            ),
            public_url=env.get("PUBLIC_URL", "").rstrip("/"),
            access_token_ttl=_int(env.get("ACCESS_TOKEN_TTL"), cls.access_token_ttl),
            refresh_token_ttl=_int(env.get("REFRESH_TOKEN_TTL"), cls.refresh_token_ttl),
            code_ttl=_int(env.get("AUTH_CODE_TTL"), cls.code_ttl),
            auto_approve=_bool(env.get("GATEWAY_AUTO_APPROVE")),
            cors_origins=_list(env.get("GATEWAY_CORS_ORIGINS"), ("*",)),
            host=env.get("GATEWAY_HOST", cls.host),
            port=_int(env.get("GATEWAY_PORT_INTERNAL"), cls.port),
            allowed_redirect_prefixes=_list(
                env.get("GATEWAY_ALLOWED_REDIRECTS"), DEFAULT_REDIRECT_PREFIXES
            ),
            allowed_client_cidrs=_networks(_list(env.get("GATEWAY_ALLOWED_CLIENT_CIDRS"))),
            max_body_bytes=_int(env.get("GATEWAY_MAX_BODY_BYTES"), cls.max_body_bytes),
            policy_root=env.get("POLICY_ROOT", "").rstrip("/"),
            deny_tools=_list(env.get("POLICY_DENY_TOOLS"), DEFAULT_DENY_TOOLS),
            allow_tools=_list(env.get("POLICY_ALLOW_TOOLS")),
            **extra,
        )
