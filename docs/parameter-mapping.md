# ABR → Krita Complete Parameter Mapping Checklist

> Engine: pixel engine (`paintbrush`) only at this stage. Source data comes from `海怪笔刷…18支.abr` (v6.2, 20 presets).
> ✅ = implemented, ⛔ = not mapped (reason at right), ❓ = awaiting confirmation.

## 1. Brush Tip and Basic Properties

| ABR key | Meaning | → Krita | Mapping formula | Status |
|--------|------|---------|----------|------|
| `samp` bitmap + `sampledData` UUID | Sampled brush tip | Embedded tip in `png_brush` | Grayscale PNG, white = ink (base64 embedded) | ✅ |
| `Brsh.Dmtr` | Main diameter in px | `scale` | `scale = Dmtr / max(tip width, tip height)`; pad the embedded sampled-tip PNG to a square | ✅ (Krita displayed-size fix) |
| `Brsh.Spcn` | Spacing % | `spacing` | `spacing = Spcn / 100` | ✅ |
| `Brsh.Angl` | Angle (degrees) | `angle` | `math.radians(Angl % 360)` (degrees → radians; normalize negative angles to [0, 360) first) | ✅ |
| `Brsh.Rndn` | Roundness % | (not mapped for sampled brushes; see note ①) | — | ⛔ |
| `Brsh.Hrdn` | Hardness % | (not mapped for sampled brushes; see note ①) | — | ⛔ |
| `Nm ` | Brush name | Preset name | Direct | ✅ |

> Note ①: Roundness and hardness are meaningful only for procedural brushes; for sampled brushes, roundness is already baked into the tip bitmap.

## 2. Procedural Brushes (no bitmap → `auto_brush`)

| ABR key | → Krita | Mapping formula | Status |
|--------|---------|----------|------|
| `Dmtr` | `MaskGenerator.diameter` | Direct | ✅ |
| `Hrdn` | `hfade` / `vfade` | `Hrdn / 100` (fade = solid-area proportion, same direction as hardness) | ✅ |
| `Rndn` | `ratio` | `Rndn / 100` | ✅ |
| `Angl` | `angle` | `math.radians(Angl % 360)` (degrees → radians; normalize negative angles) | ✅ |
| `Spcn` | `spacing` | `Spcn / 100` | ✅ |

> Note ①: Roundness and hardness apply only to procedural brushes. Hardness maps as `fade = Hrdn/100` (`hfade/vfade` in Krita is the solid-area proportion of the radius: 100% hardness → 1.0 hard edge, 0% → 0.0 fully soft; this has the same direction as Photoshop hardness, not `(100-Hrdn)/100`). The `angle` value in Krita XML is stored in **radians**, while the UI range is **[0, 360) degrees**. Normalize negative angles with `% 360` first, or the angle control clamps them to 0.

## 3. Shape Dynamics

| ABR key | Condition | → Krita | Mapping formula | Status |
|--------|-----------|---------|----------|------|
| `szVr.bVTy==2` | Pressure | `PressureSize=true` | — | ✅ |
| `minimumDiameter` | — | `SizecommonCurve` | `0,{minD/100};1,1;` | ✅ |
| `angleDynamics.bVTy==6` | Direction | `RotationSensor=drawingangle` | sensorslist + fuzzy | ✅ |
| `angleDynamics.jitter` | `RotationValue` (rotation effect strength) | fuzzy / fuzzystroke curves | `RotationValue=jitter/100`; both random curves fixed at `0,0;1,1;` (Krita UI corresponds to -180°..+180°, XML coordinates normalized to 0..1) | ✅ (calibrated against a manually adjusted KPP) |
| `angleDynamics.bVTy==2` | Pressure | `RotationSensor=pressure` | — | ✅ |
| `angleDynamics.bVTy==0` and jitter > 0 | No control source (pure random jitter) | `PressureRotation=true` + fuzzy-only sensor | `RotationValue=jitter/100`; fuzzy / fuzzystroke curves `0,0;1,1;`, **without** drawingangle (does not follow stroke direction) | ✅ (pending re-verification in Krita) |
| `roundnessDynamics.bVTy==2` | Pressure | `PressureRatio=true` | — | ✅ |
| `minimumRoundness` | — | `RatiocommonCurve` | `0,{minR/100};1,1;` | ✅ |

## 4. Transfer

| ABR key | Condition | → Krita | Mapping formula | Status |
|--------|-----------|---------|----------|------|
| `opVr.bVTy==2` (opacity) | Pressure | `PressureOpacity=true` | — | ✅ |
| `opVr.Mnm` | — | `OpacitycommonCurve` | `0,{Mnm/100};1,1;` | ✅ |
| `prVr.bVTy==2` (flow) | Pressure | `PressureFlow=true` + `FlowUseCurve=true` | — | ✅ |
| `prVr.Mnm` | — | `FlowcommonCurve` | `0,{Mnm/100};1,1;` | ✅ |
| `wtVr` (wetness) | — | — | No equivalent in the pixel engine | ⛔ |
| `mxVr` (mixing) | — | — | No equivalent in the pixel engine | ⛔ |

## 5. Scattering

| ABR key | Meaning | → Krita | Mapping formula | Status |
|--------|------|---------|----------|------|
| `useScatter` | Enable scattering | `PressureScatter=true` (scattering toggle) | — | ✅ |
| `scatterDynamics.jitter` | Scatter amount (0–1000%) | `ScatterValue` (0–5.0) | `ScatterValue = jitter / 400` | ✅ |
| `scatterDynamics.bVTy==2` | Scatter amount follows pressure | `ScatterSensor=pressure` + `ScatterUseCurve=true` | — | ✅ |
| `scatterDynamics.bVTy==0` | Constant scatter | `ScatterUseCurve=false` (disable curve) | — | ✅ |
| `bothAxes` | Both axes | `AxisX` / `AxisY` | True → AxisX=Y=True; False → AxisX=False, Y=True | ✅ |
| Top-level `Spcn` | Scatter spacing | — | Not mapped to scatter amount (see note ②) | ⛔ |
| `Cnt` (count) | — | — | The Krita pixel engine has no “count” setting | ⛔ |

> Note ②: In Krita, `PressureScatter` is the toggle indicating whether scattering is enabled (serialized as `isChecked`), not the pressure-control setting; pressure control is determined by `ScatterSensor`. The actual scatter amount comes from `scatterDynamics.jitter` (top-level `Spcn` is spacing, not scatter amount).
>
> The scatter conversion factor `÷400`: Photoshop's scatter value of 0–1000% uses a Gaussian distribution (the value represents the maximum range, but points remain concentrated), while Krita's `ScatterValue` of 0–5.0 (UI 0–500%) uses a uniform distribution. Their visual densities differ, so linear `÷200` produces too much scatter. Calibrated against a measured anchor (PS 145% ≈ Krita 35%, i.e. `ScatterValue 0.35`), the empirical factor is approximately `÷4` (`jitter/400`). Adjust this factor in the scattering branch of `preset_xml.py` if needed.

| `countDynamics` | — | — | Same as above | ⛔ |

## 6. Not Mapped (Major Engine Differences; Listed for Future Enhancement)

| ABR key | Meaning | Reason |
|--------|------|------|
| `dualBrush` | Dual brush | Krita uses a masking-brush mechanism with different semantics |
| `useColorDynamics` (`H` / `Strt` / `Brgh` / `purity` / `clVr`) | Color dynamics | The applications' color models differ significantly |
| `Wtdg` (wet edges) | Wet edges | The pixel engine requires the “Wet” option; not enabled for now |
| `Nose` / `Rpt` (nozzle / repetition) | — | Airbrush behavior; not mapped for now |
| `brushProjection` / `useBrushPose` | Projection / pose | Advanced tilt features; not mapped for now |

## 7. Texture ✅ (Added in v1.1)

> Texture source: ABR `patt` section (matched to `Txtr.Idnt` by UUID); resource embedded as PNG
> (`type="patterns"`, consistent with official Krita 5.x samples). See `docs/developer-guide.md` and
> `docs/texture-mapping-proposal.md` for format details.

| ABR key | → Krita parameter | Mapping formula | Status |
|--------|--------------|----------|------|
| `useTexture` | `Texture/Pattern/Enabled` | `true` | ✅ |
| `Txtr.Idnt` | Resource lookup | Match `patt` record by UUID; embed PNG | ✅ |
| `Txtr.Nm` | `Name` / `PatternFileName` | Safe filename `tex_<first 8 chars of uuid>.png` | ✅ |
| PNG bytes | `PatternMD5Sum` | MD5 hex (`PatternMD5` left empty to work around a binary-writing bug in Krita 5.0) | ✅ |
| `textureScale` (%) | `Texture/Pattern/Scale` | `textureScale/100`, clamp [0.01, 10] | ✅ (user confirmed consistency) |
| `textureDepth` (%) | `Texture/Strength/Value` | `textureDepth/100` (0..1) | ✅ |
| `textureDepthDynamics.bVTy==2` | `PressureTexture/Strength/` + `Texture/Strength/UseCurve` | `true` + `true` (pressure curve; minimum value below) | ✅ |
| `textureDepthDynamics.bVTy==0` | `PressureTexture/Strength/` + `Texture/Strength/UseCurve` | `true` + `false` (effect enabled, no sensor; constant `Value`) | ✅ |
| `textureDepthDynamics.Mnm` | `Texture/Strength/commonCurve` | `0,{Mnm/100};1,1;` (only when `bVTy==2`) | ✅ |
| `InvT` | `Texture/Pattern/Invert` | Direct | ✅ |
| `textureBlendMode` | `Texture/Pattern/TexturingMode` | Prefer Krita's Photoshop modes: `linearHeight` → Linear Height (Photoshop)=15, `Hght` / `height` → Height (Photoshop)=14, `hardMix` → Hard Mix (Photoshop)=10; map other modes using Krita's enum (`Mul `→0, `Sbtr`→1, `Ovrl`→5, etc.); unknown modes fall back to 0 + warning | ✅ |
| `textureBrightness` (PS -150..150) | `Texture/Pattern/Brightness` | All modes: `round(0.10-v/250,2)`; clamp [-1,1] | ✅ |
| `textureContrast` (PS -50..100) | `Texture/Pattern/Contrast` | All modes use the Photoshop center factor; round to 0.01 and clamp [0,2] | ✅ |
| `TxtC` / `interpretation` | — | No Krita equivalent; silently ignored (source file default value) | ⚠️ |
| `protectTexture` | — | No Krita equivalent; retain a lightweight warning | ⚠️ |

> Brightness/contrast mapping is based on Krita's `KisTextureMaskInfo::recalculateMask()` and `research/test results 2` / `research/Krita results`:
> all modes use the standard calibration. Linear Height (Photoshop) previously used a special mapping with a 0.30 baseline / inverse contrast, but tests showed poor results, so this was canceled on 2026-08-27.
> Krita's UI is precise only to two decimal places; round all values to 0.01 before validating.

## 8. Control Source Encoding (`bVTy` → Krita Sensor)

| `bVTy` | Photoshop | Krita sensor | Status |
|------|-----------|--------------|------|
| 0 | Off | None | ✅ |
| 1 | Fade | No equivalent (not mapped) | ⛔ |
| 2 | Pressure | `pressure` | ✅ |
| 3 | Tilt | `tilt` (reserved, not enabled) | ⛔ |
| 4 | Wheel | No equivalent | ⛔ |
| 5 | Rotation random | No equivalent (not mapped; GUI warns when jitter > 0) | ⛔ |
| 6 / 7 | Initial direction / direction | `drawingangle` | ✅ |

## 9. Deduplication Rules

- Fully duplicate presets (same name + same UUID + same `Dmtr`) keep only the first. In the current file, this removes one duplicate “淘宝店” banner brush (20 → 19).
