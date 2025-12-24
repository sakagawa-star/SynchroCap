from __future__ import annotations

from typing import List, Optional
import time
from threading import Lock

import imagingcontrol4 as ic4
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from channel_registry import ChannelEntry, ChannelRegistry


class CameraSettingsWidget(QWidget):
    def __init__(self, registry: ChannelRegistry, resolver, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.resolver = resolver

        self.preview_grabber = ic4.Grabber()
        self.display = None
        self.preview_listener = None
        self.preview_sink = None
        self._channel_entries: List[ChannelEntry] = []
        self._active_entry: Optional[ChannelEntry] = None
        self._updating_controls = False
        self._controls_enabled = False
        self._resolution_entries: List[tuple[str, object]] = []
        self._pixel_format_entries: List[tuple[str, object]] = []
        self._current_resolution: Optional[object] = None
        self._current_pixel_format: Optional[object] = None
        self._current_frame_rate: Optional[float] = None
        self._awb_prop = None
        self._awb_prop_key = None
        self._awb_notify_registered = False
        self._awb_polling_fallback = False
        self._awb_last_value = None
        self._awb_supported = False
        self._awb_display_text = "N/A"
        self._wb_selector_key = None
        self._wb_ratio_key = None
        self._wb_selector_entries = {}
        self._wb_selector_use_entries = False
        self._wb_supported = False
        self._wb_last_values = None
        self._wb_display_text = "N/A"
        self._wb_timer = QTimer(self)
        self._wb_timer.setInterval(1000)
        self._wb_timer.timeout.connect(self._on_wb_timer)
        self._resolution_error_text = None
        self._dbg_counter = 0
        self._frame_lock = Lock()
        self._frame_count = 0
        self._last_fps_time: Optional[float] = None
        self._last_fps_count = 0
        self._fixed_resolutions = [(1920, 1200), (1920, 1080)]
        self._fixed_pixel_formats = self._build_fixed_pixel_formats()

        class PreviewListener(ic4.QueueSinkListener):
            def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
                sink.alloc_and_queue_buffers(min_buffers_required + 2)
                return True

            def sink_disconnected(self, sink: ic4.QueueSink):
                pass

            def frames_queued(listener, sink: ic4.QueueSink):
                sink.pop_output_buffer()
                if hasattr(listener, "owner"):
                    listener.owner._on_preview_frame()

        self.preview_listener = PreviewListener()
        self.preview_listener.owner = self
        self.preview_sink = ic4.QueueSink(self.preview_listener)

        self._build_ui()
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self._update_measured_fps)
        self.fps_timer.start(1000)
        self.refresh_channels()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Channel", self))
        self.channel_combo = QComboBox(self)
        self.channel_combo.currentIndexChanged.connect(self.on_channel_changed)
        top_layout.addWidget(self.channel_combo, 1)
        main_layout.addLayout(top_layout)

        self.status_label = QLabel("", self)
        main_layout.addWidget(self.status_label)

        self.empty_label = QLabel("チャンネル管理で登録してください", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.empty_label)

        self.preview_widget = ic4.pyside6.DisplayWidget()
        self.preview_widget.setMinimumSize(640, 480)
        try:
            self.display = self.preview_widget.as_display()
            self.display.set_render_position(ic4.DisplayRenderPosition.STRETCH_CENTER)
        except Exception:
            self.display = None

        self.disconnected_label = QLabel("", self)
        self.disconnected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disconnected_label.setWordWrap(True)

        self.preview_stack = QStackedLayout()
        self.preview_stack.addWidget(self.preview_widget)
        self.preview_stack.addWidget(self.disconnected_label)

        preview_container = QWidget(self)
        preview_container.setLayout(self.preview_stack)

        self.settings_group = QGroupBox("Frequent Settings", self)
        settings_layout = QFormLayout(self.settings_group)

        self.resolution_button = QPushButton("Not supported", self.settings_group)
        self.resolution_button.clicked.connect(self._on_change_resolution_clicked)
        settings_layout.addRow("Resolution", self.resolution_button)

        self.pixel_format_button = QPushButton("Not supported", self.settings_group)
        self.pixel_format_button.clicked.connect(self._on_change_pixel_format_clicked)
        settings_layout.addRow("PixelFormat", self.pixel_format_button)

        self.frame_rate_button = QPushButton("Not supported", self.settings_group)
        self.frame_rate_button.clicked.connect(self._on_change_frame_rate_clicked)
        settings_layout.addRow("FrameRate (fps)", self.frame_rate_button)

        self.awb_status_label = QLabel("Auto White Balance: N/A", self.settings_group)
        self.awb_change_button = QPushButton("Change...", self.settings_group)
        self.awb_change_button.clicked.connect(self._on_change_awb_clicked)
        self.awb_once_button = QPushButton("Run Once", self.settings_group)
        self.awb_once_button.clicked.connect(self._on_run_awb_once_clicked)
        settings_layout.addRow(self.awb_status_label)
        settings_layout.addRow(self.awb_change_button)
        settings_layout.addRow(self.awb_once_button)

        self.wb_status_label = QLabel("WB (RGB): N/A", self.settings_group)
        settings_layout.addRow(self.wb_status_label)

        self.advanced_button = QPushButton("Advanced...", self.settings_group)
        self.advanced_button.clicked.connect(self.on_advanced)
        settings_layout.addRow(self.advanced_button)

        content_layout = QHBoxLayout()
        content_layout.addWidget(preview_container, 2)
        content_layout.addWidget(self.settings_group, 1)
        main_layout.addLayout(content_layout, 1)

        self.measured_fps_label = QLabel("Measured FPS: --", self)
        self.measured_fps_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.measured_fps_label)

        self.frames_label = QLabel("Frames: --", self)
        self.frames_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.frames_label)

    def refresh_channels(self) -> None:
        self._channel_entries = self.registry.list_channels()
        self._active_entry = None
        self._stop_preview()

        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()

        if not self._channel_entries:
            self.channel_combo.setEnabled(False)
            self.empty_label.setVisible(True)
            self._show_disconnected(None)
            self._set_controls_enabled(False)
            self.channel_combo.blockSignals(False)
            return

        self.channel_combo.setEnabled(True)
        self.empty_label.setVisible(False)

        statuses = {}
        try:
            statuses = self.resolver.resolve_status(self._channel_entries)
        except Exception:
            statuses = {}

        for entry in self._channel_entries:
            connected = statuses.get(entry.channel_id, False)
            self.channel_combo.addItem(self._format_entry(entry, connected))

        self.channel_combo.blockSignals(False)
        self.channel_combo.setCurrentIndex(0)
        self.on_channel_changed(0)

    def on_channel_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._channel_entries):
            self._active_entry = None
            self._show_disconnected(None)
            return

        entry = self._channel_entries[index]
        self._active_entry = entry
        self._stop_preview()

        device_info = self.resolver.find_device_for_entry(entry)
        if device_info is None:
            self._show_disconnected(entry)
            return

        try:
            self._dbg_log("CHANGED_CHANNEL", "device_open begin", device_info)
            self.preview_grabber.device_open(device_info)
            self._dbg_log("CHANGED_CHANNEL", "device_open ok", device_info)
            if self.display is not None:
                self._dbg_log("CHANGED_CHANNEL", "stream_setup begin", device_info)
                self.preview_grabber.stream_setup(self.preview_sink, self.display)
                self._dbg_log("CHANGED_CHANNEL", "stream_setup ok", device_info)
            else:
                self._dbg_log("CHANGED_CHANNEL", "stream_setup begin", device_info)
                self.preview_grabber.stream_setup(self.preview_sink)
                self._dbg_log("CHANGED_CHANNEL", "stream_setup ok", device_info)
            self.status_label.setText(f"Status: Connected")
            self.preview_stack.setCurrentWidget(self.preview_widget)
            self._load_settings_from_device()
        except ic4.IC4Exception as exc:
            self._dbg_log("CHANGED_CHANNEL", f"EXC {type(exc).__name__}: {exc}", device_info)
            self._show_disconnected(entry)

    def _stop_preview(self) -> None:
        try:
            if self.preview_grabber.is_streaming:
                self._dbg_log("STOP_PREVIEW", "stream_stop begin")
                self.preview_grabber.stream_stop()
                self._dbg_log("STOP_PREVIEW", "stream_stop ok")
        except ic4.IC4Exception as exc:
            self._dbg_log("STOP_PREVIEW", f"stream_stop EXC {type(exc).__name__}: {exc}")
            pass

        try:
            if self.preview_grabber.is_device_valid:
                self._dbg_log("STOP_PREVIEW", "device_close begin")
                self.preview_grabber.device_close()
                self._dbg_log("STOP_PREVIEW", "device_close ok")
        except ic4.IC4Exception as exc:
            self._dbg_log("STOP_PREVIEW", f"device_close EXC {type(exc).__name__}: {exc}")
            pass

        if self.display is not None:
            try:
                self.display.display_buffer(None)
            except ic4.IC4Exception:
                pass
        self._reset_fps_counters()
        self._reset_awb_state()

    def _show_disconnected(self, entry: Optional[ChannelEntry]) -> None:
        self._current_resolution = None
        self._current_pixel_format = None
        self._current_frame_rate = None
        self._resolution_entries = self._build_fixed_resolution_entries()
        self._pixel_format_entries = self._build_fixed_pixel_format_entries()
        self._set_controls_enabled(False)
        self._reset_fps_counters()
        self._reset_awb_state()
        if entry is None:
            self.status_label.setText("Status: Disconnected")
            self.disconnected_label.setText("No registered channel.")
        else:
            self.status_label.setText(f"Status: Disconnected")
            self.disconnected_label.setText(
                f"Channel {entry.channel_label}: Disconnected\nPlease connect the camera."
            )
        if self._resolution_error_text:
            self.status_label.setText(f"Status: Resolution Unsupported (EXC: {self._resolution_error_text})")
        self.preview_stack.setCurrentWidget(self.disconnected_label)

    def _load_settings_from_device(self) -> None:
        self._updating_controls = True
        self._controls_enabled = True

        prop_map = self.preview_grabber.device_property_map

        self._resolution_entries = self._build_fixed_resolution_entries()
        self._current_resolution = self._read_current_resolution(prop_map)
        self._pixel_format_entries = self._build_fixed_pixel_format_entries()
        self._current_pixel_format = self._read_current_pixel_format(prop_map)
        self._setup_awb_property(prop_map)
        self._setup_wb_properties(prop_map)
        self._refresh_awb_state(prop_map, source="LOAD")

        frame_rate_id = getattr(ic4.PropId, "ACQUISITION_FRAME_RATE", None)
        self._current_frame_rate = None
        if frame_rate_id is not None:
            try:
                self._current_frame_rate = prop_map.get_value_float(frame_rate_id)
            except ic4.IC4Exception:
                self._current_frame_rate = None

        self._refresh_frequent_settings_ui()
        self._updating_controls = False

    def _on_preview_frame(self) -> None:
        with self._frame_lock:
            self._frame_count += 1

    def _reset_fps_counters(self) -> None:
        with self._frame_lock:
            self._frame_count = 0
            self._last_fps_count = 0
        self._last_fps_time = None
        self.measured_fps_label.setText("Measured FPS: --")
        self.frames_label.setText("Frames: --")

    def _update_measured_fps(self) -> None:
        if not self._is_connected():
            self._reset_fps_counters()
            return
        try:
            if not self.preview_grabber.is_streaming:
                self._reset_fps_counters()
                return
        except ic4.IC4Exception:
            self._reset_fps_counters()
            return

        now = time.monotonic()
        with self._frame_lock:
            count = self._frame_count

        if self._last_fps_time is None:
            self._last_fps_time = now
            self._last_fps_count = count
            self.frames_label.setText(f"Frames: delivered={count}")
            return

        delta_frames = count - self._last_fps_count
        delta_time = now - self._last_fps_time
        if delta_time <= 0:
            return

        fps = delta_frames / delta_time
        self.measured_fps_label.setText(f"Measured FPS: {fps:.2f}")

        if self._awb_polling_fallback and self._is_connected():
            self._poll_awb_state()

        try:
            stats = self.preview_grabber.stream_statistics
            dropped = (
                stats.device_transmission_error
                + stats.device_underrun
                + stats.transform_underrun
                + stats.sink_underrun
            )
            self.frames_label.setText(f"Frames: delivered={count} dropped={dropped}")
        except ic4.IC4Exception:
            self.frames_label.setText(f"Frames: delivered={count}")

        self._last_fps_time = now
        self._last_fps_count = count

    def _build_fixed_pixel_formats(self) -> List[object]:
        imagetype = getattr(ic4, "imagetype", None)
        pixel_enum = getattr(imagetype, "PixelFormat", None)
        if pixel_enum is None:
            return []

        names = ("BayerGR8", "BayerGR16", "BGR8")
        return [getattr(pixel_enum, name) for name in names if hasattr(pixel_enum, name)]

    def _build_fixed_resolution_entries(self) -> List[tuple[str, object]]:
        return [(f"{width}x{height}", (width, height)) for width, height in self._fixed_resolutions]

    def _build_fixed_pixel_format_entries(self) -> List[tuple[str, object]]:
        return [(getattr(pixel_format, "name", str(pixel_format)), pixel_format) for pixel_format in self._fixed_pixel_formats]

    def _read_current_resolution(self, prop_map: ic4.PropertyMap) -> Optional[tuple[int, int]]:
        width_id = getattr(ic4.PropId, "WIDTH", None)
        height_id = getattr(ic4.PropId, "HEIGHT", None)
        if width_id is None or height_id is None:
            self._set_resolution_error("KeyError: PropId.WIDTH/HEIGHT not found")
            return None

        try:
            width = int(prop_map.get_value_int(width_id))
            height = int(prop_map.get_value_int(height_id))
        except (ic4.IC4Exception, AttributeError, TypeError, ValueError) as exc:
            self._set_resolution_error(f"{type(exc).__name__}: {exc}")
            return None

        if width <= 0 or height <= 0:
            return None
        self._clear_resolution_error()
        return (width, height)

    def _read_current_pixel_format(self, prop_map: ic4.PropertyMap) -> Optional[object]:
        prop_id = getattr(ic4.PropId, "PIXEL_FORMAT", None)
        if prop_id is None:
            return None

        try:
            current_value = prop_map.get_value_str(prop_id)
        except ic4.IC4Exception:
            return None

        for pixel_format in self._fixed_pixel_formats:
            if getattr(pixel_format, "name", None) == current_value:
                return pixel_format
        return None

    def _apply_width_height(
        self,
        prop_map: ic4.PropertyMap,
        width_id,
        height_id,
        width: int,
        height: int,
    ) -> None:
        self._dbg_log("SET_RES", f"try Width={int(width)} Height={int(height)}")
        try:
            prop_map.set_value(width_id, int(width))
            prop_map.set_value(height_id, int(height))
        except Exception as exc:
            self._dbg_log("SET_RES", f"EXC {type(exc).__name__}: {exc}")
            self._set_resolution_error(f"{type(exc).__name__}: {exc}")
            raise
        self._dbg_log("SET_RES", "ok")

    def _refresh_frequent_settings_ui(self) -> None:
        self._set_enum_button_state(
            self.resolution_button,
            self._resolution_entries,
            self._current_resolution,
            "Resolution not supported",
        )
        self._set_enum_button_state(
            self.pixel_format_button,
            self._pixel_format_entries,
            self._current_pixel_format,
            "PixelFormat not supported",
        )

        if self._current_frame_rate is None:
            self.frame_rate_button.setText("Not supported")
            self.frame_rate_button.setToolTip("FrameRate not supported")
            self.frame_rate_button.setEnabled(False)
        else:
            self.frame_rate_button.setText(f"{self._current_frame_rate:.2f}")
            self.frame_rate_button.setToolTip("")
            self.frame_rate_button.setEnabled(self._controls_enabled)

        self._apply_awb_ui()
        self._apply_wb_ui()
        self.advanced_button.setEnabled(False)

    def _set_enum_button_state(
        self,
        button: QPushButton,
        entries: List[tuple[str, object]],
        current_value: Optional[object],
        not_supported_label: str,
    ) -> None:
        if not entries:
            # Not supported when fixed candidates are unavailable.
            button.setText("Not supported")
            button.setToolTip(not_supported_label)
            button.setEnabled(False)
            return

        label = self._label_for_value(entries, current_value)
        if not label:
            label = "Unsupported"
        button.setText(label)
        button.setToolTip("")
        button.setEnabled(self._controls_enabled)

    @staticmethod
    def _label_for_value(entries: List[tuple[str, object]], value: Optional[object]) -> str:
        if value is None:
            return ""
        for label, entry_value in entries:
            if entry_value == value:
                return label
            try:
                if label == str(value):
                    return label
            except Exception:
                continue
        return ""

    def _log_awb(self, message: str) -> None:
        print(f"[AutoWhiteBalance] {message}")

    def _log_awb_exception(self, prefix: str, exc: Exception) -> None:
        self._log_awb(f"{prefix} EXC: {type(exc).__name__} {exc}")

    def _dbg_log(self, tag: str, message: str, device_info: Optional[object] = None) -> None:
        self._dbg_counter += 1
        timestamp = time.monotonic()
        valid = "?"
        streaming = "?"
        try:
            valid = self.preview_grabber.is_device_valid
        except ic4.IC4Exception:
            pass
        try:
            streaming = self.preview_grabber.is_streaming
        except ic4.IC4Exception:
            pass
        device_text = self._format_dbg_device(device_info)
        print(
            f"[DBG][{tag}][{self._dbg_counter}][t={timestamp:.3f}] "
            f"{message} {device_text} valid={valid} streaming={streaming}"
        )

    def _format_dbg_device(self, device_info: Optional[object]) -> str:
        if device_info is not None:
            model = getattr(device_info, "model_name", "") or getattr(device_info, "model", "")
            serial = getattr(device_info, "serial", "")
        elif self._active_entry is not None:
            model = self._active_entry.device_identity.model
            serial = self._active_entry.device_identity.serial
        else:
            model = ""
            serial = ""
        if model or serial:
            return f"device={model} {serial}".strip()
        return "device=?"

    def _set_resolution_error(self, reason: str) -> None:
        self._resolution_error_text = reason
        self.status_label.setText(f"Status: Resolution Unsupported (EXC: {reason})")

    def _clear_resolution_error(self) -> None:
        self._resolution_error_text = None

    def _log_wb(self, message: str) -> None:
        print(f"[WB(RGB)] {message}")

    def _log_wb_exception(self, prefix: str, exc: Exception) -> None:
        self._log_wb(f"{prefix} EXC: {type(exc).__name__} {exc}")

    def _reset_awb_state(self) -> None:
        self._awb_prop = None
        self._awb_prop_key = None
        self._awb_notify_registered = False
        self._awb_polling_fallback = False
        self._awb_last_value = None
        self._awb_supported = False
        self._awb_display_text = "N/A"
        self._apply_awb_ui()
        self._reset_wb_state()

    def _setup_awb_property(self, prop_map: ic4.PropertyMap) -> None:
        self._awb_prop = None
        self._awb_prop_key = None
        self._awb_supported = False
        self._awb_notify_registered = False
        self._awb_polling_fallback = True

        prop_id = getattr(ic4.PropId, "BALANCE_WHITE_AUTO", None)
        if prop_id is not None:
            try:
                self._awb_prop = prop_map.find(prop_id)
                self._awb_prop_key = prop_id
            except Exception as exc:
                self._log_awb_exception("find BALANCE_WHITE_AUTO", exc)
                self._awb_prop = None
                self._awb_prop_key = None

        if self._awb_prop is None:
            try:
                self._awb_prop = prop_map.find("BalanceWhiteAuto")
                self._awb_prop_key = "BalanceWhiteAuto"
            except Exception as exc:
                self._log_awb_exception("find BalanceWhiteAuto", exc)
                self._awb_prop = None
                self._awb_prop_key = None

        self._awb_supported = self._awb_prop is not None and self._awb_prop_key is not None
        if not self._awb_supported:
            self._awb_display_text = "N/A"
            self._awb_polling_fallback = False
            return

        if hasattr(self._awb_prop, "event_add_notification"):
            try:
                self._awb_prop.event_add_notification(self._on_awb_notification)
                self._awb_notify_registered = True
                self._awb_polling_fallback = False
                self._log_awb("notification registered")
            except Exception as exc:
                self._log_awb_exception("notification", exc)
                self._awb_polling_fallback = True
        else:
            self._log_awb("notification not available")

    def _apply_awb_ui(self) -> None:
        text = self._awb_display_text if self._awb_supported else "N/A"
        self.awb_status_label.setText(f"Auto White Balance: {text}")
        enabled = self._awb_supported and self._controls_enabled
        self.awb_change_button.setEnabled(enabled)
        self.awb_once_button.setEnabled(enabled)

    def _refresh_awb_state(self, prop_map: ic4.PropertyMap, source: str) -> None:
        if not self._awb_supported or self._awb_prop_key is None:
            self._awb_display_text = "N/A"
            self._apply_awb_ui()
            return

        try:
            value = prop_map.get_value_str(self._awb_prop_key)
        except Exception as exc:
            self._log_awb_exception(f"{source} get_value_str", exc)
            self._awb_display_text = "N/A"
            self._apply_awb_ui()
            return

        previous_value = self._awb_last_value
        suffix = " (same)" if value == previous_value else ""
        self._log_awb(f"{source} get_value_str={value}{suffix}")
        self._awb_last_value = value

        if value == "Once":
            display = "Running..."
        elif value in ("Off", "Continuous"):
            display = value
        else:
            display = "N/A"

        self._awb_display_text = display
        self._apply_awb_ui()
        if value != previous_value:
            self._handle_awb_state_change(previous_value, value, prop_map)

    def _poll_awb_state(self) -> None:
        if self.preview_grabber is None or not self.preview_grabber.is_device_valid:
            return
        try:
            prop_map = self.preview_grabber.device_property_map
        except Exception as exc:
            self._log_awb_exception("POLL prop_map", exc)
            return
        self._refresh_awb_state(prop_map, source="POLL")

    def _apply_awb_value(self, value: str, source: str) -> bool:
        if not self._awb_supported:
            return False
        if not self._is_connected():
            return False
        try:
            prop_map = self.preview_grabber.device_property_map
        except Exception as exc:
            self._log_awb_exception(f"{source} prop_map", exc)
            return False

        try:
            prop_map.set_value(self._awb_prop_key, value)
            self._log_awb(f"{source} set_value={value}")
        except Exception as exc:
            self._log_awb_exception(f"{source} set_value", exc)
            return False

        self._refresh_awb_state(prop_map, source=source)
        return True

    def _on_awb_notification(self, prop: ic4.Property) -> None:
        if not self._awb_supported:
            return
        if not self._is_connected():
            return
        try:
            prop_map = self.preview_grabber.device_property_map
        except Exception as exc:
            self._log_awb_exception("NOTIFY prop_map", exc)
            return
        self._refresh_awb_state(prop_map, source="NOTIFY")

    def _handle_awb_state_change(self, previous: Optional[str], current: str, prop_map: ic4.PropertyMap) -> None:
        if current == "Continuous":
            self._start_wb_timer(prop_map, source="WB_CONTINUOUS")
        elif current in ("Off", "Once"):
            self._stop_wb_timer()
        else:
            self._stop_wb_timer()

        if previous == "Once" and current == "Off":
            self._refresh_wb_values(prop_map, source="WB_ONCE_DONE")
        elif current == "Continuous":
            self._refresh_wb_values(prop_map, source="WB_CONTINUOUS")

    def _reset_wb_state(self) -> None:
        self._wb_timer.stop()
        self._wb_selector_key = None
        self._wb_ratio_key = None
        self._wb_selector_entries = {}
        self._wb_selector_use_entries = False
        self._wb_supported = False
        self._wb_last_values = None
        self._wb_display_text = "N/A"
        self._apply_wb_ui()

    def _setup_wb_properties(self, prop_map: ic4.PropertyMap) -> None:
        self._reset_wb_state()
        selector_prop = None

        selector_id = getattr(ic4.PropId, "BALANCE_RATIO_SELECTOR", None)
        if selector_id is not None:
            try:
                selector_prop = prop_map.find(selector_id)
                self._wb_selector_key = selector_id
            except Exception as exc:
                self._log_wb_exception("find BALANCE_RATIO_SELECTOR", exc)
                self._wb_selector_key = None

        if self._wb_selector_key is None:
            try:
                selector_prop = prop_map.find("BalanceRatioSelector")
                self._wb_selector_key = "BalanceRatioSelector"
            except Exception as exc:
                self._log_wb_exception("find BalanceRatioSelector", exc)
                selector_prop = None
                self._wb_selector_key = None

        ratio_id = getattr(ic4.PropId, "BALANCE_RATIO", None)
        if ratio_id is not None:
            try:
                prop_map.find(ratio_id)
                self._wb_ratio_key = ratio_id
            except Exception as exc:
                self._log_wb_exception("find BALANCE_RATIO", exc)
                self._wb_ratio_key = None

        if self._wb_ratio_key is None:
            try:
                prop_map.find("BalanceRatio")
                self._wb_ratio_key = "BalanceRatio"
            except Exception as exc:
                self._log_wb_exception("find BalanceRatio", exc)
                self._wb_ratio_key = None

        if selector_prop is not None and hasattr(selector_prop, "entries"):
            try:
                entries = selector_prop.entries
                for entry in entries:
                    name = getattr(entry, "name", None)
                    value = getattr(entry, "value", None)
                    if name is None or value is None:
                        continue
                    normalized = str(name).strip().lower()
                    if normalized == "red":
                        self._wb_selector_entries["Red"] = value
                    elif normalized == "green":
                        self._wb_selector_entries["Green"] = value
                    elif normalized == "blue":
                        self._wb_selector_entries["Blue"] = value
            except Exception as exc:
                self._log_wb_exception("selector entries", exc)

        self._wb_supported = self._wb_selector_key is not None and self._wb_ratio_key is not None
        if not self._wb_supported:
            self._wb_display_text = "N/A"
            self._apply_wb_ui()

    def _apply_wb_ui(self) -> None:
        self.wb_status_label.setText(f"WB (RGB): {self._wb_display_text}")

    def _start_wb_timer(self, prop_map: ic4.PropertyMap, source: str) -> None:
        if not self._wb_supported:
            return
        if not self._wb_timer.isActive():
            self._wb_timer.start()
        self._refresh_wb_values(prop_map, source=source)

    def _stop_wb_timer(self) -> None:
        if self._wb_timer.isActive():
            self._wb_timer.stop()

    def _on_wb_timer(self) -> None:
        if not self._is_connected():
            return
        try:
            prop_map = self.preview_grabber.device_property_map
        except Exception as exc:
            self._log_wb_exception("WB_TIMER prop_map", exc)
            return
        self._refresh_wb_values(prop_map, source="WB_TIMER")

    def _refresh_wb_values(self, prop_map: ic4.PropertyMap, source: str) -> None:
        if not self._wb_supported:
            return
        values = []
        for channel in ("Red", "Green", "Blue"):
            value = self._read_wb_channel(prop_map, channel, source)
            if value is None:
                self._wb_display_text = "N/A"
                self._apply_wb_ui()
                return
            values.append(value)

        value_tuple = tuple(values)
        r_value, g_value, b_value = value_tuple
        display = f"R={r_value:.3f} G={g_value:.3f} B={b_value:.3f}"
        if value_tuple != self._wb_last_values:
            self._log_wb(f"{source} {display}")
            self._wb_last_values = value_tuple
        self._wb_display_text = display
        self._apply_wb_ui()

    def _read_wb_channel(self, prop_map: ic4.PropertyMap, channel: str, source: str) -> Optional[float]:
        if self._wb_selector_key is None or self._wb_ratio_key is None:
            return None

        if not self._wb_selector_use_entries:
            try:
                prop_map.set_value(self._wb_selector_key, channel)
                return float(prop_map.get_value_float(self._wb_ratio_key))
            except Exception as exc:
                self._log_wb_exception(f"{source} select {channel}", exc)
                self._wb_selector_use_entries = True

        entry_value = self._wb_selector_entries.get(channel)
        if entry_value is None:
            self._log_wb(f"{source} selector entry missing for {channel}")
            return None
        try:
            prop_map.set_value(self._wb_selector_key, entry_value)
            return float(prop_map.get_value_float(self._wb_ratio_key))
        except Exception as exc:
            self._log_wb_exception(f"{source} select entry {channel}", exc)
            return None

    def _select_entry_dialog(
        self,
        title: str,
        entries: List[tuple[str, object]],
        current_value: Optional[object],
    ) -> Optional[object]:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        layout = QVBoxLayout(dlg)

        list_widget = QListWidget(dlg)
        current_item = None
        for label, value in entries:
            item = QListWidgetItem(label, list_widget)
            item.setData(Qt.ItemDataRole.UserRole, value)
            if value == current_value or label == current_value or label == str(current_value):
                current_item = item
        if current_item is not None:
            list_widget.setCurrentItem(current_item)
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        selected_item = list_widget.currentItem()
        if selected_item is None:
            return None

        return selected_item.data(Qt.ItemDataRole.UserRole)

    def _prompt_frame_rate(self, current_value: float) -> Optional[float]:
        dlg = QDialog(self)
        dlg.setWindowTitle("Set FrameRate")
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("FrameRate (fps)", dlg))
        line_edit = QLineEdit(dlg)
        validator = QDoubleValidator(0.0, 1000.0, 2, line_edit)
        validator.setNotation(QDoubleValidator.StandardNotation)
        line_edit.setValidator(validator)
        line_edit.setText(f"{current_value:.2f}")
        layout.addWidget(line_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(line_edit.text()))
        line_edit.textChanged.connect(lambda text: ok_button.setEnabled(bool(text)))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        try:
            value = float(line_edit.text())
        except ValueError:
            return None

        if value <= 0:
            QMessageBox.warning(self, "", "FrameRate must be greater than 0.", QMessageBox.StandardButton.Ok)
            return None

        return value

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._controls_enabled = enabled
        self._refresh_frequent_settings_ui()

    def _on_change_awb_clicked(self) -> None:
        if self._updating_controls or not self._controls_enabled:
            return
        if not self._awb_supported:
            return
        if not self._is_connected():
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Auto White Balance")
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("Select mode (applies immediately):", dlg))
        button_group = QButtonGroup(dlg)
        off_radio = QRadioButton("Off", dlg)
        cont_radio = QRadioButton("Continuous", dlg)
        button_group.addButton(off_radio)
        button_group.addButton(cont_radio)
        layout.addWidget(off_radio)
        layout.addWidget(cont_radio)

        if self._awb_last_value == "Off":
            off_radio.setChecked(True)
        elif self._awb_last_value == "Continuous":
            cont_radio.setChecked(True)

        error_label = QLabel("", dlg)
        layout.addWidget(error_label)

        applying = {"active": False}

        def apply_selection(selected: str) -> None:
            if applying["active"]:
                return
            if selected == self._awb_last_value:
                return
            applying["active"] = True
            success = self._apply_awb_value(selected, source="CHANGE")
            if success:
                error_label.setText("")
            else:
                error_label.setText("Failed to apply.")
            applying["active"] = False

        off_radio.toggled.connect(lambda checked: apply_selection("Off") if checked else None)
        cont_radio.toggled.connect(lambda checked: apply_selection("Continuous") if checked else None)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dlg)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        dlg.exec()

    def _on_run_awb_once_clicked(self) -> None:
        if self._updating_controls or not self._controls_enabled:
            return
        if not self._awb_supported:
            return
        if not self._is_connected():
            return

        success = self._apply_awb_value("Once", source="RUN_ONCE")
        if not success:
            QMessageBox.warning(self, "", "Failed to run Auto White Balance once.", QMessageBox.StandardButton.Ok)

    def _on_change_resolution_clicked(self) -> None:
        if self._updating_controls or not self._controls_enabled:
            return
        if not self._resolution_entries:
            return
        if not self._is_connected():
            return

        selected = self._select_entry_dialog(
            "Select Resolution",
            self._resolution_entries,
            self._current_resolution,
        )
        if selected is None or selected == self._current_resolution:
            return

        width_id = getattr(ic4.PropId, "WIDTH", None)
        height_id = getattr(ic4.PropId, "HEIGHT", None)
        if width_id is None or height_id is None:
            self._set_resolution_error("KeyError: PropId.WIDTH/HEIGHT not found")
            QMessageBox.warning(self, "", "Failed to apply Resolution.", QMessageBox.StandardButton.Ok)
            return
        width, height = selected
        success = self._reconfigure_stream(
            lambda prop_map: self._apply_width_height(prop_map, width_id, height_id, width, height)
        )
        if not success:
            QMessageBox.warning(self, "", "Failed to apply Resolution.", QMessageBox.StandardButton.Ok)
            if self._is_connected():
                self._load_settings_from_device()

    def _on_change_pixel_format_clicked(self) -> None:
        if self._updating_controls or not self._controls_enabled:
            return
        if not self._pixel_format_entries:
            QMessageBox.warning(self, "", "No applicable PixelFormat candidates.", QMessageBox.StandardButton.Ok)
            return
        if not self._is_connected():
            return

        selected = self._select_entry_dialog(
            "Select PixelFormat",
            self._pixel_format_entries,
            self._current_pixel_format,
        )
        if selected is None or selected == self._current_pixel_format:
            return

        prop_id = getattr(ic4.PropId, "PIXEL_FORMAT", None)
        if prop_id is None:
            QMessageBox.warning(self, "", "Failed to apply PixelFormat.", QMessageBox.StandardButton.Ok)
            return

        success = self._reconfigure_stream(
            lambda prop_map: prop_map.set_value(prop_id, selected)
        )
        if not success:
            QMessageBox.warning(self, "", "Failed to apply PixelFormat.", QMessageBox.StandardButton.Ok)
            if self._is_connected():
                self._load_settings_from_device()

    def _on_change_frame_rate_clicked(self) -> None:
        if self._updating_controls or not self._controls_enabled:
            return
        if self._current_frame_rate is None:
            return
        if not self._is_connected():
            return

        new_rate = self._prompt_frame_rate(self._current_frame_rate)
        if new_rate is None:
            return

        prop_id = getattr(ic4.PropId, "ACQUISITION_FRAME_RATE", None)
        if prop_id is None:
            return

        try:
            prop_map = self.preview_grabber.device_property_map
            prop_map.set_value(prop_id, float(new_rate))
            try:
                self._current_frame_rate = prop_map.get_value_float(prop_id)
            except ic4.IC4Exception:
                self._current_frame_rate = float(new_rate)
            self._refresh_frequent_settings_ui()
        except ic4.IC4Exception:
            success = self._reconfigure_stream(
                lambda prop_map: prop_map.set_value(prop_id, float(new_rate))
            )
            if not success:
                QMessageBox.warning(self, "", "Failed to apply FrameRate.", QMessageBox.StandardButton.Ok)
                if self._is_connected():
                    self._load_settings_from_device()

    def _reconfigure_stream(self, apply_update) -> bool:
        if self._active_entry is None:
            return False

        self.status_label.setText("Status: Reconfiguring...")
        self._set_controls_enabled(False)
        self._stop_preview()

        device_info = self.resolver.find_device_for_entry(self._active_entry)
        if device_info is None:
            self._show_disconnected(self._active_entry)
            return False

        try:
            self._dbg_log("RECONFIGURE_STREAM", "device_open begin", device_info)
            self.preview_grabber.device_open(device_info)
            self._dbg_log("RECONFIGURE_STREAM", "device_open ok", device_info)
            prop_map = self.preview_grabber.device_property_map
            try:
                apply_update(prop_map)
            except Exception:
                try:
                    self._dbg_log("RECONFIGURE_STREAM", "device_close begin", device_info)
                    self.preview_grabber.device_close()
                    self._dbg_log("RECONFIGURE_STREAM", "device_close ok", device_info)
                except ic4.IC4Exception:
                    pass
                self._show_disconnected(self._active_entry)
                return False
            if self.display is not None:
                self._dbg_log("RECONFIGURE_STREAM", "stream_setup begin", device_info)
                self.preview_grabber.stream_setup(self.preview_sink, self.display)
                self._dbg_log("RECONFIGURE_STREAM", "stream_setup ok", device_info)
            else:
                self._dbg_log("RECONFIGURE_STREAM", "stream_setup begin", device_info)
                self.preview_grabber.stream_setup(self.preview_sink)
                self._dbg_log("RECONFIGURE_STREAM", "stream_setup ok", device_info)
            self.status_label.setText("Status: Connected")
            self.preview_stack.setCurrentWidget(self.preview_widget)
            self._load_settings_from_device()
            return True
        except ic4.IC4Exception as exc:
            self._dbg_log("RECONFIGURE_STREAM", f"EXC {type(exc).__name__}: {exc}", device_info)
            try:
                self._dbg_log("RECONFIGURE_STREAM", "device_close begin", device_info)
                self.preview_grabber.device_close()
                self._dbg_log("RECONFIGURE_STREAM", "device_close ok", device_info)
            except ic4.IC4Exception:
                pass
            self._show_disconnected(self._active_entry)
            return False

    def on_advanced(self) -> None:
        return

    def _is_connected(self) -> bool:
        try:
            return self.preview_grabber.is_device_valid
        except ic4.IC4Exception:
            return False

    @staticmethod
    def _format_entry(entry: ChannelEntry, connected: bool) -> str:
        parts = [entry.channel_label]
        if entry.device_identity.model:
            parts.append(entry.device_identity.model)
        if entry.device_identity.serial:
            parts.append(entry.device_identity.serial)
        status = "Connected" if connected else "Disconnected"
        parts.append(status)
        return " - ".join(parts)
