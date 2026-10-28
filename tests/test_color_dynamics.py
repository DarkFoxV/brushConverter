"""Color Dynamics conversion tests (no sample needed, pure stdlib)."""

from __future__ import annotations

import colorsys
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brush_converter.color_dynamics import (  # noqa: E402
    CURVA_LINEAR,
    aplicar_dinamica_cor,
    curva_krita,
    desvios_aleatorios,
    limites,
)


def test_limites():
    assert limites(100, 100, 100) == (180.0, 1.0, 1.0)
    assert limites(0, 50, 25) == (0.0, 0.5, 0.25)
    assert limites(40, 30, 20) == (72.0, 0.3, 0.2)


def test_desvios_simetricos_dentro_do_limite():
    random.seed(7)
    for _ in range(500):
        dm, ds, db = desvios_aleatorios(40, 30, 20)
        assert -72.0 <= dm <= 72.0
        assert -0.3 <= ds <= 0.3
        assert -0.2 <= db <= 0.2


def test_desvios_com_jitter_zero_sao_nulos():
    assert desvios_aleatorios(0, 0, 0) == (0.0, 0.0, 0.0)


def test_aplicar_desvio_forcado(monkeypatch):
    # Forced draw: hue +30°, saturation -0.5, brightness +0.5
    draws = iter([30.0, -0.5, 0.5])
    monkeypatch.setattr(random, "uniform", lambda a, b: next(draws))

    rgb = colorsys.hsv_to_rgb(350 / 360, 0.6, 0.5)   # hue 350°, s=0.6, v=0.5
    r, g, b = aplicar_dinamica_cor(rgb, 100, 100, 100)

    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    assert abs(h * 360 - 20.0) < 1e-6      # (350 + 30) % 360 = 20
    assert abs(s - 0.1) < 1e-6             # 0.6 - 0.5, clamped stays 0.1
    assert abs(v - 1.0) < 1e-6             # 0.5 + 0.5, clamped to 1.0


def test_aplicar_clampa_saturacao_e_brilho(monkeypatch):
    draws = iter([0.0, 1.0, 1.0])          # hue 0, sat +1, brilho +1
    monkeypatch.setattr(random, "uniform", lambda a, b: next(draws))
    r, g, b = aplicar_dinamica_cor((1.0, 0.0, 0.0), 0, 100, 100)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    assert s == 1.0
    assert v == 1.0


def test_jitter_zero_nao_muda_a_cor():
    cor = (0.25, 0.5, 0.75)
    assert aplicar_dinamica_cor(cor, 0, 0, 0) == cor


def test_curva_krita():
    curvas = curva_krita(100, 50, 0)
    assert curvas == {
        "matiz": (CURVA_LINEAR, 180.0),
        "saturacao": (CURVA_LINEAR, 0.5),
        "brilho": (CURVA_LINEAR, 0.0),
    }
    assert CURVA_LINEAR == "0,0;1,1;"
