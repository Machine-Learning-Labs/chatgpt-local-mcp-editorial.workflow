"""Settings for the assets server, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DOWNLOAD_HOSTS = (".oaiusercontent.com", ".openai.com", ".chatgpt.com")


def _list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or not value.strip():
        return default
    return tuple(v.strip().lower() for v in value.split(",") if v.strip())


@dataclass(frozen=True)
class AssetsSettings:
    root: str  # EDITORIAL_ROOT: the only folder this server may write to
    secret: str  # signs single-use upload links
    subdir: str = "libro/assets"  # default destination, relative to root
    download_hosts: tuple[str, ...] = DEFAULT_DOWNLOAD_HOSTS
    max_bytes: int = 30 * 1024 * 1024
    max_pixels: int = 80_000_000
    upload_ttl: int = 900
    public_url: str = ""  # optional; normally derived from X-Forwarded-* set by the gateway
    host: str = "127.0.0.1"
    port: int = 8766

    def __post_init__(self) -> None:
        if not self.root.startswith("/"):
            raise ValueError("EDITORIAL_ROOT must be an absolute path")
        if len(self.secret) < 32:
            raise ValueError("ASSETS_SECRET must be at least 32 characters (run bin/setup)")
        if self.subdir.startswith("/") or ".." in self.subdir.split("/"):
            raise ValueError("ASSETS_SUBDIR must be a relative path inside EDITORIAL_ROOT")

    @property
    def default_dir(self) -> str:
        return os.path.join(self.root, self.subdir)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AssetsSettings:
        env = dict(os.environ if env is None else env)
        return cls(
            root=env.get("EDITORIAL_ROOT", "").rstrip("/"),
            secret=env.get("ASSETS_SECRET", ""),
            subdir=env.get("ASSETS_SUBDIR", cls.subdir).strip("/") or cls.subdir,
            download_hosts=_list(env.get("ASSETS_DOWNLOAD_HOSTS"), DEFAULT_DOWNLOAD_HOSTS),
            max_bytes=int(env.get("ASSETS_MAX_BYTES") or cls.max_bytes),
            public_url=env.get("ASSETS_PUBLIC_URL", "").rstrip("/"),
            host=env.get("ASSETS_HOST", cls.host),
            port=int(env.get("ASSETS_PORT") or cls.port),
        )
