# Texture Mapping Proposal

> ✅ **Confirmed and fully implemented (2026-08-25)**: all five decisions were implemented using the recommended options.
> Code is in `abr/patterns.py`, `mapping.py`, `preset_xml.py`, and `convert.py`.
> All 26 tests passed; see Section 7 of `docs/parameter-mapping.md` for the mapping checklist.
>
> Reverse-engineered through tests on the real sample `tests/海怪笔刷-详情展示的勾线笔套装组18支.abr` (v6.2, 20 presets).
> The original proposal called for confirmation before implementation. The implementation follows the project's usual approach: compare against official Krita 5.x exports and calibrate using real files.

## 0. Current State

- `useTexture` currently only triggers `_collect_warnings` (warning that “texture” is not mapped); the texture is discarded during conversion.
- **9 of 19 brushes** in this file have texture enabled (two line-art brushes, technical pen, charcoal pencil, hard pencil, soft pencil, two coloring brushes, airbrush, etc.), making this the largest unmapped feature.

## 1. Confirmed Findings (Verified in Tests)

### 1.1 ABR `patt` Section Format (Reverse-Engineered and Verified)

The `patt` section contains four length-prefixed Pattern records. Each record parses correctly, and the cursor aligns exactly with the end of the section (33,178,816 bytes; zero-byte discrepancy):

```text
Record = u32 len | record body (len bytes) | pad to 4-byte boundary
Body = u32 version (=1) | u32 color mode (3=RGB) | 2×i16 (width,height) |
       u32 name length (including trailing NUL) | name UTF-16BE |
       u8 ID length (=36) | UUID (ASCII) |
       VMA list: u32 version (=3) | u32 body_len | body {
         4×u32 rectangle (top,left,bottom,right) | u32 channel count |
         (channel count + 2) channel blocks
       }
Channel block = u32 is_written (0=empty) | u32 len | u32 depth |
                4×u32 rectangle | u16 pixel_depth | u8 compression (0=RAW, 1=RLE) |
                data (len-23)
```

Four textures were found in the sample (**associate by UUID, not by name**):

| UUID | Name | Dimensions | Channels | Data |
|------|------|------|------|------|
| 438c2948-d232-11e5-b988-9ff33e1af9cd | R. Melentyev's Art Texture | 1×1 | RGB×3 | Solid gray (236,236,236), neutral texture |
| 66e2987f-d47b-fa49-9e36-3ffa8b78533a | Shape 2.png | 1920×1920 | RGB×3 | Grayscale paper texture, MD5 `fe85154f…` |
| f648c44c-5189-b14e-8ef2-926477d0bbe7 | Shape 2.png | 1920×1920 | RGB×3 | Grayscale paper texture, MD5 `546cff5b…` |
| 69d92381-cf86-a54b-9d04-7f0fc2d9345b | Shape 2.png | 1920×1920 | RGB×3 | Grayscale paper texture, MD5 `303001b2…` |

- The three `Shape 2.png` images have different contents (different MD5 hashes), so they must be matched using `Txtr.Idnt` (UUID).
- All textures in this sample use compression=0 (RAW). The implementation must also support RLE(1), using PSD-style RLE: per-row u16 byte lengths followed by PackBits data.

### 1.2 Texture Parameters in Brush `desc` (9 Brushes Tested)

| ABR key | Type / value | Meaning |
|--------|-----------|------|
| `useTexture` | bool `True` | Enable texture |
| `Txtr` | `Objc{Nm: TEXT, Idnt: TEXT}` | Texture reference: name + UUID (find the `patt` record by `Idnt`) |
| `textureScale` | `UntF #Prc` (20–73) | Texture scale % |
| `textureDepth` | `UntF #Prc` (4–55) | Texture depth % |
| `minimumDepth` | `UntF #Prc` (0) | Minimum depth |
| `textureDepthDynamics` | `Objc{bVTy=2, fStp, jitter=0, Mnm=0}` | Depth dynamics (`bVTy=2` means pressure) |
| `textureBlendMode` | enum `BlnM`, value `linearHeight` | Blend mode (Linear Height) |
| `InvT` | bool (sometimes `True`) | Invert |
| `textureBrightness` | long (-31 to 40) | Brightness (-100 to 100) |
| `textureContrast` | long (-50 to 6) | Contrast (-100 to 100) |
| `TxtC` | bool `True` | “Texture Each Tip” (no Krita equivalent) |
| `interpretation` / `protectTexture` | bool | No direct Krita equivalent (ignore / flag) |

### 1.3 Krita 5.x Texture Preset XML (Confirmed in Local Official Sample `research/kpp_samples/ref_5.0.xml`)

- **Texture resources are embedded** in `<resources>`, like brush tips, using `type="patterns"` and PNG base64:

```xml
<resource name="test_pattern.png" filename="test_pattern.png"
          type="patterns" md5sum="dc4e9099acb7c3cd33293a48f75c6ff7">
  <![CDATA[iVBORw0KGgo...]]>
</resource>
```

- Parameters below were extracted item by item from a Krita 5.0 export (internal values are plain text; string values use CDATA):

```text
Texture/Pattern/Enabled          internal  true
Texture/Pattern/Name             string    <filename>
Texture/Pattern/PatternFileName  string    <filename>
Texture/Pattern/PatternMD5Sum    string    <PNG MD5 hex>       <- authoritative field added after 5.0
Texture/Pattern/PatternMD5       string    (raw binary was written in 5.0; bug; may be empty/omitted in newer versions)
Texture/Pattern/Scale            internal  1                  <- 0.01–10; 1=100%
Texture/Pattern/Brightness       internal  0
Texture/Pattern/Contrast         internal  1
Texture/Pattern/CutoffLeft/Right/CutoffPolicy internal 0/255/0
Texture/Pattern/Invert           internal  false
Texture/Pattern/NeutralPoint     internal  0.5
Texture/Pattern/OffsetX/Y        internal  0 / 0
Texture/Pattern/isRandomOffsetX/Y internal false / false
Texture/Pattern/MaximumOffsetX/Y internal 2 / 2
Texture/Pattern/TexturingMode    internal 1
Texture/Pattern/UseSoftTexturing internal false
Texture/Strength/Sensor          string    <!DOCTYPE params> <params id="pressure"/>
Texture/Strength/UseCurve        internal true
Texture/Strength/UseSameCurve    internal true
Texture/Strength/Value           internal 1                  <- 0..1 (100%)
Texture/Strength/commonCurve     string    0,0;1,1;
Texture/Strength/curveMode       internal 0
PressureTexture/Strength/        internal true/false          <- pressure toggle
```

- Add the above `Texture/...` entries to the default parameter template (`DEFAULT_PARAMS`). For brushes without texture, use `Enabled=false`, following `ref_勾线笔.xml`.

## 2. Mapping Plan (ABR → Krita)

| ABR key | → Krita parameter | Formula | Status |
|--------|--------------|------|------|
| `useTexture` | `Texture/Pattern/Enabled` | `true` | ✅ |
| `Txtr.Idnt` | Resource lookup | Match `patt` record by UUID; embed PNG as `type="patterns"` | ✅ |
| `Txtr.Nm` + UUID | `Name` / `PatternFileName` | Safe filename (e.g. `tex_66e2987f.png`) | ✅ |
| — | `PatternMD5Sum` | MD5 hex of PNG bytes (`PatternMD5` left empty to avoid Krita 5.0's binary-writing bug) | ✅ |
| `textureScale` | `Texture/Pattern/Scale` | `textureScale/100`, clamp [0.01, 10] | ✅ (numeric calibration to be tested) |
| `textureDepth` | `Texture/Strength/Value` | `textureDepth/100` | ✅ |
| `textureDepthDynamics.bVTy==2` | `PressureTexture/Strength/` = true + `Texture/Strength/UseCurve` = true | Pressure controls depth (`Mnm` is the minimum) | ✅ |
| `textureDepthDynamics.bVTy==0` | `PressureTexture/Strength/` = true + `Texture/Strength/UseCurve` = false | Effect enabled without a sensor; `Value`=`textureDepth/100` remains constant | ✅ |
| `textureDepthDynamics.Mnm` | `Texture/Strength/commonCurve` | `0,{Mnm/100};1,1;` (only for `bVTy==2`) | ✅ |
| `InvT` | `Texture/Pattern/Invert` | Direct | ✅ |
| `textureBlendMode` | `Texture/Pattern/TexturingMode` | **See table below** | ✅/❓ |
| `textureBrightness` | `Texture/Pattern/Brightness` | All modes: `round(0.10-v/250,2)`; clamp [-1,1] | ✅ |
| `textureContrast` | `Texture/Pattern/Contrast` | All modes use the Photoshop center factor; clamp +100 extreme to Krita UI range [0,2] | ✅ |
| `TxtC` / `interpretation` / `protectTexture` | — | No Krita equivalent; ignore while retaining lightweight warnings | ⚠️ |

### 2.1 Blend-Mode Mapping (Photoshop → Krita `TexturingMode`)

| PS value | Meaning | Krita mode | Expected value |
|-------|------|-----------|----------|
| `Hght` | Height (Photoshop) | Height (Photoshop) | 14 (measured using a test ABR) |
| `linearHeight` | Linear Height (Photoshop) | Linear Height (Photoshop) | 15 (`KisTextureOptionData` enum) |
| `Mul ` | Multiply | Multiply | 0 |
| `Scrn` | Screen | Screen | 2 |
| `Sbtr` | Subtract | Subtract | 1 |
| `Ovld` | Overlay | — (no direct equivalent; fall back to Multiply + warning) | — |
| Other / unknown | — | Fall back to Multiply (0) + warning | — |

> The full enum was checked against Krita's `KisTextureOptionData.h`: Photoshop-specific modes are Hard Mix=10, Hard Mix Softer=11, Height=14, and Linear Height=15.

### 2.2 Brightness / Contrast Calibration (Following the `÷400` Scattering Approach)

- Based on Krita source `KisTextureMaskInfo::recalculateMask()` and quantitative Photoshop tests, the final composite-matching formula was updated to use the same mapping for all modes: brightness=`round(0.10-v/250,2)`; for contrast, negative values use `1+v/100`, positive values use `1/(1-v/100)` (round to two decimals and clamp to [0,2]). The special Linear Height (Photoshop) mapping (0.30 baseline / inverse contrast) tested poorly and was canceled on 2026-08-27.
- Keep the neutral value conservative: Photoshop 0/0 → Krita 0/1 (Krita official sample's neutral defaults).

## 3. Implementation Plan (By File)

1. **Add `src/brush_converter/abr/patterns.py`**: `parse_patterns(patt_bytes) -> dict[uuid, PatternTexture]`
   - `PatternTexture`: name, uuid, image (`np.ndarray`, RGB or L), width, height, color_mode.
   - Channel decompression: copy RAW data directly; decode RLE using “u16 row length + PackBits” (PSD variant; see `psd-tools` compression).
   - Self-validation: the record cursor must land exactly at the end of the section; unsupported color modes other than 3/1 and unknown versions raise clear errors.
2. **`abr/__init__.py`**: export patterns; add a `patterns` field to `AbrFile` (parse `patt` if present, with lazy / tolerant handling).
3. **`mapping.py`**:
   - Add a `TextureSettings` dataclass (name/uuid/scale/invert/brightness/contrast/depth/depth_min/pressure/blend_mode/image).
   - Add `BrushPreset.texture`; for presets with `useTexture`, `map_presets` looks up `Txtr.Idnt` in `patt` and populates it.
   - `_collect_warnings`: if a texture is found and mapped successfully, remove the “texture” warning; retain specific warnings if the UUID is missing, the blend mode falls back, or `protectTexture` is present.
4. **`kpp/preset_xml.py`**:
   - Add default `Texture/...` and `Texture/Strength/...` entries to `DEFAULT_PARAMS` (`Enabled=false`).
   - Make `_resources_xml` support multiple resources (brush-tip PNG + texture PNG).
   - Add a `texture` argument to `build_preset_xml` and write parameters as described in Section 2.
5. **`convert.py`**: `_render_preset` generates texture PNGs (RGB/L → PNG bytes) and passes them to XML; no bundle changes needed (texture is embedded in the KPP).
6. **GUI**: update warning text based on mapping changes (no UI structure changes).
7. **Tests**:
   - `tests/test_patterns.py`: four real-sample textures (name/UUID/dimensions/MD5/1×1 and 1920×1920), plus an RLE decoding unit test (construct a PackBits sample).
   - Mapping: verify texture fields for `useTexture` presets; warning no longer includes “texture”.
   - `preset_xml`: output XML includes `<resource type="patterns">`, `PatternMD5Sum`, `Enabled=true`, and the strength curve.
   - End-to-end conversion: bundle MD5 matches (following existing test patterns).
8. **Docs**: remove texture from Section 6 of `parameter-mapping.md` and add a texture mapping table; add `patt` format and texture-embedding notes to `developer-guide.md`.

## 4. Deliverables and Validation

- After conversion, the nine textured brushes contain embedded 1920×1920 texture PNGs in their `.kpp` files (larger files expected, approximately +1–3 MB per brush); the `.bundle` can be imported in one step.
- **Needs testing in Krita:** verify that textures appear and work, and that scale/depth/invert/brightness/contrast/blend mode approximate the original Photoshop brushes. The 1×1 neutral texture used by two line-art brushes should look almost texture-free in Krita, matching Photoshop.

## 5. Decisions Awaiting Confirmation

1. **Texture resource embedding:** embed PNG (`type="patterns"`, matching official Krita 5.0 samples) — recommended; or convert to GIMP `.pat`?
2. **Blend modes:** use the mapping in 2.1 and fall back to Multiply with a warning for unknown modes — recommended; or silently fall back to Multiply?
3. **Brightness/contrast formula:** apply the mapping in 2.2 first and calibrate after testing in Krita — recommended; or leave brightness/contrast unmapped (defaults only) in this version?
4. **1×1 neutral texture** (R. Melentyev's Art Texture used by two line-art brushes): preserve and enable it — recommended for fidelity; or skip it (those two brushes would effectively have no texture)?
5. **`protectTexture` / `TxtC`, etc.:** ignore and retain lightweight warnings — recommended; or ignore silently?
