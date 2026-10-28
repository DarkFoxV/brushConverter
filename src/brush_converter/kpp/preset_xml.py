"""Generate the XML for a Krita brush (paintop) preset.

Target format: Krita 5.x embedded resources (embedded_resources="2") —
the tip is embedded as base64 inside <resources>, and brush_definition
refers to it via png_brush.

The default parameter set is taken strictly from a Krita 5.x reference preset
that was converted manually by hand (199 parameters, 145 internal + 54 string),
guaranteeing that parameter names and types match Krita's actual output.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

# Every sensor has a set of parameters: Sensor / UseCurve / UseSameCurve / Value / commonCurve / curveMode
_SENSORS = [
    "Darken", "Flow", "LightnessStrength", "Mirror", "Mix", "Opacity",
    "Rate", "Ratio", "Rotation", "Scatter", "Sharpness", "Size",
    "Softness", "Spacing", "h", "s", "v",
]

_SENSOR_XML = '<!DOCTYPE params> <params id="pressure"/> '
_CURVE_ID = "0,0;1,1;"


def _sensor_param_name(s: str, suffix: str) -> str:
    # h/s/v use a lowercase first letter: hcommonCurve / scurveMode, etc.
    return f"{s}{suffix}"


def _build_default_params() -> dict[str, tuple[str, str]]:
    """Build the default parameter set: name -> (type, inner_value)."""
    p: dict[str, tuple[str, str]] = {}

    for s in _SENSORS:
        p[_sensor_param_name(s, "Sensor")] = ("string", _SENSOR_XML)
        p[_sensor_param_name(s, "UseCurve")] = ("internal", "true")
        p[_sensor_param_name(s, "UseSameCurve")] = ("internal", "true")
        p[_sensor_param_name(s, "Value")] = ("internal", "1")
        p[_sensor_param_name(s, "commonCurve")] = ("string", _CURVE_ID)
        p[_sensor_param_name(s, "curveMode")] = ("internal", "0")

    # Pressure switches (off by default, enabled on demand when mapping)
    for s in _SENSORS:
        p[f"Pressure{s}"] = ("internal", "false")
    p["PressureTexture/Strength/"] = ("internal", "false")

    # Texture option defaults (compared against Krita 5.x export samples ref_5.0.xml / ref_勾线笔.xml)
    texture_defaults = {
        "Texture/Pattern/Brightness": ("internal", "0"),
        "Texture/Pattern/Contrast": ("internal", "1"),
        "Texture/Pattern/CutoffLeft": ("internal", "0"),
        "Texture/Pattern/CutoffPolicy": ("internal", "0"),
        "Texture/Pattern/CutoffRight": ("internal", "255"),
        "Texture/Pattern/Enabled": ("internal", "false"),
        "Texture/Pattern/Invert": ("internal", "false"),
        "Texture/Pattern/MaximumOffsetX": ("internal", "2"),
        "Texture/Pattern/MaximumOffsetY": ("internal", "2"),
        "Texture/Pattern/Name": ("string", ""),
        "Texture/Pattern/NeutralPoint": ("internal", "0.5"),
        "Texture/Pattern/OffsetX": ("internal", "0"),
        "Texture/Pattern/OffsetY": ("internal", "0"),
        "Texture/Pattern/PatternFileName": ("string", ""),
        "Texture/Pattern/PatternMD5": ("string", ""),  # 5.0 wrote the raw binary here (bug); leave empty
        "Texture/Pattern/PatternMD5Sum": ("string", ""),  # hex md5, read by Krita 5.1+
        "Texture/Pattern/Scale": ("internal", "1"),
        "Texture/Pattern/TexturingMode": ("internal", "0"),
        "Texture/Pattern/UseSoftTexturing": ("internal", "false"),
        "Texture/Pattern/isRandomOffsetX": ("internal", "false"),
        "Texture/Pattern/isRandomOffsetY": ("internal", "false"),
        "Texture/Strength/Sensor": ("string", _SENSOR_XML),
        "Texture/Strength/UseCurve": ("internal", "true"),
        "Texture/Strength/UseSameCurve": ("internal", "true"),
        "Texture/Strength/Value": ("internal", "1"),
        "Texture/Strength/commonCurve": ("string", _CURVE_ID),
        "Texture/Strength/curveMode": ("internal", "0"),
    }
    p.update(texture_defaults)

    fixed = {
        "ColorSource/Type": ("string", "plain"),
        "CompositeOp": ("string", "normal"),
        "EraserMode": ("internal", "false"),
        "HorizontalMirrorEnabled": ("internal", "false"),
        "VerticalMirrorEnabled": ("internal", "false"),
        "KisPrecisionOption/AutoPrecisionEnabled": ("internal", "false"),
        "KisPrecisionOption/precisionLevel": ("internal", "5"),
        "PaintOpAction": ("internal", "2"),
        "PaintOpSettings/ignoreSpacing": ("internal", "false"),
        "PaintOpSettings/isAirbrushing": ("internal", "false"),
        "PaintOpSettings/rate": ("internal", "20"),
        "PaintOpSettings/updateSpacingBetweenDabs": ("internal", "false"),
        "Spacing/Isotropic": ("internal", "false"),
        "Scattering/AxisX": ("internal", "false"),
        "Scattering/AxisY": ("internal", "true"),
        "Sharpness/alignoutline": ("internal", "false"),
        "Sharpness/softness": ("internal", "0"),
        "lodSizeThreshold": ("internal", "100"),
        "lodUserAllowed": ("internal", "true"),
        "paintop": ("string", "paintbrush"),
        "brush_definition": ("string", ""),
        # Scatter amount defaults to 0 (the generic Value default is 1; scatter must be the
        # exception, otherwise brushes with no scatter turn into 100%)
        "ScatterValue": ("internal", "0"),
    }
    p.update(fixed)
    return p


DEFAULT_PARAMS = _build_default_params()


def _pressure_sensor(curve: str | None = None) -> str:
    """Pressure sensor XML."""
    if curve is None:
        return _SENSOR_XML
    return f'<!DOCTYPE params> <params id="pressure"> <curve>{curve}</curve> </params> '


def _drawing_angle_sensor() -> str:
    """The "rotate by stroke direction" sensor. Krita's UI displays the fuzzy angle curve
    as -180deg..+180deg, but the XML curve values use the normalized range 0..1; therefore
    the full random range must be serialized with the end point 1."""
    return (
        '<!DOCTYPE params> <params id="sensorslist"> '
        '<ChildSensor id="drawingangle" lockedAngleMode="0" fanCornersEnabled="0" '
        'fanCornersStep="30" angleOffset="0"/> '
        '<ChildSensor id="fuzzy"> <curve>0,0;1,1;</curve> </ChildSensor> '
        '<ChildSensor id="fuzzystroke"> <curve>0,0;1,1;</curve> </ChildSensor> '
        '</params> '
    )


def _fuzzy_random_sensor() -> str:
    """Pure random rotation sensor: keeps only fuzzy/fuzzystroke, no stroke direction.

    Photoshop's angleDynamics.bVTy==0 (control=off) with jitter>0 means pure random
    angle jitter with no sensor; Krita expresses this with a fuzzy random curve, and
    the random amplitude is scaled by RotationValue (=jitter/100).
    """
    return (
        '<!DOCTYPE params> <params id="sensorslist"> '
        '<ChildSensor id="fuzzy"> <curve>0,0;1,1;</curve> </ChildSensor> '
        '<ChildSensor id="fuzzystroke"> <curve>0,0;1,1;</curve> </ChildSensor> '
        '</params> '
    )


def _fuzzy_dab_sensor() -> str:
    """Fuzzy Dab (per-dab random) sensor XML — a single active sensor for the HSV options."""
    return '<!DOCTYPE params> <params id="fuzzy"/> '


def sampled_brush_definition(filename: str, md5sum: str, spacing: float,
                             angle: float, scale: float) -> str:
    """The <Brush> definition for an image tip (png_brush).

    angle is in degrees (Photoshop #Ang, may be negative); Krita's XML stores radians
    and the UI range is [0,360). Negative angles must first be normalized to [0,360)
    (otherwise Krita's angle widget clamps them to 0).
    """
    angle_rad = math.radians(angle % 360.0)
    return (
        f'<Brush type="png_brush" useAutoSpacing="0" autoSpacingCoeff="1" '
        f'filename={quoteattr(filename)} AutoAdjustMidPoint="1" angle="{angle_rad:g}" '
        f'ContrastAdjustment="0" AdjustmentVersion="2" scale="{scale:g}" '
        f'AdjustmentMidPoint="127" md5sum={quoteattr(md5sum)} brushApplication="0" '
        f'BrushVersion="2" ColorAsMask="1" BrightnessAdjustment="0" spacing="{spacing:g}"/>'
    )


def auto_brush_definition(diameter: float, spacing: float, angle: float,
                          roundness: float, hardness: float | None) -> str:
    """The <Brush> definition for a computed tip (auto_brush).

    - angle: degrees -> radians (Krita's XML stores radians; normalizeAngle is the
      [0,2pi) radian version). Negative angles are first normalized to [0,360),
      otherwise Krita's angle widget ([0,360]) clamps them to 0.
    - fade (hfade/vfade) = hardness/100: in Krita, fade is the "solid core as a
      fraction of the radius" — hardness 100% -> 1.0 (hard edge), hardness 0% -> 0.0
      (fully soft), which matches the direction of Photoshop's hardness.
    """
    ratio = roundness / 100.0
    angle_rad = math.radians(angle % 360.0)
    fade = 0.5 if hardness is None else max(0.0, min(1.0, hardness / 100.0))
    return (
        f'<Brush type="auto_brush" randomness="0" density="1" BrushVersion="2" '
        f'spacing="{spacing:g}" angle="{angle_rad:g}"> '
        f'<MaskGenerator ratio="{ratio:g}" type="circle" vfade="{fade:g}" '
        f'id="default" spikes="2" antialiasEdges="1" hfade="{fade:g}" '
        f'diameter="{diameter:g}"/> </Brush> '
    )


def _resource_xml(res_type: str, name: str, filename: str, png: bytes) -> str:
    """A single embedded resource element (embedded_resources="2", type=brushes/patterns)."""
    md5sum = hashlib.md5(png).hexdigest()
    b64 = base64.b64encode(png).decode("ascii")
    return (
        f'<resource name={quoteattr(name)} filename={quoteattr(filename)} '
        f'type={quoteattr(res_type)} md5sum={quoteattr(md5sum)}><![CDATA[{b64}]]></resource> '
    )


def _resources_xml(resources: list[tuple[str, str, str, bytes]]) -> str:
    """Generate the <resources> element: tip PNG and texture PNG are both embedded as base64."""
    return "<resources> " + "".join(
        _resource_xml(res_type, name, filename, png)
        for res_type, name, filename, png in resources
    ) + "</resources>"


@dataclass
class TextureXml:
    """Data needed by Krita's texture options (assembled by convert from TextureSettings)."""

    pattern_filename: str   # embedded resource filename (e.g. tex_66e2987f.png)
    png_bytes: bytes
    scale: float = 1.0      # 0.01..10, 1=100%
    brightness: float = 0.0
    contrast: float = 1.0
    invert: bool = False
    texturing_mode: int = 0
    use_soft_texturing: bool = False
    strength: float = 1.0   # 0..1 (PS textureDepth/100)
    strength_curve: str | None = None  # "x,y;x,y;"
    strength_pressure: bool = False


def _apply_texture(params: dict[str, tuple[str, str]], tex: TextureXml) -> None:
    """Write a TextureXml into the parameter set (the Texture/... branches)."""
    def set_internal(key: str, value: str) -> None:
        params[key] = ("internal", value)

    def set_string(key: str, value: str) -> None:
        params[key] = ("string", value)

    md5sum = hashlib.md5(tex.png_bytes).hexdigest()
    set_internal("Texture/Pattern/Enabled", "true")
    set_string("Texture/Pattern/Name", tex.pattern_filename)
    set_string("Texture/Pattern/PatternFileName", tex.pattern_filename)
    set_string("Texture/Pattern/PatternMD5Sum", md5sum)
    set_string("Texture/Pattern/PatternMD5", "")  # leave empty to avoid the Krita 5.0 binary-writing bug
    set_internal("Texture/Pattern/Scale", f"{max(0.01, min(10.0, tex.scale)):g}")
    set_internal("Texture/Pattern/Brightness", f"{tex.brightness:g}")
    set_internal("Texture/Pattern/Contrast", f"{tex.contrast:g}")
    set_internal("Texture/Pattern/Invert", "true" if tex.invert else "false")
    set_internal("Texture/Pattern/TexturingMode", str(tex.texturing_mode))
    set_internal("Texture/Pattern/UseSoftTexturing", "true" if tex.use_soft_texturing else "false")
    set_internal("Texture/Strength/Value", f"{max(0.0, min(1.0, tex.strength)):g}")
    # Krita's PressureTexture/Strength/ is the enable switch for the "strength" option
    # (isChecked, see KisKritaSensorPack::read: getBool("Pressure"+id)); it has nothing
    # to do with pressure: PS texture depth must have it on whether or not a sensor is
    # attached, otherwise the whole option is disabled.
    set_internal("PressureTexture/Strength/", "true")
    if tex.strength_pressure:
        # PS textureDepthDynamics.bVTy==2: strength follows pressure; enable the curve (Mnm is the minimum)
        set_internal("Texture/Strength/UseCurve", "true")
        if tex.strength_curve:
            set_string("Texture/Strength/commonCurve", tex.strength_curve)
    else:
        # PS bVTy==0: constant strength; only write Value (textureDepth/100), no sensor attached
        set_internal("Texture/Strength/UseCurve", "false")


def build_preset_xml(
    name: str,
    brush_definition: str,
    tip_png: bytes | None,
    tip_name: str | None = None,
    size_curve: str | None = None,
    opacity_curve: str | None = None,
    flow_curve: str | None = None,
    ratio_curve: str | None = None,
    rotation_sensor: str | None = None,   # "pressure" | "drawingangle" | None
    rotation_jitter: float = 0.0,
    scatter: bool = False,
    scatter_pressure: bool = False,       # whether scatter amount follows pressure (ScatterSensor=pressure)
    scatter_both_axes: bool = False,
    scatter_amount: float | None = None,  # PS scatter amount 0..1000% (scatterDynamics.jitter)
    color_jitter: tuple[float, float, float] | None = None,  # PS color dynamics (H, Strt, Brgh) 0..100%
    extra_params: dict[str, str] | None = None,
    texture: TextureXml | None = None,
) -> str:
    """Assemble the complete <Preset> XML. Curve parameters are "x,y;x,y;" (no trailing semicolon)."""
    params = dict(DEFAULT_PARAMS)
    params["brush_definition"] = ("string", brush_definition)

    def set_internal(key: str, value: str) -> None:
        params[key] = ("internal", value)

    def set_string(key: str, value: str) -> None:
        params[key] = ("string", value)

    if size_curve is not None:
        set_string("SizecommonCurve", size_curve)
        set_internal("PressureSize", "true")
        set_internal("SizeUseCurve", "true")
    if opacity_curve is not None:
        set_string("OpacitycommonCurve", opacity_curve)
        set_internal("PressureOpacity", "true")
    if flow_curve is not None:
        set_string("FlowcommonCurve", flow_curve)
        set_internal("FlowUseCurve", "true")
        set_internal("PressureFlow", "true")
    if ratio_curve is not None:
        set_string("RatiocommonCurve", ratio_curve)
        set_internal("PressureRatio", "true")
    if rotation_sensor == "drawingangle":
        # Photoshop angle jitter maps directly to Krita's "Rotation-Strength";
        # Krita's fuzzy/fuzzystroke curves themselves handle the ±180° random direction;
        # the curve XML uses normalized 0..1 and cannot directly store the UI's 180.
        set_string("RotationSensor", _drawing_angle_sensor())
        set_internal("PressureRotation", "true")
        set_internal("RotationValue", f"{max(0.0, min(100.0, rotation_jitter)) / 100.0:g}")
        set_internal("RotationUseCurve", "true")
        set_internal("RotationUseSameCurve", "false")
        set_internal("RotationcurveMode", "1")
    elif rotation_sensor == "pressure":
        set_string("RotationSensor", _pressure_sensor())
        set_internal("PressureRotation", "true")
    elif rotation_jitter > 0:
        # PS angleDynamics.bVTy==0 (control=off) but jitter>0: pure random angle jitter,
        # with no sensor. Krita's "Rotation-Strength" still needs to be enabled
        # (PressureRotation=true), expressing randomness through a sensor that only has
        # fuzzy/fuzzystroke; RotationValue=jitter/100.
        set_string("RotationSensor", _fuzzy_random_sensor())
        set_internal("PressureRotation", "true")
        set_internal("RotationValue", f"{max(0.0, min(100.0, rotation_jitter)) / 100.0:g}")
        set_internal("RotationUseCurve", "true")
        set_internal("RotationUseSameCurve", "false")
        set_internal("RotationcurveMode", "1")
    if scatter:
        # PressureScatter is Krita's "scatter option enabled" switch (isChecked)
        set_internal("PressureScatter", "true")
        # Only use the pressure sensor when scatter amount follows pressure; otherwise
        # turn the curve off (constant scatter)
        if scatter_pressure:
            set_string("ScatterSensor", _pressure_sensor())
            set_internal("ScatterUseCurve", "true")
        else:
            set_internal("ScatterUseCurve", "false")
        # Scatter amount conversion: PS jitter (0..1000%) -> Krita ScatterValue (0..5.0 = 500%)
        # Measured anchor: PS 145% ≈ Krita 35% (i.e. ScatterValue 0.35), coefficient ≈ 1/4
        if scatter_amount is not None:
            set_internal("ScatterValue", f"{scatter_amount / 400.0:g}")
        # PS bothAxes -> enable both Krita axes; otherwise only the Y axis (perpendicular to the stroke)
        set_internal("Scattering/AxisX", "true" if scatter_both_axes else "false")
        set_internal("Scattering/AxisY", "true")
    if color_jitter is not None:
        # PS hue/sat/brightness jitter -> Krita's HSV options (h/s/v), verified against
        # KisKritaSensorPack/KisHSVOption: Pressure{X} is the option's isChecked switch,
        # the "fuzzy" (per-dab) sensor supplies the symmetric random draw, and the
        # transfer curve maps its 0..1 output to [0.5-L/2, 0.5+L/2] so the deviation
        # applied by Krita is exactly ±L (hue: ±L*180°, saturation/value: ±L of full range).
        # Value stays 1: Krita's strength multiplies saturation/value twice (2*S²*C-S),
        # which would bias the deviation negative for any S<1.
        for opt, pct in zip(("h", "s", "v"), color_jitter):
            limit = max(0.0, min(100.0, pct)) / 100.0
            if limit <= 0.0:
                continue
            lo = 0.5 - limit / 2.0
            hi = 0.5 + limit / 2.0
            set_internal(f"Pressure{opt}", "true")
            set_string(f"{opt}Sensor", _fuzzy_dab_sensor())
            set_internal(f"{opt}UseCurve", "true")
            set_internal(f"{opt}UseSameCurve", "true")
            set_internal(f"{opt}Value", "1")
            set_string(f"{opt}commonCurve", f"0,{lo:g};1,{hi:g};")

    if extra_params:
        for k, v in extra_params.items():
            t = params.get(k, ("internal", ""))[0]
            params[k] = (t, v)

    parts: list[str] = []
    resources: list[tuple[str, str, str, bytes]] = []
    if tip_png is not None:
        res_name = tip_name or _safe_name(name)
        resources.append(("brushes", res_name, res_name + ".png", tip_png))
        parts.append(
            '<Preset paintopid="paintbrush" name=' + quoteattr(name)
            + ' embedded_resources="2"> '
        )
    else:
        parts.append('<Preset paintopid="paintbrush" name=' + quoteattr(name) + '>')
    if texture is not None:
        resources.append(("patterns", texture.pattern_filename,
                          texture.pattern_filename, texture.png_bytes))
        _apply_texture(params, texture)
    if resources:
        parts.append(_resources_xml(resources))

    for key, (typ, value) in params.items():
        if typ == "string":
            parts.append(f' <param name={quoteattr(key)} type="string"><![CDATA[{value}]]></param>')
        else:
            parts.append(f' <param name={quoteattr(key)} type="internal">{value}</param>')
    parts.append(" </Preset>")
    return "".join(parts)


def _safe_name(name: str) -> str:
    """Sanitize a brush name into a safe resource name (word characters only)."""
    cleaned = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_")
    return cleaned or "brush"
