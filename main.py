import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.bpp.decky_adapter import Plugin

__all__ = ["Plugin"]
