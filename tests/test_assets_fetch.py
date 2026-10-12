import asyncio

import httpx
import pytest

from editorial_assets.fetch import check_url, download, host_allowed
from editorial_assets.images import AssetError

from .assets_helpers import png_bytes

HOSTS = (".oaiusercontent.com",)
OK_URL = "https://sdmntprcentralus.oaiusercontent.com/files/abc?sig=1"


async def public(_host):
    return ["20.0.0.1"]


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "host,ok",
    [
        ("sdmntprcentralus.oaiusercontent.com", True),
        ("oaiusercontent.com", False),  # pattern needs a subdomain
        ("evil-oaiusercontent.com", False),
        ("oaiusercontent.com.evil.example", False),
        ("SDMNT.OAIUSERCONTENT.COM.", True),
    ],
)
def test_host_allowed(host, ok):
    assert host_allowed(host, HOSTS) is ok


@pytest.mark.parametrize(
    "url,message",
    [
        ("http://x.oaiusercontent.com/f", "https"),
        ("https://user:pw@x.oaiusercontent.com/f", "credentials"),
        ("https://evil.example/f", "not allowed"),
        ("file:///etc/passwd", "https"),
    ],
)
def test_check_url_rejects(url, message):
    with pytest.raises(AssetError, match=message):
        run(check_url(url, HOSTS, public))


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.1.2"]
)
def test_private_addresses_are_blocked(address):
    async def resolver(_host):
        return [address]

    with pytest.raises(AssetError, match="non-public"):
        run(check_url(OK_URL, HOSTS, resolver))


def test_download_ok():
    data = png_bytes()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=data))
    got = run(
        download(OK_URL, allowed_hosts=HOSTS, max_bytes=10**6, transport=transport, resolver=public)
    )
    assert got == data


def test_redirect_to_other_host_is_rechecked():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    with pytest.raises(AssetError, match="not allowed"):
        run(
            download(
                OK_URL,
                allowed_hosts=HOSTS,
                max_bytes=10**6,
                transport=httpx.MockTransport(handler),
                resolver=public,
            )
        )


def test_redirect_within_allowlist_is_followed():
    data = png_bytes()

    def handler(request):
        if request.url.path == "/files/abc":
            return httpx.Response(302, headers={"location": "/files/final"})
        return httpx.Response(200, content=data)

    got = run(
        download(
            OK_URL,
            allowed_hosts=HOSTS,
            max_bytes=10**6,
            transport=httpx.MockTransport(handler),
            resolver=public,
        )
    )
    assert got == data


def test_too_many_redirects():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": OK_URL}))
    with pytest.raises(AssetError, match="redirects"):
        run(
            download(
                OK_URL, allowed_hosts=HOSTS, max_bytes=10**6, transport=transport, resolver=public
            )
        )


def test_size_cap_while_streaming():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(AssetError, match="too large"):
        run(
            download(
                OK_URL, allowed_hosts=HOSTS, max_bytes=1000, transport=transport, resolver=public
            )
        )


def test_http_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(403))
    with pytest.raises(AssetError, match="403"):
        run(
            download(
                OK_URL, allowed_hosts=HOSTS, max_bytes=1000, transport=transport, resolver=public
            )
        )


def test_no_cookies_or_auth_sent():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, content=png_bytes())

    run(
        download(
            OK_URL,
            allowed_hosts=HOSTS,
            max_bytes=10**6,
            transport=httpx.MockTransport(handler),
            resolver=public,
        )
    )
    assert "authorization" not in seen and "cookie" not in seen
