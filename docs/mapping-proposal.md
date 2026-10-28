# ABR → Krita Parameter Mapping Proposal (Pending Confirmation)

> Derived by parsing the real sample `海怪笔刷…18支.abr` (v6.2, 20 presets: 14 sampled + 6 procedural).
> This proposal should be confirmed before implementation proceeds.

## 0. Confirmed Facts

- The `desc` section can be fully parsed: name `Nm `, diameter `Dmtr`, hardness `Hrdn`, angle `Angl`, roundness `Rndn`, spacing `Spcn`, and brush-tip UUID `sampledData`.
- Sampled brushes have a `sampledData` UUID; procedural brushes have no UUID but do have `Hrdn`.
- Multiple presets can share the same tip at different diameters. For example, “勾线笔” at 1901 px and “大怪兽-勾线笔” at 26 px share `87465e27…`.
- Dynamic settings use a common structure: `{ bVTy variable type, fStp fade steps, jitter, Mnm minimum value }`, plus `minimumDiameter` / `minimumRoundness` / `tiltScale` (`#Prc` percentages) and `useXXX` Boolean switches.

## 1. Mapping in Three Tiers

### Tier 1 · Exact Mapping (lossless; implement all)
| ABR key | Meaning | → Krita | Notes |
|--------|------|---------|------|
| `samp` bitmap | Brush-tip image | GBR brush tip | Copy the original bytes directly (0 = ink); Krita displays it correctly when loaded |
| `Nm ` | Name | Preset name | Preserve the original Chinese name |
| `Spcn` | Spacing % | `spacing` | Both are percentages of brush diameter; map directly |
| `Angl` | Angle (degrees) | `angle` / rotation | Direct mapping |
| `Rndn` | Roundness % | `ratio` | Krita ratio = roundness; direct mapping |
| `Dmtr` | Diameter in px | Size scaling | **See decision 1** |

### Tier 2 · Approximate Mapping (pressure dynamics; recommended)
| ABR key | → Krita | Mapping method |
|--------|---------|----------|
| `minimumDiameter` (`#Prc`) | `SizeSensor` pressure curve | At zero pressure, size = diameter × minimum value |
| `opVr` (opacity dynamics) | `OpacitySensor` pressure curve | Includes jitter / minimum value |
| `wtVr` (flow dynamics) | `FlowSensor` pressure curve | Includes jitter / minimum value |
| `szVr.jitter` (size jitter) | `SizeSensor` random | Map the jitter value |
| `angleDynamics` / `roundnessDynamics` | Rotation / ratio dynamics | Includes jitter |
| `prVr` (pressure → ?) | Pressure sensor | Determine based on variable type `bVTy` |

### Tier 3 · Skip or Flag (major engine differences; off by default)
| ABR key | Reason for skipping |
|--------|----------|
| `useTexture` + `patt` section | Krita's texture engine differs. The `patt` data could be saved as a Krita pattern, but texture mapping is complex |
| `dualBrush` | Krita uses a masking-brush mechanism with different semantics |
| `useColorDynamics` (`H` / `Strt` / `Brgh` / `purity`) | The two applications use substantially different color-dynamics models |
| `useScatter` | Krita supports spacing-based scattering that could be approximated, but it is off by default |
| Procedural brushes (no bitmap) | **See decision 3** |

## 2. Four Decisions Awaiting Confirmation

1. **How should diameter `Dmtr` be handled?** (This affects the brush's actual rendered size in Krita.)
2. **How far should dynamic mapping go?**
3. **How should the six procedural brushes (round soft, round hard, technical pen, and three airbrushes) be handled?**
4. **What should the delivery format be?**

(See the options in the chat.)
