"""brush_converter command-line entry point.

Usage:
    python cli.py info <file.abr>
    python cli.py extract <file.abr> -o output_dir [--contact-sheet]
    python cli.py convert <file.abr> -o output_dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "src"))

from brush_converter.abr import AbrFile  # noqa: E402
from brush_converter.convert import convert  # noqa: E402


def cmd_gui(args: argparse.Namespace) -> int:
    """Start the PySide6 graphical interface."""
    sys.path.insert(0, str(Path(__file__).parent / "gui"))
    from gui.main_window import main
    return main()


def cmd_convert(args: argparse.Namespace) -> int:
    """Convert .abr to Krita presets (.kpp) or resource bundle (.bundle)."""
    result = convert(args.file, args.output,
                     make_bundle=not args.no_bundle,
                     make_standalone=not args.no_standalone)
    print(f"Conversion complete: {len(result.kpp_files)} presets")
    for fname, _ in result.kpp_files:
        print(f"  - {fname}")
    if result.bundle_path:
        print(f"Bundle: {result.bundle_path}")
    if result.skipped:
        print("Skipped:")
        for s in result.skipped:
            print(f"  - {s}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Print ABR file version, sections and brush tip summary."""
    abr = AbrFile.parse(args.file)
    print(abr.summary())
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Export sampled brush tips as PNG (with info.json, optional contact sheet)."""
    abr = AbrFile.parse(args.file)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.file).stem

    manifest = []
    for tip in abr.tips:
        safe_name = (tip.uuid or tip.name or f"tip{tip.index:03d}").replace("/", "_")
        png_path = out_dir / f"{stem}_{tip.index:02d}_{safe_name}.png"
        img = Image.fromarray(tip.gray, mode="L")
        img.save(png_path)
        manifest.append({
            "index": tip.index,
            "file": png_path.name,
            "width": tip.width,
            "height": tip.height,
            "depth_bits": tip.depth_bits,
            "uuid": tip.uuid,
            "name": tip.name,
            "source_offset": tip.source_offset,
        })

    info = {
        "source": str(args.file),
        "version": f"{abr.version}.{abr.subversion}",
        "sections": {k: s.length for k, s in abr.sections.items()},
        "tip_count": len(abr.tips),
        "tips": manifest,
    }
    (out_dir / f"{stem}_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.contact_sheet and abr.tips:
        _contact_sheet(abr, out_dir / f"{stem}_preview.png")

    print(f"Exported {len(abr.tips)} brush tips to {out_dir}")
    return 0


def _contact_sheet(abr: AbrFile, path: Path, cell: int = 160, cols: int = 6) -> None:
    """Generate brush tip contact sheet (black background, white brush, for visual inspection)."""
    tips = abr.tips
    rows = (len(tips) + cols - 1) // cols
    sheet = Image.new("L", (cols * cell, rows * cell), 20)
    for i, tip in enumerate(tips):
        img = Image.fromarray(tip.gray, mode="L")
        img.thumbnail((cell - 8, cell - 8))
        x = (i % cols) * cell + (cell - img.width) // 2
        y = (i // cols) * cell + (cell - img.height) // 2
        sheet.paste(img, (x, y))
    sheet.save(path)


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser: info / extract / convert / gui subcommands."""
    parser = argparse.ArgumentParser(prog="brush_converter", description="ABR brush converter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="View ABR file summary")
    p_info.add_argument("file")
    p_info.set_defaults(func=cmd_info)

    p_ext = sub.add_parser("extract", help="Extract sampled brush tips as PNG")
    p_ext.add_argument("file")
    p_ext.add_argument("-o", "--output", default="extracted")
    p_ext.add_argument("--contact-sheet", action="store_true", help="Also generate contact sheet")
    p_ext.set_defaults(func=cmd_extract)

    p_conv = sub.add_parser("convert", help="Convert to Krita presets/resource bundle")
    p_conv.add_argument("file")
    p_conv.add_argument("-o", "--output", default="converted")
    p_conv.add_argument("--no-bundle", action="store_true", help="Do not generate .bundle")
    p_conv.add_argument("--no-standalone", action="store_true", help="Do not generate standalone .kpp")
    p_conv.set_defaults(func=cmd_convert)

    p_gui = sub.add_parser("gui", help="Start graphical interface")
    p_gui.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI main entry point: dispatch to subcommands, catch parse/IO errors and return exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())