"""Tests for board_settings_store.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "synchroCap"))

from board_settings_store import BoardSettingsStore


SAMPLE_SETTINGS = {
    "board_type": "charuco",
    "cols": 5,
    "rows": 7,
    "square_mm": 30.0,
    "marker_mm": 22.0,
}


class TestSaveLoad:
    """Tests for save/load round-trip."""

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "board_settings.json")
        store = BoardSettingsStore(path)

        assert store.save(SAMPLE_SETTINGS) is True
        loaded = store.load()

        assert loaded is not None
        assert loaded["board_type"] == "charuco"
        assert loaded["cols"] == 5
        assert loaded["rows"] == 7
        assert loaded["square_mm"] == pytest.approx(30.0)
        assert loaded["marker_mm"] == pytest.approx(22.0)

    def test_all_five_keys_preserved(self, tmp_path):
        path = str(tmp_path / "board_settings.json")
        store = BoardSettingsStore(path)

        store.save(SAMPLE_SETTINGS)
        loaded = store.load()

        assert set(loaded.keys()) == {"board_type", "cols", "rows", "square_mm", "marker_mm"}

    def test_checkerboard_type(self, tmp_path):
        path = str(tmp_path / "board_settings.json")
        store = BoardSettingsStore(path)

        settings = dict(SAMPLE_SETTINGS, board_type="checkerboard")
        store.save(settings)
        loaded = store.load()

        assert loaded["board_type"] == "checkerboard"


class TestLoadErrors:
    """Tests for load error handling."""

    def test_file_not_exists(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        store = BoardSettingsStore(path)

        assert store.load() is None

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "board_settings.json"
        path.write_text("{invalid json", encoding="utf-8")
        store = BoardSettingsStore(str(path))

        assert store.load() is None

    def test_root_not_object(self, tmp_path):
        path = tmp_path / "board_settings.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        store = BoardSettingsStore(str(path))

        assert store.load() is None


class TestSaveErrors:
    """Tests for save error handling."""

    def test_auto_create_parent_directory(self, tmp_path):
        path = str(tmp_path / "subdir" / "board_settings.json")
        store = BoardSettingsStore(path)

        assert store.save(SAMPLE_SETTINGS) is True
        assert Path(path).exists()

    def test_partial_keys(self, tmp_path):
        """Saving partial keys should store only those keys."""
        path = str(tmp_path / "board_settings.json")
        store = BoardSettingsStore(path)

        partial = {"board_type": "charuco", "cols": 10}
        store.save(partial)
        loaded = store.load()

        assert loaded["board_type"] == "charuco"
        assert loaded["cols"] == 10
        assert "rows" not in loaded

    def test_overwrite_existing(self, tmp_path):
        path = str(tmp_path / "board_settings.json")
        store = BoardSettingsStore(path)

        store.save(SAMPLE_SETTINGS)
        updated = dict(SAMPLE_SETTINGS, cols=10, rows=12)
        store.save(updated)
        loaded = store.load()

        assert loaded["cols"] == 10
        assert loaded["rows"] == 12
