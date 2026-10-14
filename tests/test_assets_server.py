import asyncio
import json
import re

import httpx
import pytest
from starlette.testclient import TestClient

from editorial_assets.config import AssetsSettings
from editorial_assets.images import AssetError
from editorial_assets.server import build_asgi, build_server, resolve_folder

from .assets_helpers import png_bytes

SECRET = "s" * 40
DL = "https://sdmntprcentralus.oaiusercontent.com/files/abc"


async def public(_host):
    return ["20.0.0.1"]


@pytest.fixture
def settings(tmp_path):
    root = tmp_path / "Editorial"
    root.mkdir()
    return AssetsSettings(root=str(root), secret=SECRET)


def make(settings, data=None):
    data = data if data is not None else png_bytes(c2pa=True)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=data))
    return build_server(settings, transport=transport, resolver=public)


def result_json(result):
    """FastMCP call_tool returns (content, structured) in mcp 1.x."""
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


# ----------------------------------------------------------------------------- config
def test_settings_validation(tmp_path):
    with pytest.raises(ValueError, match="EDITORIAL_ROOT"):
        AssetsSettings(root="relative", secret=SECRET)
    with pytest.raises(ValueError, match="ASSETS_SECRET"):
        AssetsSettings(root="/x", secret="short")
    with pytest.raises(ValueError, match="ASSETS_SUBDIR"):
        AssetsSettings(root="/x", secret=SECRET, subdir="../out")
    s = AssetsSettings.from_env({"EDITORIAL_ROOT": "/home/u/Editorial/", "ASSETS_SECRET": SECRET})
    assert s.default_dir == "/home/u/Editorial/libro/assets"


def test_served_app_cuts_off_chunked_bodies_at_the_cap(tmp_path):
    """What uvicorn serves (build_asgi) limits the request body even without
    Content-Length, so an upload cannot be spooled whole into /tmp before any check."""
    from mcp_oauth_gateway.tokens import Signer

    root = tmp_path / "Editorial"
    root.mkdir()
    settings = AssetsSettings(root=str(root), secret=SECRET, max_bytes=1000)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=png_bytes()))
    link = Signer(SECRET).issue("upload", 900, folder=str(root / "libro"), name=None)

    def chunks():
        for _ in range(3):
            yield b"x" * 40_000

    app = build_asgi(settings, transport=transport, resolver=public)
    with TestClient(app, base_url="http://localhost:8766") as client:
        response = client.post(
            f"/upload/{link}",
            content=chunks(),
            headers={"content-type": "multipart/form-data; boundary=b0undary"},
        )
    assert response.status_code == 413
    assert not (root / "libro").exists()


def test_folder_jail(settings, tmp_path):
    assert str(resolve_folder(settings, None)).endswith("Editorial/libro/assets")
    assert resolve_folder(settings, "libro/capitulo-1").name == "capitulo-1"
    for bad in ("/etc", "../x", "~/x", str(tmp_path)):
        with pytest.raises(AssetError):
            resolve_folder(settings, bad)


# ----------------------------------------------------------------------------- tools
def test_import_image_tool_declares_file_params(settings):
    tools = {t.name: t for t in asyncio.run(make(settings).list_tools())}
    assert set(tools) == {"import_image", "list_assets", "request_image_upload"}
    tool = tools["import_image"]
    assert tool.meta == {"openai/fileParams": ["image"]}
    image = tool.inputSchema["$defs"]["FileRef"] if "$defs" in tool.inputSchema else None
    schema = image or tool.inputSchema["properties"]["image"]
    assert set(schema["required"]) == {"download_url", "file_id"}
    assert {"mime_type", "file_name"} <= set(schema["properties"])
    assert "ctx" not in tools["request_image_upload"].inputSchema.get("properties", {})


def test_import_image_downloads_and_stores(settings):
    server = make(settings)
    args = {
        "image": {
            "download_url": DL,
            "file_id": "file_1",
            "mime_type": "image/png",
            "file_name": "cómo_funciona_un_amplificador_de_guitarra.png",
        },
    }
    out = result_json(asyncio.run(server.call_tool("import_image", args)))
    assert out["path"].startswith(settings.default_dir + "/como-funciona-un-amplificador")
    assert out["c2pa"] is True and out["already_present"] is False
    again = result_json(asyncio.run(server.call_tool("import_image", args)))
    assert again["already_present"] is True and again["path"] == out["path"]


def test_import_image_rejects_foreign_host(settings):
    server = make(settings)
    with pytest.raises(Exception, match="not allowed"):
        asyncio.run(
            server.call_tool(
                "import_image",
                {"image": {"download_url": "https://evil.example/x", "file_id": "f"}},
            )
        )


def test_list_assets_newest_first(settings):
    server = make(settings)
    empty = result_json(asyncio.run(server.call_tool("list_assets", {})))
    assert empty["assets"] == []
    asyncio.run(server.call_tool("import_image", {"image": {"download_url": DL, "file_id": "1"}}))
    listing = result_json(asyncio.run(server.call_tool("list_assets", {})))
    assert listing["assets"][0]["width"] == 64
    assert listing["assets"][0]["path"].startswith(settings.default_dir)


# ----------------------------------------------------------------------------- HTTP
def _rpc(client, method, params, host_headers=None):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={
            "accept": "application/json, text/event-stream",
            "host": "localhost:8766",
            **(host_headers or {}),
        },
    )
    assert response.status_code == 200, response.text
    data = [ln[5:] for ln in response.text.splitlines() if ln.startswith("data:")]
    return json.loads(data[0]) if data else response.json()


def test_dns_rebinding_guard_rejects_foreign_host(settings):
    with TestClient(make(settings).streamable_http_app()) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream", "host": "evil.example"},
        )
    assert response.status_code == 421


def test_upload_link_flow(settings):
    app = make(settings).streamable_http_app()
    with TestClient(app, base_url="http://localhost:8766") as client:
        reply = _rpc(
            client,
            "tools/call",
            {"name": "request_image_upload", "arguments": {"name": "portada"}},
            {"x-forwarded-proto": "https", "x-forwarded-host": "pub.example"},
        )
        info = json.loads(reply["result"]["content"][0]["text"])
        assert info["upload_url"].startswith("https://pub.example/upload/")
        path = "/upload/" + info["upload_url"].rsplit("/upload/", 1)[1]

        page = client.get(path)
        assert page.status_code == 200 and "type=file" in page.text

        bad = client.post(path, files={"file": ("x.txt", b"hello", "text/plain")})
        assert bad.status_code == 400  # a rejected upload also burns the link (no retries)
        ok_path = _new_link(client)
        ok = client.post(ok_path, files={"file": ("p.png", png_bytes(), "image/png")})
        assert ok.status_code == 200 and "Saved as" in ok.text
        saved = re.search(r"<code>([^<]+)</code>", ok.text).group(1)
        assert saved.startswith(settings.default_dir + "/portada-")

        reuse = client.post(ok_path, files={"file": ("p.png", png_bytes(), "image/png")})
        assert reuse.status_code == 410  # single use


def _new_link(client):
    reply = _rpc(
        client, "tools/call", {"name": "request_image_upload", "arguments": {"name": "portada"}}
    )
    url = json.loads(reply["result"]["content"][0]["text"])["upload_url"]
    return "/upload/" + url.rsplit("/upload/", 1)[1]


def test_upload_rejects_forged_or_expired_links(settings):
    from mcp_oauth_gateway.tokens import Signer

    app = make(settings).streamable_http_app()
    expired = Signer(SECRET).issue("upload", 10, now=0, folder=settings.default_dir)
    forged = Signer("x" * 40).issue("upload", 600, folder="/etc")
    with TestClient(app) as client:
        assert client.get(f"/upload/{expired}").status_code == 410
        assert client.get(f"/upload/{forged}").status_code == 410
        assert client.get("/upload/garbage").status_code == 410


def test_healthz(settings):
    with TestClient(make(settings).streamable_http_app()) as client:
        assert client.get("/healthz").json()["status"] == "ok"
