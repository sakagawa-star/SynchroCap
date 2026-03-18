"""Persistent storage for calibration board settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class BoardSettingsStore:
    """Persistent storage for board settings.

    Follows the same design pattern as CameraSettingsStore
    (ui_camera_settings.py L38-96).
    """

    def __init__(self, path: str) -> None:
        """Initialize.

        Args:
            path: Full path to the JSON settings file.
        """
        self._path = Path(path)

    def load(self) -> Optional[dict]:
        """Load board settings from JSON file.

        Returns:
            Dict with board settings keys, or None if file
            does not exist or cannot be parsed.
        """
        if not self._path.exists():
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("board_settings.json: root is not an object")
            return None
        except Exception as e:
            logger.warning("Failed to load board settings: %s", e)
            return None

    def save(self, settings: dict) -> bool:
        """Save board settings to JSON file.

        Args:
            settings: Dict with board_type, cols, rows, square_mm, marker_mm.

        Returns:
            True if saved successfully, False otherwise.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=True, indent=2)
            logger.info("Board settings saved: %s", self._path)
            return True
        except Exception as e:
            logger.warning("Failed to save board settings: %s", e)
            return False
