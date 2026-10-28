"""Photoshop Color Dynamics (jitter) → Krita transfer-curve conversion.

PS jitter is a symmetric percentage deviation around the base color. Krita models
the same randomness with a transfer curve driven by a fuzzy random sensor, following
the pattern already calibrated for rotation in preset_xml.py: linear curve "0,0;1,1;"
through the full range, symmetric deviation handled by Krita around the base color,
amplitude carried by the Value parameter.

Formulas (per the conversion spec):
  - Hue:        limit (deg) = variacao_matiz / 100 * 180   (100% = half turn)
  - Saturation: limit       = variacao_saturacao / 100     (normalized 0..1)
  - Brightness: limit       = variacao_brilho / 100        (normalized 0..1)
Each deviation is drawn uniform in [-limit, +limit] and applied to the base color:
hue rotates (mod 360), saturation/brightness are clamped to 0..1.
"""

from __future__ import annotations

import colorsys
import random

# Linear transfer curve, normalized 0..1 (Krita XML curve format)
CURVA_LINEAR = "0,0;1,1;"


def limites(variacao_matiz: float, variacao_saturacao: float,
            variacao_brilho: float) -> tuple[float, float, float]:
    """Max symmetric deviation: hue in degrees, saturation/brightness normalized 0..1."""
    return (
        variacao_matiz / 100.0 * 180.0,
        variacao_saturacao / 100.0,
        variacao_brilho / 100.0,
    )


def desvios_aleatorios(variacao_matiz: float, variacao_saturacao: float,
                        variacao_brilho: float) -> tuple[float, float, float]:
    """Symmetric random deviation for hue (deg), saturation and brightness (0..1)."""
    limite_matiz, limite_sat, limite_brilho = limites(
        variacao_matiz, variacao_saturacao, variacao_brilho)
    return (
        random.uniform(-limite_matiz, limite_matiz),
        random.uniform(-limite_sat, limite_sat),
        random.uniform(-limite_brilho, limite_brilho),
    )


def aplicar_dinamica_cor(rgb: tuple[float, float, float], variacao_matiz: float,
                         variacao_saturacao: float,
                         variacao_brilho: float) -> tuple[float, float, float]:
    """Apply one symmetric jitter draw to a base color (RGB floats 0..1) → new RGB.

    Hue: new = (hue + desvio) % 360 (stays in the color circle).
    Saturation/brightness: new = clamp(value + desvio, 0.0, 1.0).
    """
    desvio_matiz, desvio_sat, desvio_brilho = desvios_aleatorios(
        variacao_matiz, variacao_saturacao, variacao_brilho)

    h, s, v = colorsys.rgb_to_hsv(*rgb)
    h = (h + desvio_matiz / 360.0) % 1.0
    s = min(1.0, max(0.0, s + desvio_sat))
    v = min(1.0, max(0.0, v + desvio_brilho))
    return colorsys.hsv_to_rgb(h, s, v)


def curva_krita(variacao_matiz: float, variacao_saturacao: float,
                variacao_brilho: float) -> dict[str, tuple[str, float]]:
    """Krita transfer-curve settings per channel: (curve XML, amplitude).

    Curve coordinates are normalized 0..1; the amplitude (Value) is the limit:
    hue in degrees (-180..+180), saturation/brightness normalized (-1..+1).
    """
    limite_matiz, limite_sat, limite_brilho = limites(
        variacao_matiz, variacao_saturacao, variacao_brilho)
    return {
        "matiz": (CURVA_LINEAR, limite_matiz),
        "saturacao": (CURVA_LINEAR, limite_sat),
        "brilho": (CURVA_LINEAR, limite_brilho),
    }
