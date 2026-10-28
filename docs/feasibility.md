# ABR → KPP Brush Converter — Feasibility Report and Project Structure

> Phase 1 deliverable | Research date: 2026-08-24
> Conclusion: **Feasible**. High-fidelity conversion is achievable for sampled brush tips; parameterized brush dynamics require approximate mapping.

## 1. Key Conclusions

| Goal | Feasibility | Notes |
|------|--------|------|
| Extract sampled-tip bitmaps from ABR | ✅ Fully feasible | Format reverse-engineered, with several open-source implementations for reference |
| Generate usable Krita `.kpp` presets | ✅ Fully feasible | Structure verified using a real `.kpp`: PNG + embedded XML in `zTXt` |
| Package as a Krita `.bundle` resource bundle | ✅ Fully feasible | ZIP container; official Krita import format |
| Migrate brush dynamics parameters (e.g. pressure curves) 1:1 | ⚠️ Partially feasible | ABR `desc` descriptors can be parsed, but the two applications use different parameter models, so only approximate mapping is possible |
| Migrate textures (`pattern`) | ⚠️ Feasible, but deferred | The `patt` block format is documented publicly; planned as a later enhancement |
| GUI + packaged executable | ✅ Fully feasible | Mature PySide6 + PyInstaller solution |

## 2. ABR Format Research Findings

The file header contains a 2-byte big-endian major version and a 2-byte minor version, followed by one of two broad layouts.

### 2.1 Legacy Format (v1/v2, Photoshop ≤ 7)
- Documented in Adobe's official *Photoshop File Formats Specification*.
- Simple structure: `brush count` followed by each brush's dimensions and 8-bit grayscale bitmap, optionally RLE-compressed.
- Parsing difficulty: **Low**.

### 2.2 New Format (v6+, Photoshop 7–CC)

Starting at offset 4, the file contains a series of 8BIM tagged blocks (publicly documented):

```
[version(2B)][subversion(2B)]
[8BIM][samp][length][...]   ← sampled-tip bitmap
[8BIM][patt][length][...]   ← texture pattern
[8BIM][desc][length][...]   ← descriptor (brush parameters, tip/parameter associations)
```

- **v6.1**: each `samp` item = Pascal-string ID + rectangle + depth + compression mode + bitmap data (RLE, same algorithm as PSD).
- **v6.2**: each `samp` item = ID + virtual-memory-array list (more complex, but GIMP has a mature implementation to reference).
- `desc` uses Photoshop's descriptor structure (documented in the PSD specification) and stores the full dynamic parameters of newer brushes.
- Parsing difficulty: **Medium** (low for v6.1; v6.2 requires reference to GIMP source code).

### 2.3 Reference Implementations (Open Source; for Learning the Format)

| Project | Language | Coverage |
|------|------|----------|
| GIMP `file-abr` plugin | C | Most complete: full v1/v2/v6.1/v6.2 support |
| abrViewer | C# | v6.1 bitmap extraction |
| nijiGPen `file_formats.py` | Python + numpy | v1/v2 + v6 bitmap extraction; small codebase and the most useful Python example |

## 3. KPP Format Research Findings (Verified in Practice)

A real preset, `AutoBrush_70px_rotated.kpp`, was downloaded from the official Krita repository and parsed successfully:

```
.kpp = PNG image (preview thumbnail; 200×200 recommended)
     + zTXt chunk (keyword="preset", zlib-compressed XML)
     + tEXt chunk ("version", etc.)
```

Core XML structure:

```xml
<Preset name="..." paintopid="paintbrush">
  <param name="brush_definition"><![CDATA[
    <Brush type="auto_brush" spacing="0.1" angle="0">
      <MaskGenerator radius="70" .../>
    </Brush>
  ]]></param>
  <param name="CurveOpacity"><![CDATA[0,0;1,1;]]></param>
  ... (pressure curves, sensors, and other parameters)
</Preset>
```

**Key discovery (architecturally important):** In Krita 5.x (`BrushVersion=2`), image tips are **no longer embedded** in the `.kpp`. Instead, the preset references a separate tip file (GBR/GIH) in the resource system using `filename` + `md5sum`. Therefore, the converter needs to produce:

1. **GBR tip file** — GIMP brush format, loaded natively by Krita. Header layout confirmed in Krita source `kis_gbr_brush.cpp`: `header_size, version(=2), width, height, bytes(=1 grayscale), magic("GIMP"), spacing` are all big-endian uint32 values, followed by a null-terminated name and bitmap data.
2. **`.kpp` preset** — PNG preview + `zTXt` XML; the XML references the GBR above.
3. **`.bundle` resource bundle** — ZIP containing `mimetype`, `META-INF/manifest.xml`, `meta.xml`, `paintoppresets/*.kpp`, and the tip file. This is the final format delivered to users for one-step import into Krita.

## 4. Conversion Pipeline Design

```
.abr ──► parser ──► [tip bitmap] ──► grayscale preparation / edge cleanup ──► GBR tip
              │                                                        │
              └─► [desc parameters] ──► parameter map ──► preset XML ──┤
                                                                       ▼
                                                     .kpp (PNG+zTXt) ──► .bundle ──► import into Krita
```

Initial parameter-mapping strategy:
- Brush-tip bitmap → `paintbrush` engine + image tip; use ABR spacing or default to 0.25.
- Size / spacing / angle → direct mapping.
- Pressure opacity / size → map to Krita `OpacitySensor` / `SizeSensor` curves.
- Dynamics that cannot be mapped (scatter, dual brush, wet edges, etc.) → use reasonable defaults and mark as “partial conversion” in the GUI.

## 5. Verified Environment

- Conda environment: `D:\program\anaconda3\envs\brushConverter`, Python **3.12.13** ✅
- Planned dependencies (all mature and installable with pip):
  - `numpy` (bitmap array operations)
  - `Pillow` (PNG I/O and preview generation; PNG text chunks can be written manually to control `zTXt` compression)
  - `PySide6` (GUI)
  - `PyInstaller` (packaging executable)
  - `pytest` (tests)
- No steps require compiling C extensions or using closed-source components.

## 6. Recommended Project Structure

```
brushConverter/
├── docs/                        # Documentation
│   ├── feasibility.md           # This report
│   └── format_notes/            # ABR/GBR/KPP format notes and field tables
├── research/                    # Research material (real samples, Krita source references)
├── src/brush_converter/         # Core package (pure logic, no GUI dependency)
│   ├── abr/
│   │   ├── reader.py            # Header / 8BIM section dispatch
│   │   ├── samples.py           # v1/v2/v6.1/v6.2 bitmap extraction
│   │   ├── descriptors.py       # `desc` parameter parsing
│   │   └── patterns.py          # `patt` extraction (later)
│   ├── kpp/
│   │   ├── gbr_writer.py        # Grayscale bitmap → GBR
│   │   ├── preset_xml.py        # Preset XML generation (template + parameter mapping)
│   │   ├── kpp_writer.py        # PNG + `zTXt` assembly
│   │   └── bundle.py            # `.bundle` ZIP packaging
│   ├── mapping.py               # ABR → Krita parameter mapping table
│   └── convert.py               # Pipeline orchestration (single file → bundle)
├── gui/
│   ├── __main__.py              # Entry point
│   ├── main_window.py           # Main window (drop ABR, tip preview, batch conversion)
│   └── workers.py               # Background conversion with QThread
├── tests/                       # pytest + small real-sample fixtures
├── cli.py                       # CLI entry point (implement before GUI for easier debugging)
├── requirements.txt
└── pyproject.toml
```

Design principle: **Keep core conversion logic completely decoupled from the GUI** (`gui/` and `cli.py` should be thin wrappers), enabling testing and future extension.

## 7. Phased Implementation Plan

| Phase | Content | Deliverable | Acceptance criteria |
|------|----------|-------------|---------------------|
| 1 ✅ | Format research, structural design | This report + directory skeleton | — |
| 2 | ABR parser (v1/v2 → v6.1 → v6.2) + `cli.py` | CLI tool that exports brush-tip PNGs | Extract all tip bitmaps from real `.abr` files |
| 3 | KPP/GBR/bundle generator | Complete conversion pipeline | Generated `.bundle` imports successfully and works in Krita 5.x |
| 4 | GUI (PySide6) | Graphical interface | Drag-and-drop / batch conversion, tip preview, progress and error reporting |
| 5 | Packaging and release | PyInstaller executable | Runs on machines without Python installed |

At the end of each phase, run regression tests using real brush files (collect samples exported from different Photoshop eras in `tests/fixtures/`).

## 8. Risks and Mitigations

| Risk | Level | Mitigation |
|------|------|------|
| Complex v6.2 virtual-memory-array parsing | Medium | Refer to GIMP `file-abr` C implementation; support v6.1 first and add v6.2 iteratively |
| Modern Photoshop brushes contain many dynamics that cannot be mapped 1:1 | Medium | Accept approximate mapping; clearly label conversion fidelity in the GUI |
| KPP/XML fields differ across Krita versions | Low | Target Krita 5.x (`BrushVersion=2`) and verify empirically |
| Details of PNG `zTXt` writing | Low | Manual PNG chunk construction has been verified; compare binary output against official KPP samples |
