from __future__ import annotations

from dataclasses import dataclass
from typing import List

import imagingcontrol4 as ic4
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from channel_registry import ChannelRegistry
import device_resolver


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLUMNS = [
    "Camera",
    "Resolution",
    "PixelFormat",
    "FPS",
    "Trigger (fps)",
    "AWB",
    "AE",
    "AG",
]

# CameraSettings field names corresponding to COLUMNS[1:]
SETTING_COLUMNS = [
    "resolution",
    "pixel_format",
    "framerate",
    "trigger_interval",
    "auto_white_balance",
    "auto_exposure",
    "auto_gain",
]

COLOR_NG = QColor("#FFCCCC")

# Column widths (index 0 = Camera is Stretch)
COLUMN_WIDTHS = {
    1: 120,   # Resolution
    2: 100,   # PixelFormat
    3: 70,    # FPS
    4: 100,   # Trigger (fps)
    5: 90,    # AWB
    6: 90,    # AE
    7: 90,    # AG
}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class CameraSettings:
    channel_id: int
    serial: str
    resolution: str
    pixel_format: str
    framerate: str
    trigger_interval: str
    auto_white_balance: str
    auto_exposure: str
    auto_gain: str


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class CameraSettingsViewerWidget(QWidget):

    def __init__(
        self,
        registry: ChannelRegistry,
        resolver,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._resolver = resolver
        self._camera_data: List[CameraSettings] = []
        self._create_ui()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._table = QTableWidget(self)
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        for col, width in COLUMN_WIDTHS.items():
            self._table.setColumnWidth(col, width)

        layout.addWidget(self._table)

        self._summary_label = QLabel("", self)
        layout.addWidget(self._summary_label)

        self._message_label = QLabel(
            "No cameras connected. Please assign channels in Channel Manager.",
            self,
        )
        layout.addWidget(self._message_label)
        self._message_label.hide()

    # -----------------------------------------------------------------------
    # Public
    # -----------------------------------------------------------------------

    def refresh(self) -> None:
        """Fetch settings from all assigned cameras and update the table."""
        print("[viewer] refresh start")
        data = self._fetch_all_camera_settings()
        self._camera_data = data

        if not data:
            self._table.setRowCount(0)
            self._summary_label.setText("")
            self._message_label.show()
            return

        self._message_label.hide()
        consistency = self._check_consistency(data)
        self._update_table(data, consistency)

        all_ok = all(consistency.values())
        verdict = "OK" if all_ok else "NG"
        self._summary_label.setText(f"All Settings Match: {verdict}")
        print(f"[viewer] refresh done – {len(data)} cameras, {verdict}")

    # -----------------------------------------------------------------------
    # Data fetch
    # -----------------------------------------------------------------------

    def _fetch_all_camera_settings(self) -> List[CameraSettings]:
        entries = self._registry.list_channels()
        results: List[CameraSettings] = []
        for entry in entries:
            settings = self._fetch_single_camera(entry)
            if settings is not None:
                results.append(settings)
        return results

    def _fetch_single_camera(self, entry) -> CameraSettings | None:
        device_info = self._resolver.find_device_for_entry(entry)
        if device_info is None:
            print(f"[viewer] Ch-{entry.channel_id:02d}: device not found, skipping")
            return None

        grabber = ic4.Grabber()
        try:
            grabber.device_open(device_info)
        except ic4.IC4Exception as exc:
            print(f"[viewer] Ch-{entry.channel_id:02d}: device_open failed: {exc}")
            return None

        try:
            prop_map = grabber.device_property_map
            props = self._read_properties(prop_map)
        except Exception as exc:
            print(f"[viewer] Ch-{entry.channel_id:02d}: read_properties failed: {exc}")
            props = {col: "N/A" for col in SETTING_COLUMNS}
        finally:
            try:
                grabber.device_close()
            except Exception:
                pass

        serial = (entry.device_identity.serial or "").strip()
        return CameraSettings(
            channel_id=entry.channel_id,
            serial=serial,
            **props,
        )

    def _read_properties(self, prop_map) -> dict[str, str]:
        result: dict[str, str] = {}

        # Resolution
        result["resolution"] = self._read_resolution(prop_map)

        # PixelFormat
        result["pixel_format"] = self._read_str_prop(
            prop_map, "PIXEL_FORMAT", None
        )

        # Framerate
        result["framerate"] = self._read_framerate(prop_map)

        # Trigger Interval (μs → fps)
        result["trigger_interval"] = self._read_trigger_interval(prop_map)

        # Auto White Balance
        result["auto_white_balance"] = self._read_str_prop(
            prop_map, "BALANCE_WHITE_AUTO", "BalanceWhiteAuto"
        )

        # Auto Exposure
        result["auto_exposure"] = self._read_str_prop(
            prop_map, "EXPOSURE_AUTO", "ExposureAuto"
        )

        # Auto Gain
        result["auto_gain"] = self._read_str_prop(
            prop_map, "GAIN_AUTO", "GainAuto"
        )

        return result

    def _read_resolution(self, prop_map) -> str:
        width_id = getattr(ic4.PropId, "WIDTH", None)
        height_id = getattr(ic4.PropId, "HEIGHT", None)
        if width_id is None or height_id is None:
            return "N/A"
        try:
            w = int(prop_map.get_value_int(width_id))
            h = int(prop_map.get_value_int(height_id))
            return f"{w}x{h}"
        except (ic4.IC4Exception, AttributeError, TypeError, ValueError):
            return "N/A"

    def _read_framerate(self, prop_map) -> str:
        prop_id = getattr(ic4.PropId, "ACQUISITION_FRAME_RATE", None)
        if prop_id is None:
            return "N/A"
        try:
            value = prop_map.get_value_float(prop_id)
            return f"{value:.1f}"
        except (ic4.IC4Exception, AttributeError, TypeError, ValueError):
            return "N/A"

    def _read_trigger_interval(self, prop_map) -> str:
        # Try PropId first
        prop_id = getattr(ic4.PropId, "ACTION_SCHEDULER_INTERVAL", None)
        value = None
        if prop_id is not None:
            try:
                value = prop_map.get_value_int(prop_id)
            except (ic4.IC4Exception, AttributeError, TypeError, ValueError):
                value = None

        # Fallback: string key
        if value is None:
            try:
                value = prop_map.get_value_int("ActionSchedulerInterval")
            except Exception:
                return "N/A"

        if value is None or value == 0:
            return "N/A"

        fps = 1_000_000 / value
        return f"{fps:.1f}"

    def _read_str_prop(
        self, prop_map, prop_id_name: str, fallback_key: str | None
    ) -> str:
        prop_id = getattr(ic4.PropId, prop_id_name, None)
        value = None
        if prop_id is not None:
            try:
                value = prop_map.get_value_str(prop_id)
            except (ic4.IC4Exception, AttributeError, TypeError, ValueError):
                value = None

        if value is None and fallback_key is not None:
            try:
                value = prop_map.get_value_str(fallback_key)
            except Exception:
                value = None

        return value if value is not None else "N/A"

    # -----------------------------------------------------------------------
    # Consistency check
    # -----------------------------------------------------------------------

    def _check_consistency(self, data: List[CameraSettings]) -> dict[str, bool]:
        if len(data) <= 1:
            return {col: True for col in SETTING_COLUMNS}

        result: dict[str, bool] = {}
        for col in SETTING_COLUMNS:
            values = [getattr(cam, col) for cam in data]
            result[col] = len(set(values)) == 1
        return result

    # -----------------------------------------------------------------------
    # Table update & highlighting
    # -----------------------------------------------------------------------

    def _update_table(
        self, data: List[CameraSettings], consistency: dict[str, bool]
    ) -> None:
        num_cameras = len(data)
        # rows = camera rows + 1 Match row
        self._table.setRowCount(num_cameras + 1)

        # Camera rows
        for row, cam in enumerate(data):
            camera_label = f"Ch-{cam.channel_id:02d} ({cam.serial})"
            self._set_cell(row, 0, camera_label)

            for col_idx, field in enumerate(SETTING_COLUMNS, start=1):
                value = getattr(cam, field)
                self._set_cell(row, col_idx, value)

        # Match row
        match_row = num_cameras
        self._set_cell(match_row, 0, "Match")
        match_item = self._table.item(match_row, 0)
        if match_item:
            font = match_item.font()
            font.setBold(True)
            match_item.setFont(font)

        for col_idx, field in enumerate(SETTING_COLUMNS, start=1):
            is_match = consistency[field]
            text = "OK" if is_match else "NG"
            self._set_cell(match_row, col_idx, text)

            # Highlight Match row cell
            self._apply_cell_highlight(match_row, col_idx, is_match)

            # Highlight camera rows for NG columns
            if not is_match:
                for cam_row in range(num_cameras):
                    self._apply_cell_highlight(cam_row, col_idx, False)

        # Center-align all cells
        for row in range(self._table.rowCount()):
            for col in range(1, self._table.columnCount()):
                item = self._table.item(row, col)
                if item:
                    item.setTextAlignment(Qt.AlignCenter)

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        self._table.setItem(row, col, item)

    def _apply_cell_highlight(
        self, row: int, col: int, is_match: bool
    ) -> None:
        item = self._table.item(row, col)
        if item is None:
            return
        if not is_match:
            item.setBackground(COLOR_NG)
