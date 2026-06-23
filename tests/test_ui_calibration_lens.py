"""Tests for feat-022 GUI lens model selection.

Covers the lens_model validation helper used when loading persisted
board settings. The helper is static so it can be tested without
instantiating the Qt widget.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))

from ui_calibration import CalibrationWidget


def test_validate_lens_model_valid_passthrough():
    assert CalibrationWidget._validate_lens_model("normal") == "normal"
    assert CalibrationWidget._validate_lens_model("wide") == "wide"


def test_validate_lens_model_missing_defaults_normal():
    # Old board_settings.json has no lens_model key, so
    # data.get("lens_model") returns None and falls back to the
    # default "normal".
    assert CalibrationWidget._validate_lens_model(None) == "normal"


def test_validate_lens_model_invalid_defaults_normal():
    assert CalibrationWidget._validate_lens_model("fisheye") == "normal"
    assert CalibrationWidget._validate_lens_model("") == "normal"
    assert CalibrationWidget._validate_lens_model(123) == "normal"
