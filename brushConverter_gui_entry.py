"""brushConverter GUI packaging entry (for PyInstaller).

Directly calls gui.main_window.main, avoiding the dev-time sys.path hack in
gui/__main__.py (running `python -m gui` still uses __main__.py).
"""
from gui.main_window import main

if __name__ == "__main__":
    raise SystemExit(main())
