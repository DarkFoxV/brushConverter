"""Conversion pipeline: .abr → Krita presets (.kpp) and resource bundles (.bundle)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .abr import AbrFile
from .mapping import BrushPreset, TextureSettings, map_presets, _TEXTURING_MODE
from .kpp import TextureXml, build_preset_xml, write_kpp, write_bundle
from .kpp.kpp_writer import render_tip_preview


def _png_bytes(gray: np.ndarray) -> bytes:
    """Grayscale mask (255 = ink) → PNG bytes (8-bit L channel)."""
    buf = io.BytesIO()
    Image.fromarray(gray, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _square_tip(gray: np.ndarray) -> np.ndarray:
    """Center the sampled tip on a square canvas to avoid Krita's size display bias for non-square tips."""
    if gray.ndim != 2:
        raise ValueError("Brush tip mask must be a 2D grayscale array")
    h, w = gray.shape
    side = max(h, w)
    if h == side and w == side:
        return gray
    # ABR/Krita tip masks follow the convention 255 = white stroke (ink), 0 = transparent;
    # fill with white so Krita does not treat the transparent border as the tip
    # boundary when computing the size.
    canvas = np.full((side, side), 255, dtype=gray.dtype)
    y = (side - h) // 2
    x = (side - w) // 2
    canvas[y:y + h, x:x + w] = gray
    return canvas


def _texture_png(texture: TextureSettings) -> bytes:
    """Texture bitmap → PNG bytes (RGB or grayscale, pixels unchanged)."""
    buf = io.BytesIO()
    img = texture.image
    if img.ndim == 3 and img.shape[2] == 3:
        Image.fromarray(img, mode="RGB").save(buf, format="PNG")
    else:
        Image.fromarray(img, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _texture_xml(bp: BrushPreset) -> TextureXml | None:
    """Map Photoshop texture parameters to Krita texture options (None when there is no bitmap).

    The mapping targets the final effect after Krita mode compositing; the calibration
    constants come from the research test-results and Krita-results data
    rather than Photoshop's intermediate texture values.
    """
    tex = bp.texture
    if tex is None or tex.image is None:
        return None
    filename = f"tex_{tex.uuid[:8]}.png" if tex.uuid else "texture.png"
    # Krita source's KisTextureMaskInfo executes directly:
    #   maskValue -= brightness
    #   maskValue = ((maskValue - 0.5) * contrast) + 0.5
    # Krita brightness applies to the 0..1 mask; the source performs the subtraction first.
    # Final composite scale from the quantitative comparison: 0.10 is the Krita
    # baseline for PS=0, and every 25 PS brightness units roughly correspond to an
    # inverse change of 0.10 in Krita.
    # All modes use this plain mapping (Linear Height (Photoshop) once used a 0.30
    # baseline; measured results were poor, so the special mapping was dropped on 2026-08-27).
    brightness = 0.10 - tex.brightness / 250.0
    # The Krita UI/presets actually keep only two decimal places.
    brightness = max(-1.0, min(1.0, round(brightness, 2)))
    if brightness == 0:
        brightness = 0.0
    # Quantitative tests show Photoshop contrast is the piecewise factor of a modern
    # adjustment layer, and Krita's Contrast parameter takes exactly this central
    # multiplicative factor:
    #   C < 0: factor = 1 + C/100
    #   C >= 0: factor = 1/(1 - C/100)
    # e.g. -50→0.5, 25→1.333..., 50→2, 75→4; +100
    # theoretically tends to infinity, so a large value approximates its full binarizing effect.
    c = max(-50.0, min(100.0, tex.contrast))
    if c < 0.0:
        ps_factor = 1.0 + c / 100.0
    elif c >= 100.0:
        ps_factor = 1_000_000.0
    else:
        ps_factor = 1.0 / (1.0 - c / 100.0)
    # All modes use the PS central factor (Linear Height (Photoshop) once used its
    # reciprocal; measured results were poor, so the special mapping was dropped on 2026-08-27).
    contrast = ps_factor
    # The Krita Contrast UI/config is exact to two decimals and its valid range is 0..2.
    contrast = max(0.0, min(2.0, round(contrast, 2)))
    return TextureXml(
        pattern_filename=filename,
        png_bytes=_texture_png(tex),
        scale=max(0.01, min(10.0, tex.scale / 100.0)),
        brightness=brightness,
        contrast=contrast,
        invert=tex.invert,
        texturing_mode=_TEXTURING_MODE.get(tex.blend_mode, 0),
        # Krita docs state explicitly: except for Height/Linear Height, Soft Texturing
        # is closer to Photoshop; the PS-specific Height mode itself does not enable that optimization.
        use_soft_texturing=(tex.blend_mode not in {
            "Hght", "height", "HghtPS", "linearHeight",
            "linearHeightPhotoshop", "linearHeightPS",
        }),
        strength=max(0.0, min(100.0, tex.depth)) / 100.0,
        strength_curve=f"0,{max(0.0, min(100.0, tex.depth_min)) / 100.0:g};1,1;"
        if tex.pressure else None,
        strength_pressure=tex.pressure,
    )


def _safe_filename(name: str, index: int) -> str:
    """Clean a Chinese name into a safe .kpp filename (3-digit index prefix)."""
    cleaned = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    cleaned = cleaned or "brush"
    return f"{index:03d}_{cleaned}.kpp"


def _circle_mask(diameter: float, hardness: float, roundness: float,
                 size: int = 256) -> np.ndarray:
    """Generate a circular grayscale mask from diameter/hardness/roundness (for computed brush previews)."""
    s = size
    yy, xx = np.mgrid[0:s, 0:s].astype(np.float64)
    cy = cx = (s - 1) / 2.0
    radius = diameter / 2.0 * (s / max(diameter, 1.0)) * 0.9  # occupies 90% of the canvas
    ratio = roundness / 100.0
    dx = (xx - cx) / radius
    dy = (yy - cy) / (radius * ratio)
    dist = np.sqrt(dx * dx + dy * dy)
    # hardness → edge softness; hardness 100 = hard edge, 0 = fully soft
    soft = max(0.02, (100.0 - hardness) / 100.0)
    falloff = 1.0 / (soft * 3.0 + 0.01)
    mask = np.clip(1.0 - dist, 0.0, 1.0)
    mask = np.clip(mask * falloff + (1.0 - falloff) * (dist <= 1.0), 0.0, 1.0)
    return (mask * 255.0).astype(np.uint8)


@dataclass
class ConvertResult:
    kpp_files: list[tuple[str, bytes]] = field(default_factory=list)
    bundle_path: str | None = None
    out_dir: str = ""
    presets: list[BrushPreset] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def convert(abr_path: str, out_dir: str, make_bundle: bool = True,
            make_standalone: bool = True) -> ConvertResult:
    """Convenience CLI entry point: parse a single .abr file and convert all presets.

    Returns a ConvertResult; the GUI uses convert_presets() to support converting a subset.
    """
    abr = AbrFile.parse(abr_path)
    presets = map_presets(abr)
    return convert_presets(abr, presets, out_dir, make_bundle=make_bundle,
                           make_standalone=make_standalone)


def _render_preset(bp: BrushPreset, index: int) -> tuple[str, str, np.ndarray]:
    """Render a single preset → (filename, preset XML, preview RGBA)."""
    if bp.tip_gray is None and not bp.is_computed:
        raise ValueError(f"{bp.name}: no tip bitmap")

    if bp.is_computed:
        tip_png = None
        brush_def = _computed_brush_def(bp)
        preview = render_tip_preview(
            _circle_mask(bp.diameter or 30.0, bp.hardness if bp.hardness is not None else 100.0,
                         bp.roundness, 256))
    else:
        # Krita's editor size display is biased for non-square png_brush;
        # keep it consistent with the max(width,height) basis used during mapping
        # by embedding a square tip.
        square_tip = _square_tip(bp.tip_gray)
        tip_png = _png_bytes(square_tip)
        res_name = _safe_filename(bp.name, index).rsplit(".", 1)[0]
        brush_def = _sampled_brush_def(res_name, tip_png, bp)
        preview = render_tip_preview(bp.tip_gray)

    xml = build_preset_xml(
        name=bp.name,
        brush_definition=brush_def,
        tip_png=tip_png,
        tip_name=_safe_filename(bp.name, index).rsplit(".", 1)[0] if tip_png else None,
        size_curve=bp.size_curve,
        opacity_curve=bp.opacity_curve,
        flow_curve=bp.flow_curve,
        ratio_curve=bp.ratio_curve,
        rotation_sensor=bp.rotation_sensor,
        rotation_jitter=bp.rotation_jitter,
        scatter=bp.scatter,
        scatter_pressure=bp.scatter_pressure,
        scatter_both_axes=bp.scatter_both_axes,
        scatter_amount=bp.scatter_amount,
        color_jitter=bp.color_jitter,
        texture=_texture_xml(bp),
    )
    return _safe_filename(bp.name, index), xml, preview


def convert_presets(abr: AbrFile, presets: list[BrushPreset], out_dir: str,
                    make_bundle: bool = True, make_standalone: bool = True) -> ConvertResult:
    """Convert the given subset of presets into .kpp / .bundle.

    At least one of make_bundle / make_standalone must be True, corresponding to the
    ".bundle" and ".kpp" outputs.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    result = ConvertResult(out_dir=str(out), presets=presets)
    kpp_dir = out / "kpp"
    if make_standalone:
        kpp_dir.mkdir(parents=True, exist_ok=True)

    for i, bp in enumerate(presets):
        if bp.tip_gray is None and not bp.is_computed:
            result.skipped.append(f"{bp.name}: no tip bitmap")
            continue
        fname, xml, preview = _render_preset(bp, i)
        result.kpp_files.append((fname, _build_kpp_bytes(xml, preview)))
        if make_standalone:
            write_kpp(str(kpp_dir / fname), xml, preview)

    if make_bundle and result.kpp_files:
        stem = getattr(abr, "name", None) or "converted"
        # tag every brush in the bundle with the source .abr name (user request)
        result.bundle_path = write_bundle(str(out / f"{stem}.bundle"), result.kpp_files,
                                          tag=stem)
    return result


def _sampled_brush_def(res_name: str, tip_png: bytes, bp: BrushPreset) -> str:
    """Build the png_brush <Brush> definition for a sampled tip (filename + md5sum reference the embedded PNG)."""
    import hashlib
    from .kpp.preset_xml import sampled_brush_definition
    md5 = hashlib.md5(tip_png).hexdigest()
    return sampled_brush_definition(res_name + ".png", md5, bp.spacing, bp.angle, bp.scale)


def _computed_brush_def(bp: BrushPreset) -> str:
    """Build the auto_brush <Brush> definition for a computed brush (procedural circular tip)."""
    from .kpp.preset_xml import auto_brush_definition
    return auto_brush_definition(bp.diameter or 30.0, bp.spacing, bp.angle,
                                 bp.roundness, bp.hardness)


def _build_kpp_bytes(xml: str, preview_rgba: np.ndarray) -> bytes:
    """Encode the preset XML + preview RGBA into complete .kpp bytes."""
    from .kpp.kpp_writer import build_kpp
    return build_kpp(xml, preview_rgba)
