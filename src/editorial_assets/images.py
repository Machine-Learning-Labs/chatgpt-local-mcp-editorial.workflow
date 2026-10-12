"""Strict image validation and storage.

Original bytes are KEPT (so C2PA content credentials survive) only after they pass:
magic-byte sniffing, a full Pillow decode with a pixel cap (decompression bombs), a
format/magic match, and a "nothing after the end marker" check (no appended payloads /
polyglots). WebP, which Scribus 1.6 may not read, is converted to PNG.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import struct
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

KEEP_FORMATS = {"PNG": ".png", "JPEG": ".jpg"}
CONVERT_FORMATS = {"WEBP"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class AssetError(Exception):
    """Rejected input; the message is safe to show to the client."""


@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: int
    height: int
    c2pa: bool


@dataclass(frozen=True)
class StoredAsset:
    path: str
    bytes: int
    width: int
    height: int
    format: str
    c2pa: bool
    sha256: str
    duplicate: bool = False

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "c2pa": self.c2pa,
            "sha256": self.sha256,
            "already_present": self.duplicate,
        }


def sniff(data: bytes) -> str:
    if data.startswith(PNG_MAGIC):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    raise AssetError("unsupported file: only PNG, JPEG or WebP images are accepted")


def _png_chunks(data: bytes) -> list[tuple[bytes, int, int]]:
    """(type, data_offset, length) for every chunk; raises if the structure is broken."""
    chunks, i = [], len(PNG_MAGIC)
    while i < len(data):
        if i + 8 > len(data):
            raise AssetError("truncated PNG")
        (length,) = struct.unpack(">I", data[i : i + 4])
        ctype = data[i + 4 : i + 8]
        end = i + 12 + length
        if end > len(data):
            raise AssetError("truncated PNG")
        chunks.append((ctype, i + 8, length))
        i = end
        if ctype == b"IEND":
            if i != len(data):
                raise AssetError("data after the end of the PNG (possible hidden payload)")
            return chunks
    raise AssetError("PNG without IEND")


def _has_c2pa(data: bytes, fmt: str) -> bool:
    if fmt == "PNG":
        return any(ctype == b"caBX" for ctype, _, _ in _png_chunks(data))
    return b"c2pa" in data[:2_000_000] and b"jumb" in data[:2_000_000]


def validate(data: bytes, max_bytes: int, max_pixels: int) -> ImageInfo:
    if not data:
        raise AssetError("empty file")
    if len(data) > max_bytes:
        raise AssetError(f"image too large ({len(data)} bytes, max {max_bytes})")
    magic = sniff(data)
    if magic == "PNG":
        _png_chunks(data)
    elif magic == "JPEG" and not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
        raise AssetError("data after the end of the JPEG (possible hidden payload)")
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            fmt, (width, height) = image.format, image.size
    except Image.DecompressionBombError as exc:
        raise AssetError("image has too many pixels") from exc
    except AssetError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decoder error means "not a valid image"
        raise AssetError(f"not a valid image: {exc.__class__.__name__}") from exc
    if fmt != magic:
        raise AssetError("file content does not match its image format")
    if width * height > max_pixels:
        raise AssetError("image has too many pixels")
    return ImageInfo(fmt, width, height, _has_c2pa(data, fmt) if fmt != "WEBP" else False)


def to_png(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()


def slugify(text: str, fallback: str = "image") -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\.(png|jpe?g|webp)$", "", text.strip().lower())
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60].strip("-") or fallback


def store(
    data: bytes, directory: Path, name_hint: str | None, max_bytes: int, max_pixels: int
) -> StoredAsset:
    """Validate and write atomically into ``directory`` (never overwrites)."""
    info = validate(data, max_bytes, max_pixels)
    fmt = info.format
    if fmt in CONVERT_FORMATS:
        data, fmt = to_png(data), "PNG"
    digest = hashlib.sha256(data).hexdigest()
    ext = KEEP_FORMATS[fmt]
    directory.mkdir(parents=True, exist_ok=True)
    # Idempotent: ChatGPT sometimes repeats a call with the same file.
    for existing in directory.glob(f"*-{digest[:10]}{ext}"):
        if existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
            return StoredAsset(
                str(existing),
                len(data),
                info.width,
                info.height,
                fmt,
                info.c2pa,
                digest,
                duplicate=True,
            )
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = directory / f"{slugify(name_hint or '')}-{stamp}-{digest[:10]}{ext}"
    tmp = directory / f".{target.name}.part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.link(tmp, target)  # fails if target exists: never overwrite
    finally:
        tmp.unlink(missing_ok=True)
    return StoredAsset(str(target), len(data), info.width, info.height, fmt, info.c2pa, digest)
