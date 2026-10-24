"""Mimir's record client (`~/.mind/mimir`, stdlib only): Odin reads the other parts' records through it."""
import sys
from pathlib import Path

try:
    import mimirrecords as records  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path.home() / ".mind" / "mimir"))
    import mimirrecords as records  # noqa: F401
