"""Client address and scheme behind the ngrok agent (or any reverse proxy).

uvicorn runs with ``proxy_headers=False`` (see ``cli.py``), so ``request.client`` is
always the TCP peer. Forwarded headers count only when that peer is a trusted proxy
(``GATEWAY_TRUSTED_PROXIES``), and only their *last* value: ngrok appends to
``X-Forwarded-For`` and ``X-Forwarded-Proto``, so earlier values are client-controlled.
``X-Forwarded-Host`` is never used, because ngrok passes a client-supplied one through.
"""

from __future__ import annotations

import ipaddress

from starlette.requests import Request

from .config import Settings


def peer_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def peer_is_trusted(request: Request, settings: Settings) -> bool:
    return _in(peer_ip(request), settings.trusted_proxy_cidrs)


def client_ip(request: Request, settings: Settings) -> str:
    """Peer address, or the address ngrok appended to X-Forwarded-For when the peer is trusted."""
    peer = peer_ip(request)
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _in(peer, settings.trusted_proxy_cidrs):
        # The proxy appends the real client last; anything before it is client-controlled.
        return forwarded.split(",")[-1].strip()
    return peer


def forwarded_proto(request: Request, settings: Settings) -> str:
    """Scheme of the public request: the last X-Forwarded-Proto hop from a trusted proxy."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded and peer_is_trusted(request, settings):
        last = forwarded.split(",")[-1].strip().lower()
        if last in {"http", "https"}:
            return last
    return request.url.scheme


def ip_allowed(request: Request, settings: Settings) -> bool:
    if not settings.allowed_client_cidrs:
        return True
    return _in(client_ip(request, settings), settings.allowed_client_cidrs)


def _in(ip: str, networks) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address in net for net in networks)
