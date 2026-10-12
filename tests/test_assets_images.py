import os
import stat
from pathlib import Path

import pytest

from editorial_assets.images import AssetError, slugify, store, validate

from .assets_helpers import jpeg_bytes, png_bytes, webp_bytes

MAX = 5 * 1024 * 1024
PIXELS = 10_000_000


def test_png_with_c2pa_is_kept_byte_for_byte(tmp_path):
    data = png_bytes(c2pa=True)
    asset = store(data, tmp_path, "Amplificador de guitarra.png", MAX, PIXELS)
    assert asset.c2pa is True
    assert asset.format == "PNG" and (asset.width, asset.height) == (64, 48)
    assert Path(asset.path).read_bytes() == data  # provenance preserved
    assert os.path.basename(asset.path).startswith("amplificador-de-guitarra-")


def test_jpeg_kept(tmp_path):
    data = jpeg_bytes()
    asset = store(data, tmp_path, None, MAX, PIXELS)
    assert asset.path.endswith(".jpg") and Path(asset.path).read_bytes() == data
    assert asset.c2pa is False


def test_webp_converted_to_png(tmp_path):
    asset = store(webp_bytes(), tmp_path, "x", MAX, PIXELS)
    assert asset.format == "PNG" and asset.path.endswith(".png")
    assert Path(asset.path).read_bytes().startswith(b"\x89PNG")


def test_same_image_twice_is_deduplicated(tmp_path):
    first = store(png_bytes(), tmp_path, "a", MAX, PIXELS)
    second = store(png_bytes(), tmp_path, "b", MAX, PIXELS)
    assert second.duplicate is True and second.path == first.path
    assert len(list(tmp_path.iterdir())) == 1


def test_files_are_not_world_readable(tmp_path):
    asset = store(png_bytes(), tmp_path, "a", MAX, PIXELS)
    assert not stat.S_IMODE(os.stat(asset.path).st_mode) & stat.S_IROTH
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".part")]


@pytest.mark.parametrize(
    "data,message",
    [
        (b"", "empty"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "unsupported"),
        (b"GIF89a....", "unsupported"),
        (png_bytes() + b"<?php system($_GET[1]); ?>", "after the end"),
        (jpeg_bytes() + b"PK\x03\x04zip-payload", "after the end"),
        (png_bytes()[:40], "truncated"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 30, "PNG"),
    ],
)
def test_rejected_inputs(data, message):
    with pytest.raises(AssetError, match=message):
        validate(data, MAX, PIXELS)


def test_size_cap():
    with pytest.raises(AssetError, match="too large"):
        validate(png_bytes(), 100, PIXELS)


def test_decompression_bomb_rejected():
    with pytest.raises(AssetError, match="too many pixels"):
        validate(png_bytes(size=(400, 400)), MAX, 10_000)


def test_jpeg_with_png_magic_mismatch_rejected():
    data = jpeg_bytes()
    with pytest.raises(AssetError):
        validate(b"\x89PNG\r\n\x1a\n" + data, MAX, PIXELS)


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "cómo_funciona_un_amplificador_de_guitarra.png",
            "como-funciona-un-amplificador-de-guitarra",
        ),
        ("../../etc/passwd", "etc-passwd"),
        ("", "image"),
        ("ÑÑÑ", "nnn"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected
