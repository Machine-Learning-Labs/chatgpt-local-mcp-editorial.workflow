from __future__ import annotations

import io
import struct
import zlib

from PIL import Image


def png_bytes(size=(64, 48), color=(200, 30, 30), c2pa: bool = False) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    data = buffer.getvalue()
    if not c2pa:
        return data
    # Insert a caBX chunk (C2PA manifest store) right after IHDR, like OpenAI does.
    payload = b"jumb....c2pa manifest (test)"
    chunk = struct.pack(">I", len(payload)) + b"caBX" + payload
    chunk += struct.pack(">I", zlib.crc32(b"caBX" + payload) & 0xFFFFFFFF)
    ihdr_end = 8 + 12 + 13
    return data[:ihdr_end] + chunk + data[ihdr_end:]


def jpeg_bytes(size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def webp_bytes(size=(64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, (10, 200, 20, 128)).save(buffer, format="WEBP")
    return buffer.getvalue()
