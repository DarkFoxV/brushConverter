# Research into Photoshop's Underlying Texture Brightness/Contrast Implementation

## Summary of Conclusions

- Adobe officially documents the control ranges and behavior, but has not published the exact source code for Photoshop's texture engine or its Brightness/Contrast calculations.
- Photoshop's brightness range is confirmed as -150..150 and contrast as -50..100. These match the controls in the newer Brightness/Contrast adjustment feature, but do not prove that the texture engine reuses the adjustment-layer algorithm.
- Krita's texture implementation is confirmed to use a separate algorithm: subtract brightness first, then multiply contrast around 0.5. This is not Photoshop's adjustment-layer formula.
- Adobe documentation says “Use Legacy” simply shifts pixel values; the newer behavior is not a simple shift and generally protects or redistributes highlights and shadows. Therefore, the newer Photoshop adjustment-layer formula cannot currently be treated as the ABR texture formula.

## Confirmed External References

- Adobe's official Brightness/Contrast documentation: <https://helpx.adobe.com/photoshop/using/apply-brightness-contrast-adjustment.html>. Confirms ranges -150..150 / -50..100 and distinguishes Use Legacy from the newer behavior.
- Adobe documentation on creating textured brushes: <https://helpx.adobe.com/photoshop/using/creating-textured-brushes.html>. Confirms that texture settings support Brightness/Contrast adjustments, but does not publish the calculation formula.
- Krita texture documentation: <https://docs.krita.org/zh_CN/reference_manual/brushes/brush_settings/texture.html>. Explains brightness/contrast as a separate filter and notes that different texture modes may require different values.
- Krita source `KisTextureMaskInfo::recalculateMask()`: brightness is subtraction, and contrast is multiplication around 0.5.

## Hypothesis Based on Photoshop's New Adjustment Layer

A common candidate model is a linear transform on normalized pixel value `x`:

```text
x1 = x + B                 # or a constrained brightness transform using B/150
x2 = (x1 - 0.5) * C + 0.5
clip(x2, 0, 1)
```

However, Photoshop's newer Brightness/Contrast implementation may involve:

- Changing midtones rather than simply shifting all values;
- Protecting or remapping highlights and shadows;
- A nonlinear curve or lookup table for the contrast slider;
- Differences between 8-bit / 16-bit, color spaces, and gamma / linear space;
- Adjusting texture brightness internally before compositing the texture with brush-tip alpha.

Thus, identical control ranges alone do not establish the exact formula.

## Empirical Mapping in the Current Project

The current implementation uses the user-provided control ranges and Krita's parameter ranges:

- Brightness in ordinary modes: `round(0.10 - PS_brightness/250, 2)`; Linear Height Photoshop: `round(0.30 - PS_brightness/250, 2)`; clamp to Krita's [-1,1].
- Contrast in ordinary modes uses a Photoshop factor; Linear Height Photoshop uses its reciprocal. Final value is clamped to Krita's [0,2] and serialized to two decimal places.
- At runtime, Krita then applies `maskValue -= brightness` and `((maskValue - 0.5) * contrast) + 0.5`.

This keeps the ranges, neutral point, and Krita's internal value semantics consistent, but remains an empirical mapping, not proof of Photoshop's formula.

## Evidence from a Manually Edited KPP Sample

The file `tests/大怪兽-软铅【用数位板】_复制.kpp` was observed to contain:

- `TexturingMode=15` (Linear Height Photoshop);
- `Brightness=-0.06`;
- `Contrast=1.14`.

The corresponding original ABR soft-pencil settings were approximately brightness=-27, contrast=-17. Because this KPP was manually adjusted by eye, it only indicates a plausible magnitude and direction; it cannot uniquely determine a formula. If used as a two-point calibration:

- The brightness ratio is about `0.06/27 ≈ 0.0022`, rather than the simple `1/150 ≈ 0.0067`;
- Contrast=-17 corresponds to 1.14, opposite the direction of the current mapping for negative values, which yields 0.66;
- This suggests that the manually edited KPP was likely a visual approximation, or that Photoshop and Krita interpret contrast in opposite directions. It cannot be directly fitted as an exact formula.

## Recommended Exact Validation Procedure

To reverse-engineer Photoshop's texture formula, the most reliable approach is to create controlled samples rather than use adjustment layers:

1. In Photoshop, use the same grayscale texture containing values 0/64/128/192/255.
2. Keep the brush tip fixed, depth at 100%, dynamics off, inversion off, and test Linear Height, Height, Subtract, and Multiply modes separately.
3. Change only Brightness and record the output texture or stroke alpha at -150, -100, -50, 0, 50, 100, and 150.
4. Keep Brightness=0, vary only Contrast, and record outputs at -50, 0, 25, 50, 75, and 100.
5. Fit a curve to the output grayscale values: first determine whether the transform is linear, then check for gamma, S-curves, shadow/highlight protection, or mode-specific branches.
6. Compare against the newer Brightness/Contrast adjustment layer using identical settings. Only identical outputs would confirm the hypothesis.

The project currently lacks the ability to batch-export these intermediate results from Photoshop. At this stage, only the control ranges, Krita formula, and empirical KPP values can be confirmed; the exact underlying Photoshop formula has **not** been established.
