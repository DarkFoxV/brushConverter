"""Krita texture parameters and embedded resource generation tests (no real sample needed)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brush_converter.convert import _texture_xml  # noqa: E402
from brush_converter.kpp.preset_xml import (  # noqa: E402
    DEFAULT_PARAMS,
    TextureXml,
    build_preset_xml,
)
from brush_converter.mapping import BrushPreset, TextureSettings  # noqa: E402


def _xml(texture: TextureXml | None = None) -> str:
    return build_preset_xml(
        name="测试纹理",
        brush_definition='<Brush type="auto_brush" spacing="0.1"/>',
        tip_png=None,
        texture=texture,
    )


def test_texture_params_written():
    tex = TextureXml(
        pattern_filename="tex_abc12345.png",
        png_bytes=b"fake-png-bytes",
        scale=0.5,
        brightness=-0.18,
        contrast=0.66,
        invert=True,
        texturing_mode=15,
        strength=0.55,
        strength_curve="0,0;1,1;",
        strength_pressure=True,
    )
    xml = _xml(tex)
    md5 = hashlib.md5(b"fake-png-bytes").hexdigest()
    assert 'type="patterns"' in xml
    assert "tex_abc12345.png" in xml
    assert f"PatternMD5Sum\" type=\"string\"><![CDATA[{md5}]]>" in xml
    assert "Texture/Pattern/Enabled\" type=\"internal\">true" in xml
    assert "Texture/Pattern/Scale\" type=\"internal\">0.5" in xml
    assert "Texture/Pattern/Brightness\" type=\"internal\">-0.18" in xml
    assert "Texture/Pattern/Contrast\" type=\"internal\">0.66" in xml
    assert "Texture/Pattern/Invert\" type=\"internal\">true" in xml
    assert "Texture/Pattern/TexturingMode\" type=\"internal\">15" in xml
    assert "Texture/Strength/Value\" type=\"internal\">0.55" in xml
    assert "Texture/Strength/UseCurve\" type=\"internal\">true" in xml
    assert "Texture/Strength/commonCurve\" type=\"string\"><![CDATA[0,0;1,1;]]>" in xml
    assert "PressureTexture/Strength/\" type=\"internal\">true" in xml


def test_texture_strength_constant_without_sensor():
    # PS textureDepthDynamics.bVTy==0 (depth has no sensor): Krita "effect strength" should
    # stay enabled (PressureTexture/Strength/=true) but with curve off (UseCurve=false),
    # strength provided constantly by Value=textureDepth/100, instead of disabling the item.
    tex = TextureXml(
        pattern_filename="tex_abc12345.png",
        png_bytes=b"fake-png-bytes",
        strength=0.55,
        strength_pressure=False,
    )
    xml = _xml(tex)
    assert "Texture/Strength/Value\" type=\"internal\">0.55" in xml
    assert "Texture/Strength/UseCurve\" type=\"internal\">false" in xml
    assert "PressureTexture/Strength/\" type=\"internal\">true" in xml
    assert "Texture/Strength/commonCurve\" type=\"string\"><![CDATA[0,0;1,1;]]>" in xml


def test_rotation_random_without_sensor_keeps_option_enabled():
    # PS angleDynamics.bVTy==0 (no sensor) but jitter>0: pure random angle jitter.
    # Krita "Rotation" option should be enabled (PressureRotation=true), using a fuzzy-only
    # sensor to express randomness (not following stroke direction, no drawingangle),
    # RotationValue=jitter/100.
    xml = build_preset_xml("random-rot", "", None, rotation_sensor=None, rotation_jitter=20.0)
    assert 'PressureRotation" type="internal">true' in xml
    assert 'RotationValue" type="internal">0.2' in xml
    assert 'RotationUseCurve" type="internal">true' in xml
    assert '<ChildSensor id="fuzzy"> <curve>0,0;1,1;</curve>' in xml
    assert '<ChildSensor id="fuzzystroke"> <curve>0,0;1,1;</curve>' in xml
    assert '<ChildSensor id="drawingangle"' not in xml


def test_rotation_off_when_no_jitter_and_no_sensor():
    xml = build_preset_xml("no-rot", "", None)
    assert 'PressureRotation" type="internal">false' in xml


def test_texture_disabled_by_default():
    xml = _xml(None)
    assert 'type="patterns"' not in xml
    assert "Texture/Pattern/Enabled\" type=\"internal\">false" in xml
    assert DEFAULT_PARAMS["Texture/Pattern/Enabled"] == ("internal", "false")
    assert DEFAULT_PARAMS["Texture/Pattern/TexturingMode"] == ("internal", "0")


def test_convert_texture_xml_formulas():
    # Brightness/contrast/scale conversion + clamping; unknown blend mode falls back to Multiply(0)
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    ts = TextureSettings(
        name="x",
        uuid="12345678-0000-0000-0000-000000000000",
        scale=2000.0,   # 2000% → clamp to 10.0
        invert=True,
        brightness=-100,
        contrast=100,
        depth=55.0,
        depth_min=0.0,
        pressure=True,
        blend_mode="Ovld",  # not in mapping table → 0
        image=img,
    )
    tex = _texture_xml(BrushPreset(name="x", texture=ts))
    assert tex is not None
    assert tex.scale == 10.0
    assert tex.brightness == 0.5
    assert tex.contrast == 2.0
    assert tex.texturing_mode == 0
    assert abs(tex.strength - 0.55) < 1e-9
    assert tex.strength_pressure is True
    assert tex.strength_curve == "0,0;1,1;"


def test_photoshop_brightness_contrast_use_krita_native_ranges():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    ts = TextureSettings(name="x", uuid="x", brightness=-27, contrast=-17, image=img)
    tex = _texture_xml(BrushPreset(name="x", texture=ts))
    assert tex is not None
    # Krita KisTextureMaskInfo: brightness is subtracted in [−1,1],
    # contrast is a multiplier around 0.5 with neutral value 1.
    assert tex.brightness == 0.21
    assert abs(tex.contrast - 0.83) < 1e-9


def test_photoshop_contrast_uses_modern_adjustment_factor():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    from brush_converter.mapping import TextureSettings
    for value, expected in [(-50, 0.5), (25, 4/3), (50, 2.0), (75, 2.0)]:
        ts = TextureSettings(name="x", uuid="x", contrast=value, image=img)
        tex = _texture_xml(BrushPreset(name="x", texture=ts))
        assert tex is not None
        assert abs(tex.contrast - round(expected, 2)) < 1e-9
    ts = TextureSettings(name="x", uuid="x", contrast=100, image=img)
    tex = _texture_xml(BrushPreset(name="x", texture=ts))
    assert tex is not None and tex.contrast == 2.0


def test_linear_height_brightness_uses_common_mapping():
    # Linear Height (Photoshop) no longer uses a 0.30 baseline: all modes use the common mapping
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    from brush_converter.mapping import TextureSettings
    tex = _texture_xml(BrushPreset(name="x", texture=TextureSettings(name="x", uuid="x", brightness=30, image=img, blend_mode="linearHeight")))
    assert tex is not None
    assert abs(tex.brightness - (0.10 - 30 / 250)) < 1e-9


def test_linear_height_contrast_uses_common_mapping():
    # Linear Height (Photoshop) no longer inverts contrast: all modes use the common PS centered factor
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    from brush_converter.mapping import TextureSettings
    for value, expected in [(-50, 0.5), (-25, 0.75), (25, 4/3), (50, 2.0), (75, 2.0), (100, 2.0)]:
        ts = TextureSettings(name="x", uuid="x", contrast=value, image=img, blend_mode="linearHeight")
        tex = _texture_xml(BrushPreset(name="x", texture=ts))
        assert tex is not None
        assert abs(tex.contrast - round(expected, 2)) < 1e-9


def test_photoshop_texture_modes_use_krita_photoshop_variants():
    from brush_converter.mapping import _TEXTURING_MODE
    assert _TEXTURING_MODE["linearHeight"] == 15
    assert _TEXTURING_MODE["height"] == 14
    assert _TEXTURING_MODE["Hght"] == 14
    assert _TEXTURING_MODE["HdMx"] == 10
    assert _TEXTURING_MODE["HdMxS"] == 11
    assert _TEXTURING_MODE["hardMix"] == 10
    assert _TEXTURING_MODE["Mul "] == 0
    assert _TEXTURING_MODE["Sbtr"] == 1


def test_convert_texture_filename_from_uuid():
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    ts = TextureSettings(name="x", uuid="66e2987f-d47b-fa49-9e36-3ffa8b78533a",
                         image=img)
    tex = _texture_xml(BrushPreset(name="x", texture=ts))
    assert tex is not None
    assert tex.pattern_filename == "tex_66e2987f.png"
