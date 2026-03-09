"""Shared fixtures for SynchroCap tests."""

import sys
from pathlib import Path

# Add src/synchroCap to sys.path so that modules can be imported directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))
