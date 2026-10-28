"""ABR file-level reading: header + 8BIM section traversal."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

from .patterns import PatternTexture, parse_patterns
from .samples import BrushTip, parse_samples


@dataclass
class AbrSection:
    """Raw data of one 8BIM section."""

    key: str
    offset: int  # start of the data area (absolute)
    length: int
    data: bytes


@dataclass
class AbrFile:
    """Parsed ABR file.

    Attributes
    ----------
    version : major version (1/2 old format, 6/10 new format)
    subversion : brush count in the old format; sub-version (1 or 2) in the new format
    sections : {key: AbrSection}
    tips : sampled brush tip list parsed from the samp section
    """

    version: int
    subversion: int
    sections: dict[str, AbrSection] = field(default_factory=dict)
    tips: list[BrushTip] = field(default_factory=list)
    patterns: dict[str, PatternTexture] = field(default_factory=dict)  # patt textures {uuid: PatternTexture}
    name: str = ""  # file name (without extension)

    @classmethod
    def parse(cls, path: str | os.PathLike) -> "AbrFile":
        path = os.fspath(path)
        with open(path, "rb") as f:
            data = f.read()
        base_name = os.path.splitext(os.path.basename(path))[0]
        return cls._from_bytes(data, base_name)

    @classmethod
    def _from_bytes(cls, data: bytes, base_name: str) -> "AbrFile":
        if len(data) < 4:
            raise ValueError("File too small, not an ABR")
        version, subversion = struct.unpack_from(">HH", data, 0)

        sections: dict[str, AbrSection] = {}
        if version in (6, 10):
            pos = 4
            while pos + 12 <= len(data):
                sig, key = data[pos : pos + 4], data[pos + 4 : pos + 8]
                if sig != b"8BIM":
                    break
                (length,) = struct.unpack_from(">I", data, pos + 8)
                start = pos + 12
                if start + length > len(data):
                    length = len(data) - start  # the last section may have no padding
                sections[key.decode("latin1")] = AbrSection(
                    key=key.decode("latin1"), offset=start, length=length,
                    data=data[start : start + length],
                )
                pos = start + length + (length % 4)

        abr = cls(version=version, subversion=subversion, sections=sections, name=base_name)
        samp = sections.get("samp")
        if samp is not None:
            abr.tips = parse_samples(samp.data, version, subversion, base_name)
        elif version in (1, 2):
            abr.tips = parse_samples(data, version, subversion, base_name)
        patt = sections.get("patt")
        if patt is not None:
            abr.patterns = parse_patterns(patt.data)
        return abr

    @property
    def has_descriptors(self) -> bool:
        return "desc" in self.sections

    @property
    def has_patterns(self) -> bool:
        return "patt" in self.sections

    def summary(self) -> str:
        lines = [
            f"Version: {self.version}.{self.subversion}",
            f"Sections: {', '.join(f'{k}({v.length}B)' for k, v in self.sections.items()) or '(old format, no sections)'}",
            f"Sampled tips: {len(self.tips)}",
            f"Texture patterns: {len(self.patterns)}",
        ]
        for t in self.tips:
            name = t.uuid or t.name or ""
            lines.append(f"  [{t.index}] {t.width}x{t.height} {t.depth_bits}bit {name}")
        return "\n".join(lines)
