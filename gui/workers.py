"""GUI background threads: parse ABR and run conversion, to avoid blocking the UI."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from brush_converter.abr import AbrFile
from brush_converter.mapping import BrushPreset, map_presets
from brush_converter.convert import convert_presets, ConvertResult


class ParseWorker(QThread):
    """Parse ABR file in the background."""

    done = Signal(object, object)   # (abr, presets) or (None, error message string)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        """Thread body: parse ABR + map presets; exceptions reported via done signal."""
        try:
            abr = AbrFile.parse(self._path)
            presets = map_presets(abr)
            self.done.emit(abr, presets)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.done.emit(None, f"Parse failed: {e}")


class ConvertWorker(QThread):
    """Convert selected presets in the background."""

    done = Signal(object)    # ConvertResult or error message string

    def __init__(self, abr: AbrFile, presets: list[BrushPreset], out_dir: str,
                 make_bundle: bool, make_standalone: bool, parent=None):
        super().__init__(parent)
        self._abr = abr
        self._presets = presets
        self._out_dir = out_dir
        self._make_bundle = make_bundle
        self._make_standalone = make_standalone

    def run(self) -> None:
        """Thread body: convert selected presets; exceptions reported via done signal."""
        try:
            result = convert_presets(
                self._abr, self._presets, self._out_dir,
                make_bundle=self._make_bundle,
                make_standalone=self._make_standalone,
            )
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.done.emit(f"Conversion failed: {e}")
