"""Extraction of sampled brush tips from the ABR samp section (v1/v2 old format and v6.1/v6.2 new format)."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

from .rle import rle_decode

MAX_SIZE = 10000  # protective cap on the same order as GIMP_BRUSH_MAX_SIZE


@dataclass
class BrushTip:
    """A sampled brush tip. gray is a uint8 (h, w) opacity mask: 255 = ink, 0 = transparent."""

    index: int
    width: int
    height: int
    depth_bits: int
    gray: np.ndarray
    uuid: str | None = None
    name: str | None = None
    spacing: int | None = None
    source_offset: int = 0
    meta: dict = field(default_factory=dict)


class AbrParseError(ValueError):
    pass


def _to_gray8(raw: np.ndarray, bytes_per_pixel: int) -> np.ndarray:
    """Normalize raw pixel data to uint8 grayscale."""
    if bytes_per_pixel == 1:
        return raw.astype(np.uint8)
    if bytes_per_pixel == 2:
        # 16-bit samples are stored little-endian (consistent with GIMP's behavior), mapped to 0..255
        u16 = raw.view("<u2").astype(np.float64) / 65535.0
        return (u16 * 255.0 + 0.5).astype(np.uint8)
    raise AbrParseError(f"Unsupported bit depth: {bytes_per_pixel} bytes/pixel")


def _decode_pixels(buf, compress: int, width: int, height: int,
                   bytes_per_pixel: int) -> np.ndarray:
    """Decompress and convert to an "opacity mask" grayscale (255=ink).

    compress 0=raw, 1=PackBits RLE. Returns an (h, w) uint8 mask.
    """
    size = width * height * bytes_per_pixel
    if compress == 0:
        if len(buf) < size:
            raise AbrParseError("Raw pixel data truncated")
        raw = np.frombuffer(buf[:size], dtype=np.uint8)
    elif compress == 1:
        if bytes_per_pixel != 1:
            raise AbrParseError("RLE compression only supports 8-bit tips")
        raw = rle_decode(buf, size, height)
    else:
        raise AbrParseError(f"Unknown compression mode: {compress}")
    gray = _to_gray8(raw, bytes_per_pixel)
    # ABR sampled byte semantics: 0 = opaque (ink), 255 = transparent (consistent with
    # Krita's convertToQImage; Krita applies a 255 - byte inversion to both ABR and GBR).
    # Here we normalize to an "opacity mask": 255 = ink, for preview and downstream GBR generation.
    mask = (255 - gray.reshape(height, width)).astype(np.uint8)
    return mask


def _parse_v12(data: memoryview | bytes, count: int, version: int,
               base_name: str) -> list[BrushTip]:
    """Old format (major version 1/2): count brushes laid out in sequence."""
    tips: list[BrushTip] = []
    pos = 4
    for i in range(count):
        if pos + 6 > len(data):
            raise AbrParseError(f"Brush header out of bounds at index {i}")
        brush_type, size = struct.unpack_from(">HI", data, pos)
        item_start = pos
        pos += 6
        next_pos = pos + size
        if brush_type != 2:  # 1=calculated tip (no bitmap), other values unknown: skip
            pos = next_pos
            continue
        _misc, spacing = struct.unpack_from(">IH", data, pos)
        pos += 6
        name = None
        if version == 2:
            (char_count,) = struct.unpack_from(">I", data, pos)
            pos += 4
            name = data[pos : pos + char_count * 2].decode("utf-16-be", "replace")
            pos += char_count * 2
        pos += 1  # antialiasing
        pos += 8  # short bounds ×4
        top, left, bottom, right = struct.unpack_from(">4i", data, pos)
        pos += 16
        (depth_bits,) = struct.unpack_from(">H", data, pos)
        pos += 2
        compress = data[pos]
        pos += 1
        width, height = right - left, bottom - top
        if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
            raise AbrParseError(f"Brush size out of bounds: {width}x{height}")
        bpp = depth_bits >> 3
        gray = _decode_pixels(data[pos:next_pos], compress, width, height, bpp)
        tips.append(BrushTip(
            index=len(tips), width=width, height=height,
            depth_bits=depth_bits, gray=gray, name=name or f"{base_name}-{i + 1:03d}",
            spacing=spacing, source_offset=item_start,
        ))
        pos = next_pos
    return tips


def _read_pascal_uuid(data, pos: int) -> str | None:
    """Best-effort read of a v6.2 brush item's UUID (1-byte length + ASCII). Returns None on failure."""
    try:
        length = data[pos]
        if not (20 <= length <= 40):
            return None
        raw = bytes(data[pos + 1 : pos + 1 + length])
        text = raw.decode("ascii")
        if all(c in "0123456789abcdefABCDEF-" for c in text):
            return text
    except Exception:
        pass
    return None


def _parse_v6(data: memoryview | bytes, section_end: int,
              subversion: int, base_name: str) -> list[BrushTip]:
    """New format (major version 6/10): parse item by item within the samp section."""
    skip = 47 if subversion == 1 else 301
    tips: list[BrushTip] = []
    pos = 0
    while pos + 4 <= section_end:
        (brush_size,) = struct.unpack_from(">I", data, pos)
        item_start = pos
        next_pos = pos + 4 + brush_size + (-brush_size % 4)
        if next_pos > section_end + 3:  # allow the last item to overrun slightly (no padding)
            raise AbrParseError(f"Brush item length out of bounds: item@{item_start} size={brush_size}")
        uuid = _read_pascal_uuid(data, pos + 4)
        rect_off = pos + 4 + skip
        top, left, bottom, right = struct.unpack_from(">4i", data, rect_off)
        (depth_bits,) = struct.unpack_from(">H", data, rect_off + 16)
        compress = data[rect_off + 18]
        width, height = right - left, bottom - top
        if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
            raise AbrParseError(f"Brush size out of bounds: {width}x{height} (item@{item_start})")
        bpp = depth_bits >> 3
        if not (1 <= bpp <= 2):
            raise AbrParseError(f"Unsupported bit depth: {depth_bits} bits")
        data_start = rect_off + 19
        gray = _decode_pixels(data[data_start:next_pos], compress, width, height, bpp)
        tips.append(BrushTip(
            index=len(tips), width=width, height=height,
            depth_bits=depth_bits, gray=gray, uuid=uuid,
            name=uuid or f"{base_name}-{len(tips) + 1:03d}",
            source_offset=item_start,
        ))
        pos = next_pos
        if pos >= section_end:
            break
    return tips


def parse_samples(samp: memoryview | bytes, version: int, subversion: int,
                  base_name: str) -> list[BrushTip]:
    """Extract all sampled brush tips from the samp section data."""
    if version in (1, 2):
        return _parse_v12(samp, subversion, version, base_name)
    if version in (6, 10) and subversion in (1, 2):
        return _parse_v6(samp, len(samp), subversion, base_name)
    raise AbrParseError(f"Unsupported ABR version: {version}.{subversion}")
