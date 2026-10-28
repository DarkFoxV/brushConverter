"""ABR patt section (texture pattern) parsing.

The format was reverse-engineered from observed data (compared against the
Pattern / VirtualMemoryArrayList structure of psd-tools, with corrections for
ABR's differences on that basis):

    patt section = several "length-prefixed" Pattern records, each padded to 4 bytes:
        u32 len | record body (len bytes) | pad to 4

    Record body:
        u32 version(=1) | u32 color mode(3=RGB, 1=grayscale) | 2×i16 (width, height hint) |
        u32 name char count (including the trailing NUL) | name UTF-16BE (NUL counts as 1 char) |
        u8 name byte length(=36) | UUID(ASCII) |
        VMA list: u32 version(=3) | u32 body_len | body {
            u32×4 rect(top,left,bottom,right) | u32 channel count | (channel count+2) channel blocks }

    Channel block:
        u32 is_written(0=empty) | u32 len | u32 depth(bit depth) | u32×4 rect |
        u16 pixel_depth | u8 compression(0=RAW, 1=RLE) | data(len-23)

    RLE(1) is the PSD variant: first height u16 row byte counts, then a PackBits stream per row.

    Notes:
    - In ABR the pattern id uses a u8 length + ASCII UUID (psd-tools' PSD Pattern
      uses a Pascal string; the two differ); the name char count includes the
      trailing NUL.
    - Patterns are linked to brush presets by UUID (Txtr.Idnt in desc), not by name
      (this repo's samples contain 3 patterns all named "Shape 2.png" with
      different contents).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

MAX_SIZE = 30000  # protective cap on the same order as the samp section


class PatternParseError(ValueError):
    pass


@dataclass
class PatternTexture:
    """A Photoshop texture pattern.

    image : uint8 array. color_mode=3 -> (h, w, 3) RGB; color_mode=1 -> (h, w) grayscale.
            Pixel values are as-is (no 255-raw inversion like ABR brush tips).
    """

    name: str
    uuid: str
    image: np.ndarray
    width: int
    height: int
    color_mode: int
    compression: int = 0  # first channel's compression (0=RAW, 1=RLE), reference only


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def _rle_decode_u16(buf: bytes, expected_size: int, height: int) -> bytes:
    """PSD variant RLE decoding: height u16 row byte counts + PackBits per row."""
    if len(buf) < height * 2:
        raise PatternParseError("RLE row-length table truncated")
    counts = struct.unpack_from(f">{height}H", buf, 0)
    offset = height * 2
    out = bytearray()
    for line_len in counts:
        if line_len <= 0:
            raise PatternParseError(f"Invalid scanline length: {line_len}")
        line_end = offset + line_len
        if line_end > len(buf):
            raise PatternParseError("RLE data truncated")
        j = offset
        while j < line_end:
            n = buf[j]
            j += 1
            if n >= 128:
                n -= 256
            if n < 0:
                if n == -128:
                    continue
                run = -n + 1
                if j + 1 > line_end:
                    raise PatternParseError("RLE decode out of bounds (repeat run)")
                out.extend(bytes([buf[j]]) * run)
                j += 1
            else:
                run = n + 1
                if j + run > line_end:
                    raise PatternParseError("RLE decode out of bounds (literal run)")
                out.extend(buf[j : j + run])
                j += run
        offset = line_end
    if len(out) != expected_size:
        raise PatternParseError(
            f"RLE decoded size mismatch: got {len(out)}, expected {expected_size}"
        )
    return bytes(out)


def _decode_channel(data: bytes, depth: int, width: int, height: int,
                    compression: int) -> np.ndarray:
    """Decompress a single channel to (height, width) uint8."""
    if depth != 8:
        raise PatternParseError(f"Unsupported channel bit depth: {depth} bits")
    size = width * height
    if compression == 0:
        if len(data) < size:
            raise PatternParseError("RAW channel data truncated")
        raw = data[:size]
    elif compression == 1:
        raw = _rle_decode_u16(data, size, height)
    else:
        raise PatternParseError(f"Unsupported channel compression: {compression}")
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width)


def _parse_vma_channels(body: bytes, want: int):
    """Parse a VMA body, returning (rect, channel count, the first want channels with data).

    Channel blocks are collected in order of appearance; for RGB take the first 3,
    for grayscale take the 1st, skipping empty blocks with is_written=0.
    """
    if len(body) < 20:
        raise PatternParseError("VMA body too short")
    rect = struct.unpack_from(">4I", body, 0)
    nchans = _u32(body, 16)
    b = 20
    chans: list[tuple[int, tuple, int, bytes]] = []
    for _ in range(nchans + 2):
        if b + 4 > len(body):
            break
        is_written = _u32(body, b)
        b += 4
        if is_written == 0:
            continue
        if b + 4 > len(body):
            break
        length = _u32(body, b)
        b += 4
        if length == 0:
            continue
        if length < 23:
            raise PatternParseError(f"Invalid channel length: {length}")
        depth = _u32(body, b)
        crect = struct.unpack_from(">4I", body, b + 4)
        pixel_depth, compression = struct.unpack_from(">HB", body, b + 20)
        data = body[b + 23 : b + length]
        b += length
        chans.append((depth, crect, compression, data))
        if len(chans) >= want:
            break
    return rect, nchans, chans


def parse_patterns(data: bytes) -> dict[str, PatternTexture]:
    """Parse the entire patt section, returning {uuid: PatternTexture}.

    The cursor must consume the section exactly (each record 4-byte aligned),
    otherwise it is treated as a format error.
    """
    out: dict[str, PatternTexture] = {}
    pos = 0
    index = 0
    while pos + 4 <= len(data):
        length = _u32(data, pos)
        if length <= 0:
            raise PatternParseError(f"Invalid pattern record length: {length} @ {pos}")
        record_end = pos + 4 + length
        if record_end > len(data):
            raise PatternParseError(
                f"Pattern record out of bounds: @{pos} len={length} exceeds section")
        p = pos + 4
        version = _u32(data, p)
        if version != 1:
            raise PatternParseError(f"Unknown pattern version: {version} (pattern {index})")
        p += 4
        color_mode = _u32(data, p)
        p += 4
        p += 4  # 2×i16 point (width/height hint; the VMA rect is authoritative)
        name_chars = _u32(data, p)
        p += 4
        if not (1 <= name_chars <= 4096) or p + name_chars * 2 > record_end:
            raise PatternParseError(f"Invalid pattern name length: {name_chars} @ {p}")
        name = data[p : p + name_chars * 2].decode("utf-16-be", "replace")
        name = name.rstrip("\x00")
        p += name_chars * 2
        id_len = data[p]
        p += 1
        if not (16 <= id_len <= 64) or p + id_len > record_end:
            raise PatternParseError(f"Invalid pattern id length: {id_len}")
        uuid = data[p : p + id_len].decode("ascii", "replace")
        p += id_len

        if p + 8 > record_end:
            raise PatternParseError("Missing VMA list header")
        vma_version = _u32(data, p)
        if vma_version != 3:
            raise PatternParseError(f"Unknown VMA version: {vma_version} (pattern {index})")
        body_len = _u32(data, p + 4)
        body = data[p + 8 : p + 8 + body_len]
        if len(body) != body_len:
            raise PatternParseError("VMA list length out of bounds")

        want = {1: 1, 3: 3}.get(color_mode)
        if want is None:
            raise PatternParseError(f"Unsupported pattern color mode: {color_mode}")
        rect, nchans, chans = _parse_vma_channels(body, want)
        if len(chans) < want:
            raise PatternParseError(
                f"Not enough pattern channels: need {want}, got {len(chans)} (pattern {index})")

        width = rect[3] - rect[1]
        height = rect[2] - rect[0]
        if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
            raise PatternParseError(f"Pattern size out of bounds: {width}x{height}")

        planes = []
        for depth, crect, compression, cdata in chans[:want]:
            w = crect[3] - crect[1]
            h = crect[2] - crect[0]
            if (w, h) != (width, height):
                raise PatternParseError(f"Channel rect does not match pattern: {crect}")
            planes.append(_decode_channel(cdata, depth, w, h, compression))
        if want == 3:
            image = np.stack(planes, axis=-1)
        else:
            image = planes[0]

        out[uuid] = PatternTexture(
            name=name, uuid=uuid, image=image,
            width=width, height=height, color_mode=color_mode,
            compression=chans[0][2],
        )
        pos = (record_end + 3) & ~3
        index += 1

    if pos != len(data):
        raise PatternParseError(
            f"patt section parse misaligned: stopped at {pos}, section length {len(data)}")
    return out
