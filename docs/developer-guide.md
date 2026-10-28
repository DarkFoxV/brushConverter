# brushConverter Project Structure and Internals

> For developers: explains how this project converts Photoshop brushes (`.abr`) into Krita brushes (`.kpp` / `.bundle`), along with pitfalls encountered during development and key conclusions.
>
> See [`parameter-mapping.md`](parameter-mapping.md) for the complete field-by-field parameter mapping checklist.

## 1. Overview

**brushConverter** converts Adobe Photoshop brush sets (`.abr`) into Krita brushes (`.kpp` presets / `.bundle` resource bundles). It provides both a command-line interface (CLI) and a graphical user interface (GUI), and can be packaged as a Windows executable with PyInstaller.

**Technology stack:** Python 3.12 + numpy + Pillow + PySide6 (GUI) + PyInstaller (packaging).

**Core data flow:**

```text
.abr file
   │  AbrFile.parse()          — split into 8BIM sections
   ├─ samp section → sampled-tip bitmap (BrushTip)
   ├─ desc section → brush parameter descriptors (Descriptor)
   └─ patt / phry → texture / thumbnail sections
   │
   │  map_presets()            — parameter mapping
   ▼
BrushPreset list (name / size / spacing / angle / hardness / dynamics / scatter…)
   │
   │  convert_presets()        — generate output
   ├─ build_preset_xml()  → preset XML
   ├─ build_kpp()         → .kpp (PNG + iTXt)
   └─ write_bundle()      → .bundle (ZIP resource bundle)
```

## 2. Project Structure

```text
brushConverter/
├── src/brush_converter/          # Core library (pure logic, no GUI dependency)
│   ├── abr/                      # ABR parsing
│   │   ├── reader.py             #   Header + 8BIM section iteration (AbrFile)
│   │   ├── samples.py            #   Extract samp tips (v1/v2 + v6.1/v6.2)
│   │   ├── rle.py                #   Photoshop PackBits RLE decoder
│   │   ├── descriptors.py        #   desc descriptor parsing (Descriptor/Value/Reader)
│   │   └── patterns.py           #   patt texture-pattern parsing (Pattern/VMA/RLE)
│   ├── kpp/                      # KPP/bundle generation
│   │   ├── preset_xml.py         #   Assemble preset XML + brush-tip definitions (png_brush/auto_brush)
│   │   ├── kpp_writer.py         #   Construct PNG chunks manually (iTXt/tEXt/IDAT)
│   │   └── bundle.py             #   .bundle (OpenDocument manifest/meta)
│   ├── mapping.py                # Map descriptors to BrushPreset parameters
│   └── convert.py                # Orchestrate the conversion pipeline (convert/convert_presets)
├── gui/                          # PySide6 GUI
│   ├── main_window.py            #   Main window (preview/selection/format choice/unmapped warnings)
│   ├── workers.py                #   Background parsing/conversion with QThread
│   └── __main__.py               #   python -m gui entry point
├── cli.py                        # CLI entry point (info/extract/convert/gui)
├── brushConverter_gui_entry.py   # GUI packaging entry point (avoids sys.path hacks)
├── brushconverter-*.spec         # PyInstaller configurations (CLI / GUI)
├── tests/test_mapping.py         # Parameter-mapping regression tests (requires sample files)
├── docs/                         # Documentation
├── assets/                       # Application icons
└── research/                     # Third-party source and research samples (not committed to git)
```

## 3. ABR Parsing

### 3.1 File Format Overview

ABR has two generations:

| Version | Layout |
|------|------|
| v1 / v2 (legacy) | Header (version + subversion = brush count), followed by brushes **sequentially** |
| v6 / v10 (new) | Sequence of **8BIM tagged blocks** after the header |

The new-format 8BIM sections traversed by `reader.py`:

| Section key | Contents | Used by this project? |
|----------|----------------|----------------|
| `samp` | Sampled-tip bitmap (RLE-compressed grayscale) | ✅ Extract brush tips |
| `desc` | Brush parameter descriptors | ✅ Parameter mapping |
| `patt` | Texture patterns | ✅ Parsed and mapped; see texture mapping docs |
| `phry` | Thumbnails | ⛔ Ignored |

Each 8BIM block = `8BIM` (4B) + key (4B) + length (4B, big-endian) + data + 4-byte alignment padding (**the final section may have no padding**).

### 3.2 Sampled Tips (`samples.py`)

Layout of a single v6.2 tip item (compared with GIMP's `gimpbrush-load.c`):

```text
u32  item_size
     [skip 301 bytes for v6.2] (skip 47 bytes for v6.1)
     [1+36 byte UUID (Pascal-style: 1-byte length + ASCII)]
4×i32 rect (top, left, bottom, right)
i16  depth_bits   (8 or 16)
i8   compress     (0=raw, 1=RLE)
...  pixel data
```

Tip width/height = `right - left`, `bottom - top`. Next tip position = `pos + 4 + round_up_to_4(item_size)`.

Legacy v1/v2 layout: `u16 type` (1 = skip procedural brush / 2 = sampled) → `u32 size` → `u32 misc` → `u16 spacing` → [v2: UCS-2 name] → `u8 aa` → `4×i16 short bounds` → `4×i32 long bounds` → `u16 depth` → `u8 compress` → data.

### 3.3 RLE (`rle.py`)

Photoshop PackBits: first read `height` big-endian `int16` values giving the compressed length of each row, then decode each row with PackBits:

- `n >= 0`: the next `n+1` bytes are literals.
- `n < 0` (`n != -128`): repeat the next byte `-n+1` times.
- `n == -128`: no operation.

Read 16-bit raw pixels as **little-endian**, consistent with GIMP's `GUINT16_FROM_LE`.

### 3.4 Grayscale Semantics (Important; Directly Affects Output)

In ABR sampled-tip bytes, **0 = ink (opaque), 255 = transparent**. Krita source confirms that both its ABR loader (`convertToQImage`) and GBR loader invert values using `255 - byte`.

Therefore, `BrushTip.gray` is consistently defined as an **opacity mask** (255 = ink, 0 = transparent); decoding applies `255 - raw`. This convention is used throughout the project, including previews and PNG brush-tip generation.

### 3.5 Descriptors (`descriptors.py`)

The `desc` section consists of `u32 version` (ignored) followed by a Photoshop binary Descriptor:

```text
Descriptor: unicode name → classID → u32 itemCount → items[]
item:       key (readId) + type (4-character code) + value
```

Value types include `long`, `doub`, `bool`, `TEXT`, `enum`, `UntF` (4-byte unit + double), `Objc` (nested descriptor), `VlLs` (value list), `tdta`, `alis`, `obj `, etc.

The brush preset list is at `desc["Brsh"]` (`VlLs`). Each item is an `Objc` containing `Nm ` (name), `Brsh` (tip definition: `Dmtr` / `Hrdn` / `Angl` / `Rndn` / `Spcn` / `sampledData` UUID), and various dynamics keys (`szVr` / `opVr` / `angleDynamics` / `scatterDynamics`, etc.).

> The parsing algorithm references SonyStone/ABR-Viewer (MIT); `research/descriptor-parser.ts` contains a complete TypeScript reference.

### 3.6 Texture Patterns (`patterns.py`)

The `patt` section stores texture patterns as length-prefixed Pattern records. The format was reverse-engineered in real samples, correcting ABR-specific differences against the Pattern / VirtualMemoryArrayList structures in `psd-tools`:

```text
Record = u32 len | record body (len bytes) | pad to 4
Body = u32 version (=1) | u32 color mode (3=RGB, 1=grayscale) | 2×i16 (width,height) |
       u32 name length (including trailing NUL) | name UTF-16BE | u8 ID length (=36) | UUID (ASCII) |
       VMA list: u32 version (=3) | u32 body_len | body {
         4×u32 rectangle (top,left,bottom,right) | u32 channel count | (channel count + 2) channel blocks
       }
Channel block = u32 is_written (0=empty) | u32 len | u32 depth | 4×u32 rectangle |
                u16 pixel_depth | u8 compression (0=RAW, 1=RLE) | data (len-23)
```

Key details:
- **Name length includes the trailing NUL** (a length of 27 means 26 visible characters + NUL).
- **Pattern ID is a u8 length + ASCII UUID**, unlike the Pascal string used for PSD Pattern in `psd-tools`.
- Associate patterns with brushes by **UUID** (`Txtr.Idnt` in `desc`), never by name. The sample has three different images all named `Shape 2.png`.
- RLE(1) uses the PSD variant: `height` u16 row-byte lengths + PackBits per row. A run of four repeated bytes has header `0xFD` (256-3), not 256-4.
- The `parse_patterns()` cursor must end exactly at the section boundary (4-byte alignment); otherwise, treat it as a format error.

## 4. Parameter Mapping (`mapping.py`)

`map_presets(abr)` converts each preset descriptor in `desc` into a `BrushPreset` dataclass. Fields include name, spacing, angle, roundness, hardness, diameter, scale, tip grayscale array, UUID, whether the brush is procedural, dynamics curves, scatter parameters, and unmapped warnings.

The mapped `BrushPreset` is serialized as Krita preset XML in `preset_xml.py`. Core mappings:

| Category | ABR source | Krita target |
|------|-----------|-----------|
| Size | `Dmtr` | `scale = Dmtr / max(tip width, tip height)`; pad the embedded sampled-tip PNG to a square |
| Spacing | `Spcn` (`#Prc`) | `spacing = Spcn/100` |
| Angle | `Angl` (degrees) | `angle = math.radians(Angl % 360)` |
| Hardness (procedural brush) | `Hrdn` | `hfade/vfade = Hrdn/100` |
| Pressure → size | `szVr.bVTy==2` + `minimumDiameter` | `SizecommonCurve` |
| Pressure → opacity | `opVr.Mnm` | `OpacitycommonCurve` |
| Pressure → flow | `prVr.Mnm` | `FlowcommonCurve` |
| Pressure → aspect ratio | `roundnessDynamics` + `minimumRoundness` | `RatiocommonCurve` |
| Rotation | `angleDynamics.bVTy` | `RotationSensor` (`drawingangle` / `pressure`) |
| Scatter | `useScatter` + `scatterDynamics.jitter` | `PressureScatter` + `ScatterValue` |

**Control-source codes (`bVTy`):** 0=off, 1=fade, 2=pressure, 3=tilt, 4=wheel, 5=rotation, 6/7=initial direction/direction. Currently mapped to Krita sensors: `pressure` (`bVTy=2`) and `drawingangle` (`bVTy=6/7`, follows stroke direction). `bVTy=1/3/4/5` are not mapped (if jitter > 0, the GUI warns that the rotation control source is unmapped). For direction-based rotation, Photoshop `angleDynamics.jitter` maps to Krita `RotationValue` (effect strength, `jitter/100`). The `fuzzy` and `fuzzystroke` random curves correspond in the UI to -180°..+180°, but XML uses normalized coordinates; the full range is `0,0;1,1;`. When `bVTy=0` (control off) but jitter > 0, this is pure random angle jitter: rotation must still be enabled (`PressureRotation=true`), using a sensor with only fuzzy/fuzzystroke (no drawingangle), with `RotationValue=jitter/100`.

**Procedural brushes** (no `sampledData` UUID, parameters only) map to Krita's `auto_brush` (procedural circular tip). `diameter`, `ratio` (roundness), and `hfade` / `vfade` (hardness) are placed in `MaskGenerator`.

See [`parameter-mapping.md`](parameter-mapping.md) for the complete field-by-field checklist.

## 5. KPP / Bundle Generation (`kpp/`)

### 5.1 `.kpp` Structure

A `.kpp` is **not a ZIP**; it is essentially a PNG file:

```text
PNG signature
IHDR    (200×200, 8-bit RGBA preview)
iTXt    (keyword="preset", zlib-compressed preset XML)
tEXt    (keyword="version"="5.0")
IDAT    (preview image data)
IEND
```

`kpp_writer.py` manually constructs these PNG chunks (length + type + data + CRC32).

### 5.2 Embedded Brush Tips

Krita 5.x uses `embedded_resources="2"`. The brush-tip PNG is **base64-embedded** in the preset XML's `<resources>`:

```xml
<Preset paintopid="paintbrush" name="..." embedded_resources="2">
  <resources>
    <resource name="..." filename="....png" type="brushes" md5sum="...">
      <![CDATA[ base64(PNG) ]]>
    </resource>
  </resources>
  ...
  <param name="brush_definition" type="string"><![CDATA[
    <Brush type="png_brush" filename="....png" md5sum="..." spacing="..." angle="..." scale="..."/>
  ]]></param>
</Preset>
```

`md5sum` is the MD5 hex digest of the **raw PNG bytes** of the brush tip.

### 5.3 Embedded Textures (`type="patterns"`)

Textures are embedded in `<resources>` just like brush tips, but use `type="patterns"` and PNG base64:

```xml
<resource name="tex_66e2987f.png" filename="tex_66e2987f.png"
          type="patterns" md5sum="...">
  <![CDATA[ base64(PNG) ]]></resource>
```

Preset parameters (the `TextureXml` / `_apply_texture` logic in `preset_xml.py`):
`Texture/Pattern/{Enabled,Name,PatternFileName,PatternMD5Sum,Scale,Brightness,Contrast,Invert,TexturingMode}`,
`Texture/Strength/{Value,UseCurve,commonCurve}`, and `PressureTexture/Strength/`.

`PressureTexture/Strength/` is the toggle for Krita's “effect strength” option (`isChecked`; see `getBool("Pressure"+id)` in `KisKritaSensorPack::read`), not a pressure sensor. Photoshop texture depth must set it to `true` whether or not a sensor is used. When depth follows pressure (`bVTy==2`), also set `Texture/Strength/UseCurve=true` and write `commonCurve` (minimum = `Mnm/100`). When `bVTy==0` (no sensor), set `Texture/Strength/UseCurve=false`; `Texture/Strength/Value` (`textureDepth/100`) supplies constant strength.

Notes:
- **`PatternMD5Sum` stores MD5 hex**; leave `PatternMD5` empty. Krita 5.0 once wrote raw binary to that field, producing invalid XML (fixed in an official Krita MR); newer versions use `PatternMD5Sum`.
- `TexturingMode` values come from Krita's `KisTextureOptionData::TexturingMode`: Multiply=0, Subtract=1, Lightness=2, Gradient=3, Darken=4, Overlay=5, Color Dodge=6, Color Burn=7, Linear Dodge=8, Linear Burn=9, Hard Mix (Photoshop)=10, Hard Mix Softer (Photoshop)=11, Height=12, Linear Height=13, Height (Photoshop)=14, Linear Height (Photoshop)=15. Map ABR `linearHeight` to 15 first, rather than accidentally mapping it to Darken=4.
- Brightness/contrast conversion follows Krita's `KisTextureMaskInfo::recalculateMask()` and Photoshop/Krita comparisons. All modes use the same mapping: brightness `round(0.10-v/250,2)`; contrast uses the Photoshop center factor (`C<0 → 1+C/100`, `C>=0 → 1/(1-C/100)`). Clamp to Krita UI ranges (brightness [-1,1], contrast [0,2]). A special mapping for Linear Height (Photoshop) using a 0.30 baseline and inverse contrast tested poorly and was canceled on 2026-08-27. Source snapshots and links are in `research/krita_texture/` and `research/README.md`.

### 5.4 Bundle Structure

A `.bundle` is a ZIP archive (following `KoResourceBundleManifest.cpp` strictly):

```text
mimetype                      first entry, stored without compression = "application/x-krita-resourcebundle"
META-INF/manifest.xml         OpenDocument manifest namespace (easy to get wrong; see §7)
meta.xml                      OpenDocument metadata
paintoppresets/*.kpp          Self-contained brush presets
```

## 6. CLI and GUI

- **CLI** (`cli.py`): `info` (summary), `extract` (export brush-tip PNGs), `convert` (convert), `gui` (launch interface).
- **GUI** (`gui/`): parsing and conversion both run in background `QThread`s (`workers.py`) so the interface remains responsive. Each brush has a card (checkbox + thumbnail + name + unmapped warnings); supports select all / deselect all, output format selection (`.kpp` / `.bundle`), and a warning dialog before conversion if selected brushes contain unmapped parameters.

## 7. Important Development Findings (Pitfalls)

These conclusions took source-code comparisons and repeated trial and error to establish; keep them in mind during maintenance.

### 7.1 Format-Level Findings

1. **`.kpp` is PNG + an iTXt chunk, not ZIP.** Preset XML is zlib-compressed into `iTXt` (keyword=`preset`); the older 2.2 format uses `zTXt` + version=`2.2`.
2. **The tip is PNG, not GBR.** In Krita 5.x, `png_brush` treats a PNG with no alpha and uniform grayscale as a mask (white=ink, black=transparent). A grayscale PNG works directly: no GBR and no byte inversion required. This was the key change that overturned the phase-1 GBR plan in phase 3.
3. **Grayscale convention:** ABR/GBR store 0=ink and 255=transparent; `png_brush` uses white=ink. The project standardizes on “opacity mask, 255=ink.”
4. **The bundle `manifest.xml` uses the OpenDocument namespace** (`urn:oasis:names:tc:opendocument:xmlns:manifest:1.0`), not a custom format; it is easy to get wrong.
5. **Krita's official ABR importer does not parse `desc`** (`kis_abr_brush_collection.cpp` only extracts `samp` bitmaps and uses default parameter values). Parameter mapping is therefore a value-add over the official importer.

### 7.2 Parameter-Mapping Findings

6. **Angles are stored in radians, not degrees.** Krita brush XML stores `angle` in radians (`CommonData.angle`); the UI converts to degrees using `zoom(scale(180/π))`.
7. **The angle UI range is [0,360); negative angles are clamped to 0.** `KisAngleSelector`'s spin box uses `setRange(0,360)`, so `-33°` is clamped by `setValue` to 0 (=360°). Normalize with `angle % 360` first (`-33° → 327°`), then convert to radians. This fixed a second bug where degrees-to-radians conversion was correct but negative angles still displayed as 360°.
8. **Hardness is `fade = Hrdn/100`, not `(100-Hrdn)/100`.** Krita auto-brush `hfade/vfade` is the proportion of the radius occupied by the solid region (`valueAt` is solid when `n < fade`), so it follows Photoshop hardness (84% → 0.84, not 0.16).
9. **`PressureScatter` toggles whether scattering is enabled; it does not mean “pressure controls scatter.”** It serializes `isChecked` (`getBool("Pressure" + id)`); pressure control is determined by `ScatterSensor`. Misreading this confuses both concepts.
10. **Scatter amount comes from `scatterDynamics.jitter`, not top-level `Spcn`.** Top-level `Spcn` is spacing. Scatter `jitter` ranges from 0–1000%.
11. **Scatter conversion `÷400` is empirical.** Photoshop scatter uses a Gaussian distribution (the value describes the maximum range but points remain concentrated); Krita `ScatterValue` uses a uniform distribution, so visual density differs. A measured anchor, PS 145% ≈ Krita 35%, yields a factor of about `÷4`.
12. **Template-version trap:** using an old `Basic_tip_default.kpp` template (format 2.2) omits many Krita 5.x `*commonCurve` / `Pressure*` parameters. Booleans and numeric values must use `type="internal"` with plain text (not `type="string"` with CDATA), or Krita may fail to read them, revert to defaults, and leave dynamics “uncontrolled.”

### 7.3 Parsing Implementation Findings

13. **numpy 2.x does not allow `arr[a:b] = bytes`.** Use `np.frombuffer(buf, dtype, count, offset)` instead.
14. Read 16-bit raw pixels as little-endian.
15. The final 8BIM section may not have 4-byte alignment padding; the iterator must tolerate slight overrun.
16. Skip 47 bytes for v6.1 and 301 bytes for v6.2 (`abr_skipped_bytes`).
17. Sampled tips must be `reshape(height, width)`; otherwise, a 1D array is saved as a one-pixel-high horizontal strip (the cause of the “thin white line” bug).

### 7.4 Packaging and Release Findings

18. **Manually remove old artifacts before rebuilding with PyInstaller.** In some sandbox environments, a secure-delete shim blocks PyInstaller's internal `shutil.rmtree` calls from `--clean` / `--noconfirm` (error `SAFE_DELETE_FAIL_CLOSED`). Workaround: run `rm -rf dist/ build/` first, then package without `--clean`.
19. **Git Credential Manager token retrieval can be unreliable.** Without `gh` or a PAT, a release can be published through the REST API using an OAuth token from `git credential fill`. However, this often fails in a new shell; trigger credential refresh with `git ls-remote` (or push), then immediately run `fill` and use the token **within the same command**.

## 8. Reference Implementations and Samples

- **GIMP** (GPL): `app/core/gimpbrush-load.c` + `gimp-utils.c` — authoritative references for ABR v6 tip parsing and RLE decoding.
- **Krita** (GPL): `libs/brush/kis_abr_brush_collection.cpp` (ABR import), `kis_circle_mask_generator.cpp` (fade math), `kis_brush.cpp` / `kis_global.h` (angle units), `KisScatterOption.cpp` (scatter formula), `KoResourceBundleManifest.cpp` (bundle format).
- **SonyStone/ABR-Viewer** (MIT): reference for descriptor parsing.
- These sources are downloaded under `research/` (kept locally, not committed to git).

**Source retrieval tip:** raw links on `invent.kde.org` may redirect to HTML; use `raw.githubusercontent.com/KDE/krita/master/...` instead. GitHub's `git/trees?recursive=1` endpoint can list the repository tree without authentication.

## 9. Development and Testing

```bash
# Environment
conda activate brushConverter
pip install -r requirements.txt

# Convert (CLI)
python cli.py convert <file.abr> -o converted

# GUI
python cli.py gui        # or python -m gui

# Tests (if sample files are missing, tests skip automatically; put samples in tests/ to run all assertions)
python -m pytest tests/ -q

# Packaging
pyinstaller brushconverter-cli.spec    # → dist/brushconverter-cli/
pyinstaller brushconverter-gui.spec    # → dist/brushConverter/
```

The test sample is a commercial brush set of 42 MB and is not included in the repository (see `.gitignore`). You must provide it yourself in the `tests/` directory.
