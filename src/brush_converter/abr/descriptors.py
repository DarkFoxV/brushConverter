"""Photoshop Descriptor parsing.

The ABR desc section uses Photoshop's binary descriptor format (same as PSD/ASL).
Structure references the "Descriptor Structure" of the Adobe Photoshop File
Formats Specification, plus the open-source implementation SonyStone/ABR-Viewer (MIT).

Top-level desc block layout:
    u32  version (value ignored)
    Descriptor { unicode name, classID, itemCount, items[] }

Descriptor / Objc:
    unicode string : name (u32 character count + 2-byte UTF-16BE each)
    id             : classID (u32 len; 0 -> 4-byte four-char code, otherwise len bytes ASCII)
    u32            : itemCount
    items[]        : { key: id, type: 4-char code, value }

key / id reading (readId): u32 len; 0 -> the next 4 bytes are a four-char code; otherwise len bytes ASCII.

value types (type four-char code):
    'long'  int32          'doub'  float64        'bool'  1 byte
    'TEXT'  unicode string 'enum'  typeId+value   'UntF'  4-byte unit + float64
    'Objc'  Descriptor     'VlLs'  value list     'tdta'  u32 len + raw bytes
    'alis'  u32 len + raw bytes
    'obj '  / 'GlbO' / 'comp' / 'Glbc' etc.: rarely used, skipped per the rules
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


class DescParseError(ValueError):
    pass


@dataclass
class Value:
    type: str
    value: object = None
    unit: str | None = None      # UntF unit
    type_id: str | None = None   # enum's type id
    class_id: str | None = None  # Objc's classId
    data: bytes | None = None    # tdta/alis raw data

    def __repr__(self) -> str:  # for debugging
        if self.type == "Objc":
            return f"<Objc {self.class_id} keys={list(self.value.keys()) if isinstance(self.value, dict) else '?'}>"
        if self.type == "VlLs":
            return f"<VlLs {len(self.value)} items>"
        if self.type == "UntF":
            return f"<UntF {self.value} {self.unit}>"
        if self.type == "enum":
            return f"<enum {self.type_id}.{self.value}>"
        return f"<{self.type} {self.value!r}>"


class Reader:
    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None):
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    def remaining(self) -> int:
        return self.end - self.pos

    def _need(self, n: int) -> None:
        if self.pos + n > self.end:
            raise DescParseError(f"Descriptor out of bounds: need {n} bytes, {self.remaining()} remaining @ {self.pos}")

    def u8(self) -> int:
        self._need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        self._need(2)
        v = struct.unpack_from(">H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        self._need(4)
        v = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        self._need(4)
        v = struct.unpack_from(">i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f64(self) -> float:
        self._need(8)
        v = struct.unpack_from(">d", self.data, self.pos)[0]
        self.pos += 8
        return v

    def raw(self, n: int) -> bytes:
        self._need(n)
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def read_id(self) -> str:
        n = self.u32()
        if n == 0:
            return self.raw(4).decode("latin1")
        return self.raw(n).decode("latin1")

    def read_unicode(self) -> str:
        n = self.u32()
        if n == 0:
            return ""
        raw = self.raw(n * 2)
        return raw.decode("utf-16-be", "replace").rstrip("\x00")

    def read_descriptor(self) -> dict[str, Value]:
        name = self.read_unicode()
        class_id = self.read_id()
        count = self.u32()
        items: dict[str, Value] = {}
        for _ in range(count):
            key = self.read_id()
            items[key] = self.read_value()
        return items

    def read_value(self) -> Value:
        typ = self.raw(4).decode("latin1")
        if typ == "long":
            return Value("long", self.i32())
        if typ == "doub":
            return Value("doub", self.f64())
        if typ == "bool":
            return Value("bool", self.u8() != 0)
        if typ == "TEXT":
            return Value("TEXT", self.read_unicode())
        if typ == "enum":
            return Value("enum", self.read_id(), type_id=self.read_id())
        if typ == "UntF":
            unit = self.raw(4).decode("latin1")
            return Value("UntF", self.f64(), unit=unit)
        if typ == "Objc":
            obj = self.read_descriptor()
            return Value("Objc", obj)
        if typ == "VlLs":
            count = self.u32()
            return Value("VlLs", [self.read_value() for _ in range(count)])
        if typ == "tdta":
            n = self.u32()
            return Value("tdta", data=self.raw(n))
        if typ == "alis":
            n = self.u32()
            return Value("alis", data=self.raw(n))
        if typ == "obj ":
            _skip_object_reference(self)
            return Value("obj ", None)
        if typ in ("GlbO", "Glbc"):
            _skip_global_object(self)
            return Value(typ, None)
        if typ == "comp":
            self.read_id()          # classId
            self.read_unicode()     # name
            return Value("comp", None)
        # unknown type: length cannot be determined, raise to help locate it
        raise DescParseError(f"Unknown descriptor type: {typ!r} @ {self.pos - 4}")


def _skip_object_reference(r: Reader) -> None:
    """Skip 'obj ' type object references (rarely used; only need to locate lengths correctly)."""
    count = r.u32()
    for _ in range(count):
        ref = r.raw(4).decode("latin1")
        if ref in ("Clss", "Enmr", "name", "prop", "rele"):
            r.read_id(); r.read_id()
        if ref == "Enmr":
            r.read_id(); r.read_id()
        if ref == "Idnt":
            r.u32()
        if ref == "indx":
            r.u32()
        if ref == "name":
            r.read_unicode()
        if ref == "prop":
            r.read_id()
        if ref == "rele":
            r.u32()


def _skip_global_object(r: Reader) -> None:
    """Skip 'GlbO'/'Glbc' global objects (descriptor + classID)."""
    r.read_descriptor()
    r.read_id()  # classID


def parse_descriptor_block(data: bytes) -> dict[str, Value]:
    """Parse a complete desc section (including the 4-byte version prefix), returning the top-level descriptor."""
    r = Reader(data)
    version = r.u32()  # value ignored
    desc = r.read_descriptor()
    return desc


def iter_brush_presets(desc: dict[str, Value]) -> list[dict[str, Value]]:
    """Extract the brush preset list from the top-level descriptor ('Brsh' -> VlLs -> Objc)."""
    brsh = desc.get("Brsh")
    if brsh is None or brsh.type != "VlLs":
        return []
    out = []
    for item in brsh.value:
        if item.type == "Objc" and isinstance(item.value, dict):
            out.append(item.value)
    return out


def get_text(d: dict[str, Value], key: str) -> str | None:
    v = d.get(key)
    if v is not None and v.type in ("TEXT", "enum"):
        return str(v.value)
    return None


def get_number(d: dict[str, Value], key: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    if v.type in ("long", "doub", "UntF"):
        return float(v.value)
    return None


def get_bool(d: dict[str, Value], key: str) -> bool | None:
    v = d.get(key)
    if v is not None and v.type == "bool":
        return bool(v.value)
    return None


def get_obj(d: dict[str, Value], key: str) -> dict[str, Value] | None:
    v = d.get(key)
    if v is not None and v.type == "Objc" and isinstance(v.value, dict):
        return v.value
    return None
