"""Package a Krita resource bundle (.bundle).

A .bundle is a ZIP archive whose layout (strictly matching Krita's
KoResourceBundle write format) is:
    mimetype                        (first entry, stored uncompressed, application/x-krita-resourcebundle)
    META-INF/manifest.xml           (OpenDocument manifest namespace)
    meta.xml                        (OpenDocument meta)
    paintoppresets/*.kpp            (brush presets, self-contained with embedded tip)
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

MIMETYPE = "application/x-krita-resourcebundle"
NS_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
NS_META = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
NS_DC = "http://purl.org/dc/elements/1.1"
RES_TYPE = "paintoppresets"


def _manifest_xml(entries: list[tuple[str, str]], tag: str | None = None) -> str:
    """entries: [(filename, md5hex)]; tag: applied to every resource.

    Krita reads a per-file-entry <manifest:tags><manifest:tag> element
    (KoResourceBundleManifest::parseFileEntry) and registers each one in the
    resource_tags cache on bundle import, so every brush shows the tag.
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<manifest:manifest xmlns:manifest="{NS_MANIFEST}" manifest:version="1.2">',
        '<manifest:file-entry manifest:full-path="/" '
        f'manifest:media-type="{MIMETYPE}"/>',
    ]
    for fname, md5 in entries:
        entry = (
            f'<manifest:file-entry manifest:media-type="{RES_TYPE}" '
            f'manifest:full-path="{RES_TYPE}/{fname}" manifest:md5sum="{md5}">'
        )
        if tag:
            entry += f"<manifest:tags><manifest:tag>{escape(tag)}</manifest:tag></manifest:tags>"
        entry += "</manifest:file-entry>"
        lines.append(entry)
    lines.append("</manifest:manifest>")
    return "".join(lines)


def _meta_xml(bundle_name: str) -> str:
    """Generate the OpenDocument meta.xml (bundle name / version / description)."""
    name = escape(bundle_name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document-meta>\n'
        f'<meta:meta xmlns:meta="{NS_META}" xmlns:dc="{NS_DC}">\n'
        '<meta:generator>brushConverter</meta:generator>\n'
        '<meta:bundle-version>1</meta:bundle-version>\n'
        f'<dc:title>{name}</dc:title>\n'
        '<dc:description>Converted from Photoshop ABR</dc:description>\n'
        '</meta:meta>\n'
        '</office:document-meta>'
    )


def write_bundle(bundle_path: str, kpp_files: list[tuple[str, bytes]],
                 tag: str | None = None) -> str:
    """Package .kpp files into a .bundle.

    Parameters
    ----------
    bundle_path : output .bundle path
    kpp_files : [(filename, file bytes)], placed into the paintoppresets/ directory
    tag : optional tag applied to every brush in the bundle (e.g. the source .abr stem)
    """
    name = Path(bundle_path).stem
    entries: list[tuple[str, str]] = []
    for fname, data in kpp_files:
        entries.append((fname, hashlib.md5(data).hexdigest()))

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/manifest.xml", _manifest_xml(entries, tag=tag))
        zf.writestr("meta.xml", _meta_xml(name))
        for fname, data in kpp_files:
            zf.writestr("paintoppresets/" + fname, data)
    return bundle_path
