"""Regression tests for Stage 3 parameter mapping.

Key values calibrated against the user's manually converted Krita reference preset (liner pen).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brush_converter.abr import AbrFile  # noqa: E402
from brush_converter.mapping import map_presets  # noqa: E402

# Test sample is commercial brush material (42MB), not kept in version control. The whole
# test is skipped when the sample is missing; place the .abr in tests/ to run full assertions.
ABR = Path(__file__).parent / "海怪笔刷-详情展示的勾线笔套装组18支.abr"

pytestmark = pytest.mark.skipif(
    not ABR.exists(),
    reason="Missing test sample .abr (provide your own in tests/)",
)


def _presets():
    abr = AbrFile.parse(ABR)
    return map_presets(abr)


def test_preset_count():
    # Source file has 20 presets, minus 1 exact-duplicate "Taobao store" banner -> 19
    assert len(_presets()) == 19


def test_dedup_banner():
    names = [p.name for p in _presets()]
    assert names.count("淘宝店：大怪兽素材噗收集整理") == 1


def test_scatter_mapping():
    presets = _presets()
    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    # Liner pen has useScatter=True, scatter amount follows pressure (bVTy=2)
    assert line.scatter is True
    assert line.scatter_pressure is True
    assert line.scatter_both_axes is False

    # Bubble has useScatter=True but bVTy=0 (scatter does not follow pressure), still enabled
    bubble = next(p for p in presets if "气泡" in p.name)
    assert bubble.scatter is True
    assert bubble.scatter_pressure is False
    assert bubble.scatter_both_axes is True


def test_scatter_amount():
    presets = _presets()
    # Bubble: scatterDynamics.jitter=145% (top-level Spcn is spacing, not scatter amount)
    bubble = next(p for p in presets if "气泡" in p.name)
    assert bubble.scatter_amount == 145.0
    # Butterfly: jitter=85%
    butterfly = next(p for p in presets if "蝴蝶" in p.name)
    assert butterfly.scatter_amount == 85.0
    # Liner pen: jitter=0 (scatter enabled but amount is 0)
    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    assert line.scatter_amount == 0.0


def test_line_pen_scale():
    # Monster liner pen [for tablet] (index 2) shares tip 87465e27, Dmtr=26
    presets = _presets()
    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    assert line.diameter == 26.0
    # Tip image is 1895x1901, square canvas baseline takes the larger side -> scale = 26/1901
    assert abs(line.scale - 26.0 / 1901.0) < 1e-9


def test_line_pen_dynamics():
    presets = _presets()
    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    # Flow min 17%, opacity min 80%, aspect ratio min 30%
    assert line.flow_curve == "0,0.17;1,1;"
    assert line.opacity_curve == "0,0.8;1,1;"
    assert line.ratio_curve == "0,0.3;1,1;"
    # Rotation follows stroke direction, scatter controlled by pressure
    assert line.rotation_sensor == "drawingangle"
    assert line.rotation_jitter == 6.0
    assert line.scatter is True


def test_computed_brush():
    presets = _presets()
    comp = next(p for p in presets if "圆头虚" in p.name)
    assert comp.is_computed is True
    assert comp.tip_gray is None
    assert comp.diameter == 25.0
    assert comp.hardness == 84.0


def test_auto_brush_angle_radians():
    # Angle: Photoshop Angl is degrees, Krita XML stores radians; negative angle normalized to [0,360) then converted to radians
    from brush_converter.kpp.preset_xml import auto_brush_definition
    import math
    xml = auto_brush_definition(25.0, 0.05, -33.0, 100.0, 84.0)
    # -33° → 327° → radians
    assert f'angle="{math.radians(-33.0 % 360.0):g}"' in xml


def test_auto_brush_hardness_fade():
    # Hardness 84% → fade 0.84 (fade = solid area fraction, same direction as hardness, not (100-h)/100)
    from brush_converter.kpp.preset_xml import auto_brush_definition
    xml = auto_brush_definition(25.0, 0.05, 0.0, 100.0, 84.0)
    assert 'hfade="0.84"' in xml
    assert 'vfade="0.84"' in xml
    # Edge cases: hardness 100% → 1.0, hardness 0% → 0.0
    assert 'hfade="1"' in auto_brush_definition(25.0, 0.05, 0.0, 100.0, 100.0)
    assert 'hfade="0"' in auto_brush_definition(25.0, 0.05, 0.0, 100.0, 0.0)


def test_sampled_brush_angle_radians():
    # Sampled brush angle also needs degrees→radians + normalize
    from brush_converter.kpp.preset_xml import sampled_brush_definition
    import math
    xml = sampled_brush_definition("x.png", "abc123", 0.25, -33.0, 1.0)
    assert f'angle="{math.radians(-33.0 % 360.0):g}"' in xml


def test_rotation_jitter_uses_effect_strength_and_180_degree_curves():
    from brush_converter.kpp.preset_xml import build_preset_xml
    xml = build_preset_xml("rotation", "", None, rotation_sensor="drawingangle", rotation_jitter=12.0)
    assert 'RotationValue" type="internal">0.12' in xml
    assert 'RotationUseCurve" type="internal">true' in xml
    # Krita UI shows ±180°, but the XML curve coordinates are normalized 0..1.
    assert '<ChildSensor id="fuzzy"> <curve>0,0;1,1;</curve>' in xml
    assert '<ChildSensor id="fuzzystroke"> <curve>0,0;1,1;</curve>' in xml


def test_sampled_tip_is_padded_to_square_for_krita():
    import numpy as np
    from brush_converter.convert import _square_tip
    tip = np.full((3, 5), 7, dtype=np.uint8)
    padded = _square_tip(tip)
    assert padded.shape == (5, 5)
    assert np.array_equal(padded[1:4, :], tip)
    assert np.all(padded[0] == 255)
    assert np.all(padded[4] == 255)


def test_generated_sampled_brush_resource_is_square():
    import base64
    import re
    from io import BytesIO
    from PIL import Image
    from brush_converter.convert import _render_preset
    presets = _presets()
    pencil = next(p for p in presets if "大怪兽-软铅" in p.name)
    _, xml, _ = _render_preset(pencil, 0)
    encoded = re.search(r'type="brushes"[^>]*><!\[CDATA\[(.*?)\]\]>', xml, re.S).group(1)
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        assert image.width == image.height



def test_texture_mapping():
    presets = _presets()
    textured = [p for p in presets if p.texture is not None]
    # Source file has 9 brushes with texture enabled (including 2 liner pens with a 1x1 neutral texture)
    assert len(textured) == 9

    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    t = line.texture
    assert t is not None
    assert t.uuid == "438c2948-d232-11e5-b988-9ff33e1af9cd"
    assert t.name == "R. Melentyev's Art Texture"
    assert t.scale == 50.0
    assert t.depth == 55.0
    assert t.pressure is True
    assert t.invert is False
    assert t.blend_mode == "linearHeight"
    assert t.image is not None and t.image.shape == (1, 1, 3)

    pen = next(p for p in presets if "针管笔" in p.name)
    t2 = pen.texture
    assert t2 is not None
    assert t2.uuid == "69d92381-cf86-a54b-9d04-7f0fc2d9345b"
    assert t2.scale == 73.0
    assert t2.depth == 5.0
    assert t2.invert is True
    assert t2.brightness == -21
    assert t2.contrast == -50
    assert t2.image is not None and t2.image.shape == (1920, 1920, 3)


def test_new_texture_sample_modes():
    sample = Path(__file__).parent / "测试用.abr"
    if not sample.exists():
        pytest.skip("Missing 测试用.abr sample")
    presets = map_presets(AbrFile.parse(sample))
    assert len(presets) == 6
    assert {p.texture.blend_mode for p in presets if p.texture} == {"Hght", "Sbtr", "hardMix"}
    assert all(p.texture is not None for p in presets)
    hard_mix = next(p for p in presets if p.texture and p.texture.blend_mode == "hardMix")
    assert hard_mix.texture is not None
    assert hard_mix.texture.blend_mode == "hardMix"
    _, hard_xml, _ = __import__("brush_converter.convert", fromlist=["_render_preset"])._render_preset(hard_mix, 0)
    assert "Texture/Pattern/TexturingMode\" type=\"internal\">10" in hard_xml

    height = next(p for p in presets if p.texture and p.texture.blend_mode == "Hght")
    _, height_xml, _ = __import__("brush_converter.convert", fromlist=["_render_preset"])._render_preset(height, 0)
    assert "Texture/Pattern/TexturingMode\" type=\"internal\">14" in height_xml


def test_texture_warnings_removed():
    # Texture core is mapped: no more "Texture" warnings; only other unmapped items remain
    presets = _presets()
    textured = [p for p in presets if p.texture is not None]
    assert textured
    for p in textured:
        assert not any("Texture" in w for w in p.warnings)


def test_texture_xml_end_to_end():
    # End-to-end conversion pipeline: liner pen XML should contain patterns resource and texture params
    from brush_converter.convert import _render_preset
    presets = _presets()
    line = next(p for p in presets if "大怪兽-勾线笔" in p.name)
    _, xml, _ = _render_preset(line, 0)
    assert 'type="patterns"' in xml
    assert "tex_438c2948.png" in xml
    assert "Texture/Pattern/Enabled\" type=\"internal\">true" in xml
    assert "Texture/Pattern/TexturingMode\" type=\"internal\">15" in xml
    assert "Texture/Pattern/Brightness\" type=\"internal\">0" in xml
    assert "Texture/Pattern/Contrast\" type=\"internal\">1" in xml
    assert "Texture/Strength/Value\" type=\"internal\">0.55" in xml
    assert "PressureTexture/Strength/\" type=\"internal\">true" in xml

