"""Bundle tag tests: every brush carries the source .abr name as a Krita tag (no sample needed)."""

from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brush_converter.kpp.bundle import NS_MANIFEST, write_bundle  # noqa: E402

_NS = f"{{{NS_MANIFEST}}}"
_KPPS = [("brush_a.kpp", b"aaa"), ("brush_b.kpp", b"bbb")]


def _manifest_tags(bundle_path: str) -> dict[str, list[str]]:
    """Read per-resource tags the way Krita does (file-entry -> tags -> tag)."""
    with zipfile.ZipFile(bundle_path) as zf:
        root = ET.fromstring(zf.read("META-INF/manifest.xml"))
    out: dict[str, list[str]] = {}
    for entry in root.findall(f"{_NS}file-entry"):
        path = entry.get(f"{_NS}full-path")
        if path in (None, "/"):
            continue
        out[path] = [
            (t.text or "")
            for t in entry.findall(f"{_NS}tags/{_NS}tag")
        ]
    return out


def test_every_brush_gets_abr_stem_tag(tmp_path):
    bundle = str(tmp_path / "Devin_Elle_Kurtz_Plant_Brushes.bundle")
    write_bundle(bundle, _KPPS, tag="Devin_Elle_Kurtz_Plant_Brushes")

    tags = _manifest_tags(bundle)
    assert set(tags) == {"paintoppresets/brush_a.kpp", "paintoppresets/brush_b.kpp"}
    assert all(t == ["Devin_Elle_Kurtz_Plant_Brushes"] for t in tags.values())


def test_bundle_without_tag_has_no_tag_elements(tmp_path):
    bundle = str(tmp_path / "plain.bundle")
    write_bundle(bundle, _KPPS)

    with zipfile.ZipFile(bundle) as zf:
        manifest = zf.read("META-INF/manifest.xml").decode()
    assert "manifest:tags" not in manifest
    assert all(not t for t in _manifest_tags(bundle).values())


def test_tag_is_xml_escaped_and_round_trips(tmp_path):
    bundle = str(tmp_path / "x.bundle")
    write_bundle(bundle, _KPPS, tag='Weird & <Name> "tag"')

    with zipfile.ZipFile(bundle) as zf:
        manifest = zf.read("META-INF/manifest.xml").decode()
    assert "Weird &amp; &lt;Name&gt;" in manifest  # raw & must be escaped
    assert all(
        t == ['Weird & <Name> "tag"'] for t in _manifest_tags(bundle).values()
    )


def test_bundle_layout_still_valid(tmp_path):
    bundle = str(tmp_path / "layout.bundle")
    write_bundle(bundle, _KPPS, tag="sometag")

    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
        info = zf.getinfo("mimetype")
    # Krita requires: mimetype first, stored uncompressed, then manifest/meta/paintoppresets
    assert names[0] == "mimetype"
    assert info.compress_type == zipfile.ZIP_STORED
    assert {"META-INF/manifest.xml", "meta.xml"} <= set(names)
    assert "paintoppresets/brush_a.kpp" in names
