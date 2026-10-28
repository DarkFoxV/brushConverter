"""Mapping of ABR descriptors → brush preset parameters.

Mapping strategy (calibrated item by item against Krita 5.x reference presets
manually converted by the user):
  - Size: scale = Dmtr / tip width (respects Photoshop's master diameter)
  - Spacing / angle: mapped directly
  - Pressure → size: minimumDiameter (szVr.bVTy==2 pressure)
  - Pressure → opacity: opVr.Mnm (opVr.bVTy==2)
  - Pressure → flow: prVr.Mnm (prVr.bVTy==2)
  - Pressure → aspect ratio: minimumRoundness (roundnessDynamics.bVTy==2)
  - Rotation: angleDynamics.bVTy==6 → follows stroke direction (drawingangle); jitter
    becomes the Krita RotationValue effect strength, randomness curve fixed at ±180°
  - Scatter: useScatter → enable switch; scatterDynamics.jitter → scatter amount
    (empirical conversion ScatterValue = jitter/400, see the scatter branch in preset_xml.py)
    bVTy==2 → pressure-controlled, bVTy==0 → constant; bothAxes → both axes
  - Texture: brightness/contrast calibrated via Krita mode compositing; Linear Height
    (Photoshop) uses a separate baseline and an inverted contrast mapping;
    Krita UI values are output with two decimals
  - Computed brushes → Krita auto_brush
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .abr import AbrFile
from .abr import descriptors as D


# Photoshop texture blend modes (enum BlnM members) → Krita TexturingMode values.
# Unlisted modes fall back to Multiply(0), noted in the warning (see _collect_warnings).
_TEXTURING_MODE = {
    # Krita KisTextureOptionData::TexturingMode enum (Krita master/6.x)
    "Mul ": 0,           # MULTIPLY
    "Sbtr": 1,           # SUBTRACT
    "Lght": 2,           # LIGHTNESS
    "Grdn": 3,           # GRADIENT
    "Drkn": 4,           # DARKEN
    "Ovrl": 5,           # OVERLAY
    "CDdg": 6,           # COLOR_DODGE
    "CBrn": 7,           # COLOR_BURN
    "LDdg": 8,           # LINEAR_DODGE
    "LBur": 9,           # LINEAR_BURN
    "HdMx": 10,          # HARD_MIX_PHOTOSHOP
    "HdMxS": 11,         # HARD_MIX_SOFTER_PHOTOSHOP
    "Hght": 14,          # HEIGHT_PHOTOSHOP (actual value from the test sample)
    "hardMix": 10,       # HARD_MIX_PHOTOSHOP (actual value from the test sample)
    # Photoshop-specific modes must preferentially use Krita's (Photoshop) entries;
    # ABR's linearHeight is Photoshop's Linear Height.
    "linearHeight": 15,  # LINEAR_HEIGHT_PHOTOSHOP
    "height": 14,        # HEIGHT_PHOTOSHOP
    "linearHeightPhotoshop": 15,  # LINEAR_HEIGHT_PHOTOSHOP
    "linearHeightPS": 15,
    "HghtPS": 14,
}


@dataclass
class TextureSettings:
    """Texture settings of one brush preset (texture parameters from the ABR desc + the patt bitmap).

    scale/brightness/contrast/depth keep Photoshop's original semantics:
    scale: textureScale % (0..100); brightness/contrast: -100..100;
    depth: textureDepth % (0..100).
    """

    name: str
    uuid: str
    scale: float = 100.0
    invert: bool = False
    brightness: int = 0       # Photoshop texture brightness: -150..150
    contrast: int = 0         # Photoshop texture contrast: -50..100
    depth: float = 100.0
    depth_min: float = 0.0      # minimum of the pressure→depth curve (textureDepthDynamics.Mnm)
    pressure: bool = False      # depth follows pressure (bVTy==2)
    blend_mode: str = "Mul "    # PS 4CC member ('linearHeight' etc.)
    image: np.ndarray | None = None  # (h,w,3) RGB or (h,w) grayscale, from patt


@dataclass
class BrushPreset:
    name: str
    spacing: float = 0.25          # 0..1 (Krita spacing is a fraction of the diameter)
    angle: float = 0.0             # degrees
    roundness: float = 100.0       # 0..100 (100 = circle)
    diameter: float | None = None  # px (computed brushes)
    hardness: float | None = None  # 0..100 (computed brushes)
    scale: float = 1.0             # sampled brush scale (Dmtr / tip width)
    tip_gray: np.ndarray | None = None   # sampled tip mask (255 = ink)
    uuid: str | None = None
    is_computed: bool = False
    size_curve: str | None = None       # "x,y;x,y;"
    opacity_curve: str | None = None
    flow_curve: str | None = None
    ratio_curve: str | None = None
    rotation_sensor: str | None = None  # "pressure" | "drawingangle" | None
    rotation_jitter: float = 0.0
    scatter: bool = False                 # useScatter → scatter option enabled
    scatter_pressure: bool = False        # scatterDynamics.bVTy==2 → scatter amount follows pressure
    scatter_both_axes: bool = False
    scatter_amount: float | None = None   # PS scatter amount (scatterDynamics.jitter, 0..1000%)
    color_jitter: tuple[float, float, float] | None = None  # PS color dynamics (H, Strt, Brgh) 0..100%
    texture: TextureSettings | None = None  # texture settings (set when useTexture and a pattern is found)
    warnings: list[str] = field(default_factory=list)  # English names of unmapped parameters
    meta: dict = field(default_factory=dict)


def _norm_uuid(s: str) -> str:
    """Normalize UUID: strip NULs, strip spaces, lowercase, truncate to 36 chars."""
    return s.replace("\x00", "").strip().lower()[:36]


def _dyn(obj: dict[str, D.Value] | None) -> dict[str, float]:
    """Extract the numeric fields from a dynamics object (szVr/opVr etc.): bVTy/fStp/jitter/Mnm."""
    if obj is None:
        return {}
    return {
        k: float(v.value)
        for k, v in obj.items()
        if v.type in ("long", "doub", "UntF")
    }


def _texture_blend_mode(p: dict[str, D.Value]) -> str:
    """Read the textureBlendMode enum member (e.g. 'linearHeight').

    The descriptor parser stores an enum as value=class id('BlnM'), type_id=member id;
    the semantic value lives on type_id (same as toolOptions.Md's 'Nrml').
    """
    v = p.get("textureBlendMode")
    if v is not None and v.type == "enum" and isinstance(v.type_id, str):
        return v.type_id
    return "Mul "


def _map_texture(p: dict[str, D.Value],
                 patterns: dict[str, object]) -> TextureSettings | None:
    """Extract texture settings from a useTexture preset (including the patt bitmap lookup by UUID)."""
    tex_obj = D.get_obj(p, "Txtr") or {}
    tex_uuid = D.get_text(tex_obj, "Idnt")
    tex_name = D.get_text(tex_obj, "Nm  ")
    pat = patterns.get(tex_uuid) if tex_uuid else None
    tdd = _dyn(D.get_obj(p, "textureDepthDynamics"))
    min_depth = D.get_number(p, "minimumDepth")
    return TextureSettings(
        name=tex_name or (getattr(pat, "name", None) or tex_uuid or "texture"),
        uuid=tex_uuid or "",
        scale=D.get_number(p, "textureScale") or 100.0,
        invert=D.get_bool(p, "InvT") or False,
        brightness=int(D.get_number(p, "textureBrightness") or 0),
        contrast=int(D.get_number(p, "textureContrast") or 0),
        depth=D.get_number(p, "textureDepth") or 100.0,
        depth_min=float(tdd.get("Mnm ", min_depth or 0.0)),
        pressure=tdd.get("bVTy") == 2,
        blend_mode=_texture_blend_mode(p),
        image=getattr(pat, "image", None),
    )


def _bvty_sensor(bvty: float | None) -> str | None:
    """Photoshop bVTy control source → Krita sensor id."""
    if bvty is None:
        return None
    b = int(bvty)
    if b == 2:          # pressure
        return "pressure"
    if b in (6, 7):     # initial direction / direction
        return "drawingangle"
    if b == 3:          # tilt
        return "tilt"
    return None         # 0=off, 1=fade, 4=wheel, 5=rotation not mapped yet


def _color_jitter(p: dict[str, D.Value]) -> tuple[float, float, float] | None:
    """PS color dynamics jitters (H, Strt, Brgh in the clVr group), 0..100% each.

    Returns None when color dynamics is off. Descriptor keys are 4 chars ("H  ",
    "Strt", "Brgh"), so each name is tried padded as well as bare.
    """
    if not D.get_bool(p, "useColorDynamics"):
        return None
    cd = D.get_obj(p, "clVr") or {}

    def jitter(key: str) -> float:
        for k in (key, key.ljust(4)):
            n = D.get_number(cd, k)
            if n is None:
                n = D.get_number(p, k)
            if n is not None:
                return max(0.0, min(100.0, float(n)))
        return 0.0

    return (jitter("H"), jitter("Strt"), jitter("Brgh"))


def map_presets(abr: AbrFile) -> list[BrushPreset]:
    """Map a parsed ABR to a list of BrushPreset (with deduplication).

    Without a desc section (rare old files), falls back to generating a default preset per tip.
    """
    if "desc" not in abr.sections:
        return [
            BrushPreset(name=f"brush-{t.index + 1:03d}",
                        spacing=0.25, tip_gray=t.gray, uuid=t.uuid,
                        scale=1.0)
            for t in abr.tips
        ]

    top = D.parse_descriptor_block(abr.sections["desc"].data)
    presets = D.iter_brush_presets(top)

    patterns = getattr(abr, "patterns", None) or {}

    tip_by_uuid: dict[str, object] = {}
    for t in abr.tips:
        if t.uuid:
            tip_by_uuid[_norm_uuid(t.uuid)] = t

    out: list[BrushPreset] = []
    for p in presets:
        name = D.get_text(p, "Nm  ") or D.get_text(p, "name") or "Unnamed"
        brsh = D.get_obj(p, "Brsh") or {}

        spacing = (D.get_number(brsh, "Spcn") or 25.0) / 100.0
        angle = D.get_number(brsh, "Angl") or 0.0
        roundness = D.get_number(brsh, "Rndn")
        roundness = roundness if roundness is not None else 100.0
        diameter = D.get_number(brsh, "Dmtr")
        hardness = D.get_number(brsh, "Hrdn")

        uuid_raw = None
        sd = brsh.get("sampledData")
        if sd is not None and sd.type == "TEXT":
            uuid_raw = str(sd.value)
        tip = tip_by_uuid.get(_norm_uuid(uuid_raw)) if uuid_raw else None

        scale = 1.0
        if tip is not None and diameter is not None:
            # A sampled brush's scale in Krita is based on a square tip canvas; a
            # non-square tip still using width would make the preset editor display a
            # size inconsistent with the actual painting area.
            scale = diameter / max(1, tip.width, tip.height)

        # bVTy / numeric values of each dynamics object
        sz = _dyn(D.get_obj(p, "szVr"))
        ang = _dyn(D.get_obj(p, "angleDynamics"))
        rnd = _dyn(D.get_obj(p, "roundnessDynamics"))
        opv = _dyn(D.get_obj(p, "opVr"))
        prv = _dyn(D.get_obj(p, "prVr"))
        sct = _dyn(D.get_obj(p, "scatterDynamics"))

        min_diameter = D.get_number(p, "minimumDiameter")
        min_roundness = D.get_number(p, "minimumRoundness")

        size_curve = None
        if sz.get("bVTy") == 2:
            m = 0.0 if min_diameter is None else max(0.0, min(100.0, min_diameter))
            size_curve = f"0,{m / 100.0:g};1,1;"

        opacity_curve = None
        if opv.get("bVTy") == 2:
            m = max(0.0, min(100.0, opv.get("Mnm ", 0.0)))
            opacity_curve = f"0,{m / 100.0:g};1,1;"

        flow_curve = None
        if prv.get("bVTy") == 2:
            m = max(0.0, min(100.0, prv.get("Mnm ", 0.0)))
            flow_curve = f"0,{m / 100.0:g};1,1;"

        ratio_curve = None
        if rnd.get("bVTy") == 2:
            m = 0.0 if min_roundness is None else max(0.0, min(100.0, min_roundness))
            ratio_curve = f"0,{m / 100.0:g};1,1;"

        rotation_sensor = _bvty_sensor(ang.get("bVTy"))
        rotation_jitter = ang.get("jitter", 0.0)

        scatter = D.get_bool(p, "useScatter") or False
        scatter_pressure = sct.get("bVTy") == 2
        scatter_both_axes = D.get_bool(p, "bothAxes") or False
        # The PS scatter amount lives in scatterDynamics.jitter (#Prc, 0..1000%); the top-level Spcn is spacing
        scatter_amount = sct.get("jitter") if (scatter and "jitter" in sct) else None

        texture = _map_texture(p, patterns) if D.get_bool(p, "useTexture") else None
        color_jitter = _color_jitter(p)
        warnings = _collect_warnings(p, texture)
        # Rotation control source bVTy=1(fade)/3(tilt)/4(wheel)/5(rotation) is not mapped yet;
        # jitter>0 means the effect actually exists in PS, so the lost effect needs a warning.
        if rotation_jitter > 0 and ang.get("bVTy") not in (0, 2, 6, 7, None):
            warnings.append(f"Rotation control source (bVTy={int(ang['bVTy'])} not mapped)")

        out.append(BrushPreset(
            name=name,
            spacing=spacing,
            angle=angle,
            roundness=roundness,
            diameter=diameter,
            hardness=hardness,
            scale=scale,
            tip_gray=tip.gray if tip is not None else None,
            uuid=uuid_raw,
            is_computed=(tip is None),
            size_curve=size_curve,
            opacity_curve=opacity_curve,
            flow_curve=flow_curve,
            ratio_curve=ratio_curve,
            rotation_sensor=rotation_sensor,
            rotation_jitter=rotation_jitter,
            scatter=scatter,
            scatter_pressure=scatter_pressure,
            scatter_both_axes=scatter_both_axes,
            scatter_amount=scatter_amount,
            texture=texture,
            color_jitter=color_jitter,
            warnings=warnings,
            meta={"Dmtr": diameter, "Hrdn": hardness, "Rndn": roundness, "Spcn": spacing * 100.0},
        ))
    return _dedupe(out)


def _collect_warnings(p: dict[str, D.Value],
                          texture: TextureSettings | None = None) -> list[str]:
    """Collect the parameters of the current preset that are not mapped (for a GUI popup)."""
    warnings: list[str] = []
    if D.get_bool(p, "useTexture"):
        # The texture body is already mapped: keep only lightweight warnings for anomalies / fallbacks / missing counterparts
        if texture is None or texture.image is None:
            warnings.append("Texture (pattern missing)")
        elif texture.blend_mode not in _TEXTURING_MODE:
            warnings.append(f"Texture blend mode ({texture.blend_mode!r} falls back to Multiply)")
        if D.get_bool(p, "protectTexture"):
            warnings.append("Texture (protectTexture not mapped)")
        # TxtC(Texture Each Tip) / interpretation has no counterpart in Krita but is this
        # file's default, so it is silently ignored (as agreed with the user).
    if D.get_bool(p, "Wtdg"):
        warnings.append("Wet Edges")
    if D.get_bool(p, "Nose"):
        warnings.append("Airbrush / Nozzle")
    if D.get_bool(p, "useBrushPose"):
        warnings.append("Brush Pose")
    dual = D.get_obj(p, "dualBrush")
    if dual is not None and D.get_bool(dual, "useDualBrush"):
        warnings.append("Dual Brush")
    return warnings


def _dedupe(presets: list[BrushPreset]) -> list[BrushPreset]:
    """Drop exactly duplicate presets (same name+uuid+Dmtr), keeping the first one."""
    seen: set[tuple] = set()
    result: list[BrushPreset] = []
    for bp in presets:
        key = (bp.name, bp.uuid, bp.diameter)
        if key in seen:
            continue
        seen.add(key)
        result.append(bp)
    return result
