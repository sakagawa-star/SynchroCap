"""Calibration tab (Tab5) for camera calibration with live board detection overlay."""

from __future__ import annotations

import logging

import cv2
import imagingcontrol4 as ic4
import numpy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from board_detector import BoardDetector, DetectionResult
from channel_registry import ChannelRegistry

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)


class _CalibSinkListener(ic4.QueueSinkListener):
    """QueueSinkListener that stores the latest frame via callback."""

    def __init__(self, on_frame_callback):
        self._on_frame = on_frame_callback

    def sink_connected(
        self,
        sink: ic4.QueueSink,
        image_type: ic4.ImageType,
        min_buffers_required: int,
    ) -> bool:
        sink.alloc_and_queue_buffers(min_buffers_required + 2)
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):
        pass

    def frames_queued(self, sink: ic4.QueueSink):
        buf = sink.pop_output_buffer()
        if buf is not None:
            arr = buf.numpy_copy()  # BGR8, shape=(H, W, 3), dtype=uint8
            self._on_frame(arr)


class CalibrationWidget(QWidget):
    """Calibration tab main widget: camera selection, live view, board detection overlay."""

    def __init__(
        self,
        registry: ChannelRegistry,
        resolver,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._resolver = resolver

        # Camera state
        self._grabber: ic4.Grabber | None = None
        self._sink: ic4.QueueSink | None = None
        self._latest_frame: numpy.ndarray | None = None
        self._current_serial: str = ""

        # Board detector
        self._detector = BoardDetector()

        # Frame processing timer
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)  # ~30FPS
        self._frame_timer.timeout.connect(self._process_latest_frame)

        self._create_ui()

    # ── Public methods (called from mainwindow.py) ──

    def on_tab_activated(self) -> None:
        """Called when this tab is selected. Refreshes camera list."""
        self._populate_camera_list()

    def stop_live_view(self) -> None:
        """Stop live view and release Grabber. Safe to call in any state."""
        self._frame_timer.stop()
        if self._grabber is not None:
            try:
                self._grabber.stream_stop()
            except ic4.IC4Exception as e:
                logger.warning("stream_stop failed: %s", e)
            try:
                self._grabber.device_close()
            except ic4.IC4Exception as e:
                logger.warning("device_close failed: %s", e)
            self._grabber = None
        self._sink = None
        self._latest_frame = None
        self._current_serial = ""
        self._live_view_label.clear()
        self._live_view_label.setText("カメラを選択してください")
        self._status_label.setText("Ready")

    # ── UI construction ──

    def _create_ui(self) -> None:
        """Build the tab layout.

        ┌──────────┬──────────────────┐
        │Camera    │   Live View      │
        │List      │   (QLabel)       │
        │(QList)   │                  │
        │──────────│                  │
        │Board     │──────────────────│
        │Settings  │  Status          │
        └──────────┴──────────────────┘
        """
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # ── Left panel ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Camera list
        cam_group = QGroupBox("Camera")
        cam_layout = QVBoxLayout(cam_group)
        self._camera_list = QListWidget()
        self._camera_list.itemClicked.connect(self._on_camera_clicked)
        cam_layout.addWidget(self._camera_list)
        left_layout.addWidget(cam_group)

        # Board settings panel
        board_group = QGroupBox("Board Settings")
        board_form = QFormLayout(board_group)

        self._board_type_combo = QComboBox()
        self._board_type_combo.addItems(["ChArUco", "Checkerboard"])
        self._board_type_combo.currentIndexChanged.connect(
            self._on_board_config_changed
        )
        board_form.addRow("Type:", self._board_type_combo)

        self._cols_spin = QSpinBox()
        self._cols_spin.setRange(3, 20)
        self._cols_spin.setValue(5)
        self._cols_spin.valueChanged.connect(self._on_board_config_changed)
        board_form.addRow("Columns:", self._cols_spin)

        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(3, 20)
        self._rows_spin.setValue(7)
        self._rows_spin.valueChanged.connect(self._on_board_config_changed)
        board_form.addRow("Rows:", self._rows_spin)

        self._square_spin = QDoubleSpinBox()
        self._square_spin.setRange(1.0, 200.0)
        self._square_spin.setValue(30.0)
        self._square_spin.setSingleStep(0.5)
        self._square_spin.setSuffix(" mm")
        self._square_spin.valueChanged.connect(self._on_board_config_changed)
        board_form.addRow("Square size:", self._square_spin)

        self._marker_spin = QDoubleSpinBox()
        self._marker_spin.setRange(1.0, 200.0)
        self._marker_spin.setValue(22.0)
        self._marker_spin.setSingleStep(0.5)
        self._marker_spin.setSuffix(" mm")
        self._marker_spin.valueChanged.connect(self._on_board_config_changed)
        board_form.addRow("Marker size:", self._marker_spin)

        left_layout.addWidget(board_group)
        left_layout.addStretch()

        left_panel.setFixedWidth(200)
        splitter.addWidget(left_panel)

        # ── Right panel ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setFixedHeight(24)
        right_layout.addWidget(self._status_label, stretch=0)

        self._live_view_label = QLabel("カメラを選択してください")
        self._live_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._live_view_label.setStyleSheet("background-color: #1a1a1a; color: #888;")
        right_layout.addWidget(self._live_view_label, stretch=1)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)

    # ── Camera list ──

    def _populate_camera_list(self) -> None:
        """Build camera list from ChannelRegistry."""
        self._camera_list.clear()
        entries = self._registry.list_channels()

        if not entries:
            self._status_label.setText("No channels registered")
            return

        for entry in entries:
            device_info = self._resolver.find_device_for_entry(entry)
            serial = entry.device_identity.serial
            label = f"Ch-{entry.channel_id:02d} ({serial})"
            item = QListWidgetItem(label)

            if device_info is not None:
                item.setData(Qt.ItemDataRole.UserRole, entry)
                item.setData(Qt.ItemDataRole.UserRole + 1, device_info)
            else:
                item.setText(f"{label} [offline]")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                logger.info("Camera %s: offline", serial)

            self._camera_list.addItem(item)

    def _on_camera_clicked(self, item: QListWidgetItem) -> None:
        """Handle camera click. Ignore offline cameras."""
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return

        entry = item.data(Qt.ItemDataRole.UserRole)
        device_info = item.data(Qt.ItemDataRole.UserRole + 1)
        if entry is None or device_info is None:
            return

        serial = entry.device_identity.serial
        if serial == self._current_serial:
            return  # Already connected to this camera

        # Stop existing live view before switching
        self.stop_live_view()
        self._start_live_view(device_info, serial)

    # ── Live view ──

    def _start_live_view(self, device_info: ic4.DeviceInfo, serial: str) -> None:
        """Start live view for the given device."""
        self._status_label.setText(f"Connecting to {serial}...")
        self._camera_list.setEnabled(False)

        try:
            self._grabber = ic4.Grabber()
            self._grabber.event_add_device_lost(self._on_device_lost_callback)
            self._grabber.device_open(device_info)

            listener = _CalibSinkListener(self._on_frame_received)
            self._sink = ic4.QueueSink(
                listener,
                accepted_pixel_formats=[ic4.PixelFormat.BGR8],
            )
            self._grabber.stream_setup(self._sink)

            self._current_serial = serial
            self._frame_timer.start()
            self._camera_list.setEnabled(True)
            self._status_label.setText(f"Live: {serial}")
            logger.info("Camera %s connected", serial)

        except ic4.IC4Exception as e:
            logger.error("Failed to open %s: %s", serial, e)
            self._status_label.setText(f"Error: {e}")
            # Clean up partial state
            if self._grabber is not None:
                try:
                    self._grabber.device_close()
                except ic4.IC4Exception:
                    pass
                self._grabber = None
            self._sink = None
            self._current_serial = ""
            self._camera_list.setEnabled(True)

    def _on_device_lost_callback(self, grabber: ic4.Grabber) -> None:
        """Called from IC4 internal thread when camera is disconnected."""
        QTimer.singleShot(0, self._on_device_lost)

    def _on_device_lost(self) -> None:
        """Handle camera disconnection (GUI thread)."""
        logger.warning("Camera disconnected: %s", self._current_serial)
        self.stop_live_view()
        self._status_label.setText("Camera disconnected")

    def _on_frame_received(self, frame: numpy.ndarray) -> None:
        """Called from IC4 internal thread. Store latest frame only.

        Thread safety: Python reference assignment is effectively atomic under GIL.
        Same pattern as ui_camera_settings.py.
        """
        self._latest_frame = frame

    def _process_latest_frame(self) -> None:
        """Called by QTimer. Process and display the latest frame."""
        frame = self._latest_frame
        if frame is None:
            return
        self._latest_frame = None

        bgr = frame  # Already BGR8 from IC4 QueueSink

        result = self._detector.detect(bgr)
        if result.success:
            bgr = self._detector.draw_overlay(bgr, result)
        self._update_detection_status(result)
        self._display_frame(bgr)

    def _display_frame(self, bgr: numpy.ndarray) -> None:
        """Display BGR image on QLabel with aspect ratio preserved."""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        if qimg.isNull():
            logger.warning("QImage creation failed")
            return
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(
            self._live_view_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._live_view_label.setPixmap(scaled)

    def _update_detection_status(self, result: DetectionResult) -> None:
        """Update status label with detection result."""
        if result.success:
            total = self._detector.max_corners
            self._status_label.setText(
                f"Detected: {result.num_corners}/{total} corners"
            )
        elif result.failure_reason:
            self._status_label.setText(result.failure_reason)
        else:
            self._status_label.setText("No board detected")

    # ── Board settings ──

    def _on_board_config_changed(self) -> None:
        """Reconfigure BoardDetector when any board setting changes."""
        board_type = "charuco" if self._board_type_combo.currentIndex() == 0 else "checkerboard"
        cols = self._cols_spin.value()
        rows = self._rows_spin.value()
        square_mm = self._square_spin.value()
        marker_mm = self._marker_spin.value()

        # Enable/disable marker size based on board type
        self._marker_spin.setEnabled(board_type == "charuco")

        # Enforce marker_mm < square_mm
        if marker_mm >= square_mm:
            marker_mm = max(1.0, square_mm - 1.0)
            if square_mm < 2.0:
                marker_mm = 1.0
            self._marker_spin.blockSignals(True)
            self._marker_spin.setValue(marker_mm)
            self._marker_spin.blockSignals(False)
            logger.info("marker_mm adjusted to %.1f", marker_mm)

        self._detector.reconfigure(board_type, cols, rows, square_mm, marker_mm)
