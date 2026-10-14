"""The Editorial Assets MCP server (FastMCP, Streamable HTTP, stateless).

Tools
- import_image   ChatGPT passes an image file (``openai/fileParams``) → saved under the root
- list_assets    what is already in the folder, newest first, with absolute paths for Scribus
- request_image_upload  single-use upload link (fallback when the client cannot pass files)

Routes (proxied by the gateway without bearer auth, the token in the URL is the capability)
- GET/POST /upload/{token}
"""

from __future__ import annotations

import html
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from mcp_oauth_gateway.tokens import Signer, TokenError

from . import __version__
from .config import AssetsSettings
from .fetch import Resolver, download, system_resolver
from .images import AssetError, store

log = logging.getLogger("editorial_assets")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


class FileRef(BaseModel):
    """File object ChatGPT injects for parameters listed in ``openai/fileParams``."""

    model_config = ConfigDict(extra="allow")
    download_url: str = Field(description="Temporary URL of the file (filled by ChatGPT)")
    file_id: str = Field(description="ChatGPT file id (filled by ChatGPT)")
    mime_type: str | None = None
    file_name: str | None = None


INSTRUCTIONS = (
    "Brings images into the editorial folder so Scribus can place them. "
    "To save an image from this conversation (generated or uploaded), call import_image "
    "with the image file. Then use the returned absolute path with the Scribus connector "
    "(create_image_frame + load_image). list_assets shows what is already available. "
    "If import_image cannot receive the file, call request_image_upload and give the user "
    "the link."
)


class UploadLinks:
    def __init__(self, secret: str, ttl: int) -> None:
        self.signer = Signer(secret)
        self.ttl = ttl
        self._used: dict[str, float] = {}

    def issue(self, folder: str, name: str | None) -> str:
        return self.signer.issue("upload", self.ttl, folder=folder, name=name)

    def peek(self, token: str) -> dict:
        claims = self.signer.decode(token, typ="upload")
        if claims["jti"] in self._used:
            raise TokenError("upload link already used")
        return claims

    def consume(self, token: str) -> dict:
        claims = self.peek(token)
        now = time.time()
        self._used = {k: v for k, v in self._used.items() if v > now}
        self._used[claims["jti"]] = claims["exp"]
        return claims


def resolve_folder(settings: AssetsSettings, folder: str | None) -> Path:
    """Destination inside EDITORIAL_ROOT (defense in depth: the gateway checks it too)."""
    root = Path(os.path.realpath(settings.root))
    if not folder:
        target = Path(settings.default_dir)
    else:
        if "\x00" in folder or folder.startswith("~"):
            raise AssetError("folder must be a path inside the editorial folder")
        target = Path(folder) if folder.startswith("/") else root / folder
    resolved = Path(os.path.realpath(target))
    if resolved != root and root not in resolved.parents:
        raise AssetError(f"folder must be inside {settings.root}")
    return resolved


def build_server(
    settings: AssetsSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = system_resolver,
) -> FastMCP:
    links = UploadLinks(settings.secret, settings.upload_ttl)
    mcp = FastMCP(
        "editorial-assets",
        instructions=INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        streamable_http_path="/mcp",
        # Only the gateway talks to us, with Host: localhost:<port> and no Origin.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*", "127.0.0.1:*"],
            allowed_origins=[],
        ),
    )

    def save(data: bytes, folder: str | None, name: str | None) -> dict:
        asset = store(
            data, resolve_folder(settings, folder), name, settings.max_bytes, settings.max_pixels
        )
        log.info(
            "stored %s (%s bytes, c2pa=%s, dup=%s)",
            asset.path,
            asset.bytes,
            asset.c2pa,
            asset.duplicate,
        )
        return asset.as_dict()

    @mcp.tool(
        title="Import image into the editorial folder",
        meta={"openai/fileParams": ["image"]},
    )
    async def import_image(
        image: FileRef, name: str | None = None, folder: str | None = None
    ) -> dict:
        """Save an image from the conversation (generated or uploaded) to the editorial folder.

        Pass the image file itself as `image` (ChatGPT fills download_url/file_id).
        `name` is a short human name used in the file name. `folder` defaults to the book's
        assets folder. Returns the absolute `path` to use with Scribus load_image.
        """
        log.info(
            "import_image file_id=%s mime=%s name=%s",
            image.file_id,
            image.mime_type,
            image.file_name,
        )
        data = await download(
            image.download_url,
            allowed_hosts=settings.download_hosts,
            max_bytes=settings.max_bytes,
            transport=transport,
            resolver=resolver,
        )
        return save(data, folder, name or image.file_name)

    @mcp.tool(title="List images in the editorial folder")
    def list_assets(folder: str | None = None, limit: int = 50) -> dict:
        """List images (newest first) with absolute paths, sizes and pixel dimensions."""
        directory = resolve_folder(settings, folder)
        if not directory.is_dir():
            return {"folder": str(directory), "assets": []}
        files = sorted(
            (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[: max(1, min(limit, 500))]
        assets = []
        for path in files:
            entry: dict[str, Any] = {"path": str(path), "bytes": path.stat().st_size}
            try:
                from PIL import Image

                with Image.open(path) as image:
                    entry["width"], entry["height"] = image.size
            except Exception:  # noqa: BLE001 - listing must not fail on one bad file
                entry["error"] = "unreadable"
            assets.append(entry)
        return {"folder": str(directory), "assets": assets}

    @mcp.tool(title="Create a one-time image upload link")
    def request_image_upload(
        ctx: Context, name: str | None = None, folder: str | None = None
    ) -> dict:
        """Fallback when import_image cannot receive the file: returns a single-use link
        (valid 15 minutes) where the user uploads the image from their browser or phone."""
        directory = resolve_folder(settings, folder)
        token = links.issue(str(directory), name)
        return {
            "upload_url": f"{_public_base(settings, ctx)}/upload/{token}",
            "expires_in_seconds": settings.upload_ttl,
            "destination": str(directory),
        }

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "version": __version__})

    @mcp.custom_route("/upload/{token}", methods=["GET", "POST"])
    async def upload(request: Request) -> Response:
        token = request.path_params["token"]
        try:
            claims = links.peek(token)
        except TokenError as exc:
            return HTMLResponse(_page("Link not valid", f"<p>{html.escape(str(exc))}.</p>"), 410)
        if request.method == "GET":
            return HTMLResponse(_page("Upload an image", _form(claims["folder"])))
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > settings.max_bytes + 64 * 1024:
            return HTMLResponse(_page("Too large", "<p>The image is too large.</p>"), 413)
        form = await request.form(max_files=1, max_fields=2, max_part_size=settings.max_bytes)
        file = form.get("file")
        if file is None or not hasattr(file, "read"):
            return HTMLResponse(
                _page("Upload an image", _form(claims["folder"], "Choose a file.")), 400
            )
        data = await file.read(settings.max_bytes + 1)
        try:
            claims = links.consume(token)
            result = save(data, claims["folder"], claims.get("name") or file.filename)
        except (AssetError, TokenError) as exc:
            return HTMLResponse(_page("Upload rejected", f"<p>{html.escape(str(exc))}</p>"), 400)
        body = (
            f"<p>Saved as <code>{html.escape(result['path'])}</code> "
            f"({result['width']}×{result['height']}).</p>"
            "<p>Go back to the conversation and ask to place it.</p>"
        )
        return HTMLResponse(_page("Image saved", body))

    return mcp


def build_asgi(settings: AssetsSettings, **kwargs):
    """The ASGI app uvicorn serves: the MCP app behind a request body limit.

    Only the gateway reaches this server, and it already caps uploads, but a chunked
    body without Content-Length would otherwise be spooled whole before any check.
    """
    from starlette.middleware.body_limit import RequestBodyLimitMiddleware

    app = build_server(settings, **kwargs).streamable_http_app()
    return RequestBodyLimitMiddleware(app, max_body_size=settings.max_bytes + 64 * 1024)


def _public_base(settings: AssetsSettings, ctx: Context) -> str:
    """Public origin: ASSETS_PUBLIC_URL, or X-Forwarded-* set by the gateway."""
    if settings.public_url:
        return settings.public_url
    request = getattr(ctx.request_context, "request", None)
    if request is None:
        return ""
    proto = request.headers.get("x-forwarded-proto", "https").split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host.split(',')[0].strip()}"


_STYLE = (
    "body{font:16px system-ui,sans-serif;margin:0;padding:16px;display:grid;place-items:center;"
    "min-height:100vh;background:#f6f5f2;color:#1d1d1b}main{max-width:420px;width:100%;"
    "background:#fff;padding:24px;border-radius:12px}code{word-break:break-all}"
    "button{padding:10px 16px;font:inherit;margin-top:12px}"
    "@media (prefers-color-scheme:dark){body{background:#161614;color:#ecebe6}"
    "main{background:#22211e}}"
)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>"
    )


def _form(folder: str, error: str = "") -> str:
    err = f"<p><strong>{html.escape(error)}</strong></p>" if error else ""
    return (
        f"{err}<p>Destination: <code>{html.escape(folder)}</code></p>"
        "<form method=post enctype=multipart/form-data>"
        "<input type=file name=file accept='image/png,image/jpeg,image/webp' required>"
        "<br><button type=submit>Upload</button></form>"
        "<p>This link works once and expires in 15 minutes.</p>"
    )
