"""Photoshop PackBits RLE decoding.

Data layout (same as PSD image channels):
- first, height int16 (big-endian) compressed lengths, one per row
- then an independent PackBits stream per row:
  * n is a signed byte; n >= 0: the next n+1 bytes are literals
  * n < 0 (n != -128): the next 1 byte is repeated -n+1 times
  * n == -128: no-op
"""

from __future__ import annotations

import struct

import numpy as np


def rle_decode(buf: memoryview | bytes, expected_size: int, height: int) -> np.ndarray:
    """Decode RLE data of ABR sampled brush tips.

    Parameters
    ----------
    buf : compressed data (including the row length table)
    expected_size : total byte count after decompression (width * height * bytes_per_pixel)
    height : number of scan lines
    Returns
    -------
    np.ndarray : one-dimensional uint8 array of length expected_size
    """
    counts = struct.unpack_from(f">{height}h", buf, 0)
    offset = height * 2
    out = np.empty(expected_size, dtype=np.uint8)
    pos = 0
    for line_len in counts:
        if line_len <= 0:
            raise ValueError(f"Invalid scanline length: {line_len}")
        line_end = offset + line_len
        if line_end > len(buf):
            raise ValueError("RLE data truncated")
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
                if j + 1 > line_end or pos + run > expected_size:
                    raise ValueError("RLE decode out of bounds (repeat run)")
                out[pos : pos + run] = buf[j]
                j += 1
                pos += run
            else:
                run = n + 1
                if j + run > line_end or pos + run > expected_size:
                    raise ValueError("RLE decode out of bounds (literal run)")
                out[pos : pos + run] = np.frombuffer(
                    buf, dtype=np.uint8, count=run, offset=j)
                j += run
                pos += run
        offset = line_end
    if pos != expected_size:
        raise ValueError(f"RLE decoded size mismatch: got {pos}, expected {expected_size}")
    return out
