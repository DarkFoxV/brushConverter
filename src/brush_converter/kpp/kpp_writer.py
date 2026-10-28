"""Write out Krita .kpp preset files.

A .kpp is a PNG (200x200 preview) + an iTXt chunk (keyword="preset", zlib-compressed XML)
       + a tEXt chunk (keyword="version" = "5.0").

PNG chunks are constructed manually to guarantee a structure identical to
the .kpp files Krita itself generates.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np
from PIL import Image


def _chunk(ctype: bytes, payload: bytes) -> bytes:
    """Construct a standard PNG chunk (length + type + data + CRC32)."""
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def _itxt_chunk(keyword: str, text: str, compressed: bool = True) -> bytes:
    """Construct an iTXt chunk (Krita uses it to store the preset XML, keyword="preset")."""
    if compressed:
        data = zlib.compress(text.encode("utf-8"), 9)
        flag = 1
    else:
        data = text.encode("utf-8")
        flag = 0
    payload = (
        keyword.encode("latin1") + b"\x00"
        + bytes([flag, 0])            # compression flag + method
        + b"\x00"                     # language tag
        + b"\x00"                     # translated keyword
        + data
    )
    return _chunk(b"iTXt", payload)


def _text_chunk(keyword: str, text: str) -> bytes:
    """Construct a tEXt chunk (Krita uses it to store version="5.0")."""
    payload = keyword.encode("latin1") + b"\x00" + text.encode("utf-8")
    return _chunk(b"tEXt", payload)


def render_tip_preview(gray: np.ndarray, size: int = 200) -> np.ndarray:
    """Render a grayscale mask (255=ink) as a white brush on a transparent RGBA preview."""
    h, w = gray.shape
    scale = min(size / h, size / w)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = Image.fromarray(gray, mode="L").resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(Image.merge("RGBA", (img, img, img, img)),
                 ((size - nw) // 2, (size - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8)


def build_kpp(preset_xml: str, preview_rgba: np.ndarray) -> bytes:
    """Build the complete .kpp bytes. preview_rgba is (h, w, 4) uint8 RGBA."""
    h, w = preview_rgba.shape[:2]
    out = bytearray()
    out += b"\x89PNG\r\n\x1a\n"

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8bit RGBA
    out += _chunk(b"IHDR", ihdr)

    out += _itxt_chunk("preset", preset_xml, compressed=True)
    out += _text_chunk("version", "5.0")

    # IDAT: each scanline is prefixed with filter byte 0
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += bytes(preview_rgba[y])
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))

    out += _chunk(b"IEND", b"")
    return bytes(out)


def write_kpp(path: str, preset_xml: str, preview_rgba: np.ndarray) -> str:
    with open(path, "wb") as f:
        f.write(build_kpp(preset_xml, preview_rgba))
    return path
