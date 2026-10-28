"""Color Dynamics → Krita HSV option (h/s/v) XML tests (no sample needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brush_converter.kpp.preset_xml import build_preset_xml  # noqa: E402


def _xml(**kwargs) -> str:
    return build_preset_xml(
        name="color-dyn",
        brush_definition='<Brush type="auto_brush" spacing="0.1"/>',
        tip_png=None,
        **kwargs,
    )


def test_color_jitter_enables_hsv_options():
    xml = _xml(color_jitter=(50, 100, 30))

    # Pressure{X} is Krita's isChecked switch for the option (KisKritaSensorPack::read)
    assert 'name="Pressureh" type="internal">true' in xml
    assert 'name="Pressures" type="internal">true' in xml
    assert 'name="Pressurev" type="internal">true' in xml

    # Single active sensor: fuzzy (Fuzzy Dab, per-dab random)
    assert 'name="hSensor" type="string"><![CDATA[<!DOCTYPE params> <params id="fuzzy"/> ]]>' in xml
    assert 'name="sSensor" type="string"><![CDATA[<!DOCTYPE params> <params id="fuzzy"/> ]]>' in xml
    assert 'name="vSensor" type="string"><![CDATA[<!DOCTYPE params> <params id="fuzzy"/> ]]>' in xml

    for opt in "hsv":
        assert f'name="{opt}UseCurve" type="internal">true' in xml
        assert f'name="{opt}UseSameCurve" type="internal">true' in xml
        assert f'name="{opt}Value" type="internal">1' in xml

    # Transfer curve maps the random 0..1 draw to [0.5-L/2, 0.5+L/2] → deviation ±L
    # 50% → ±0.5; 100% → ±1 (identity curve, full range)
    assert 'name="hcommonCurve" type="string"><![CDATA[0,0.25;1,0.75;]]>' in xml
    assert 'name="scommonCurve" type="string"><![CDATA[0,0;1,1;]]>' in xml
    # 30% → 0.5∓0.15 (float formatting via :g)
    assert 'name="vcommonCurve" type="string"><![CDATA[0,0.35;1,0.65;]]>' in xml


def test_zero_jitter_keeps_options_off():
    xml = _xml(color_jitter=(0, 0, 0))
    for opt in "hsv":
        assert f'name="Pressure{opt}" type="internal">false' in xml
        assert f'name="{opt}Sensor" type="string"><![CDATA[<!DOCTYPE params> <params id="pressure"/> ]]>' in xml


def test_no_color_dynamics_leaves_defaults():
    xml = _xml()
    for opt in "hsv":
        assert f'name="Pressure{opt}" type="internal">false' in xml
        assert 'name="hcommonCurve" type="string"><![CDATA[0,0;1,1;]]>' in xml


def test_jitter_is_clamped_to_100():
    xml = _xml(color_jitter=(150, -20, 30))
    # 150% → clamped to 100% → identity curve
    assert 'name="hcommonCurve" type="string"><![CDATA[0,0;1,1;]]>' in xml
    # -20% → clamped to 0 → option stays off
    assert 'name="Pressures" type="internal">false' in xml
    assert 'name="vcommonCurve" type="string"><![CDATA[0,0.35;1,0.65;]]>' in xml
