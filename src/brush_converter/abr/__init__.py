"""ABR (Photoshop brush) reading subpackage.

Layout and algorithm reference the official GIMP implementation
app/core/gimpbrush-load.c (GPL), independently rewritten in Python.
"""

from .patterns import PatternTexture, parse_patterns
from .reader import AbrFile
from .samples import BrushTip

__all__ = ["AbrFile", "BrushTip", "PatternTexture", "parse_patterns"]
