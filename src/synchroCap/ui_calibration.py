"""Calibration tab (Tab5) for camera calibration with live board detection overlay."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import imagingcontrol4 as ic4
import numpy
from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QMessageBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from board_detector import BoardDetector, DetectionResult
from board_settings_store import BoardSettingsStore
from calibration_engine import CalibrationEngine, CalibrationResult
from calibration_exporter import CalibrationExporter
from channel_registry import ChannelRegistry
from coverage_heatmap import CoverageHeatmap
from stability_trigger import Phase, StabilityState, StabilityTrigger

logger = logging.getLogger(__name__)

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)


@dataclass
class CaptureData:
    """Data from a single calibration capture."""
    image_points: numpy.ndarray    # shape=(N,1,2), float32
    object_points: numpy.ndarray   # shape=(N,1,3), float32
    charuco_ids: numpy.ndarray | None  # shape=(N,1), int32 (ChArUco only)
    num_corners: int
    raw_bgr: numpy.ndarray         # raw frame without overlay (for saving)


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

        # Board settings (internal state)
        self._board_type: str = "charuco"
        self._cols: int = 5
        self._rows: int = 7
        self._square_mm: float = 30.0
        self._marker_mm: float = 22.0

        # Persistent storage
        appdata = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        board_settings_path = os.path.join(appdata, "board_settings.json")
        self._board_settings_store = BoardSettingsStore(board_settings_path)
        self._load_board_settings()

        # Board detector
        self._detector = BoardDetector()

        # Stability trigger
        self._stability_trigger = StabilityTrigger()

        # Capture state
        self._captures: list[CaptureData] = []
        self._capture_image_size: tuple[int, int] | None = None
        self._save_dir: Path | None = None

        # Heatmap state
        self._heatmap_generator: CoverageHeatmap | None = None
        self._heatmap_cache: numpy.ndarray | None = None

        # Calibration state
        self._calibration_engine = CalibrationEngine()
        self._calibration_result: CalibrationResult | None = None

        # Frame processing timer
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)  # ~30FPS
        self._frame_timer.timeout.connect(self._process_latest_frame)

        self._create_ui()

        # Apply restored board settings to UI and detector
        self._update_board_settings_ui()
        self._apply_board_config()

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
        self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")
        self._status_label.setText("Ready")
        # Clear captures
        self._captures.clear()
        self._capture_image_size = None
        self._save_dir = None
        self._stability_trigger.reset()
        self._heatmap_cache = None
        self._heatmap_generator = None
        self._clear_calibration_result()
        self._update_capture_list_ui()
        self._update_button_states()

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

        self._type_button = QPushButton("ChArUco")
        self._type_button.clicked.connect(self._on_type_button_clicked)
        board_form.addRow("Type:", self._type_button)

        self._cols_button = QPushButton("5")
        self._cols_button.clicked.connect(self._on_cols_button_clicked)
        board_form.addRow("Columns:", self._cols_button)

        self._rows_button = QPushButton("7")
        self._rows_button.clicked.connect(self._on_rows_button_clicked)
        board_form.addRow("Rows:", self._rows_button)

        self._square_button = QPushButton("30.0 mm")
        self._square_button.clicked.connect(self._on_square_button_clicked)
        board_form.addRow("Square size:", self._square_button)

        self._marker_button = QPushButton("22.0 mm")
        self._marker_button.clicked.connect(self._on_marker_button_clicked)
        board_form.addRow("Marker size:", self._marker_button)

        left_layout.addWidget(board_group)

        # Captures section
        captures_group = QGroupBox("Captures")
        captures_layout = QVBoxLayout(captures_group)

        self._captures_list = QListWidget()
        self._captures_list.currentRowChanged.connect(self._update_button_states)
        captures_layout.addWidget(self._captures_list)

        captures_btn_layout = QHBoxLayout()
        self._delete_button = QPushButton("Delete")
        self._delete_button.setEnabled(False)
        self._delete_button.clicked.connect(self._on_delete_clicked)
        captures_btn_layout.addWidget(self._delete_button)

        self._clear_all_button = QPushButton("Clear All")
        self._clear_all_button.setEnabled(False)
        self._clear_all_button.clicked.connect(self._on_clear_all_clicked)
        captures_btn_layout.addWidget(self._clear_all_button)
        captures_layout.addLayout(captures_btn_layout)

        self._save_button = QPushButton("Save")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._on_save_clicked)
        captures_layout.addWidget(self._save_button)

        left_layout.addWidget(captures_group)

        # Calibration section
        calib_group = QGroupBox("Calibration")
        calib_layout = QVBoxLayout(calib_group)

        self._calibrate_button = QPushButton("Calibrate")
        self._calibrate_button.setEnabled(False)
        self._calibrate_button.clicked.connect(self._on_calibrate_clicked)
        calib_layout.addWidget(self._calibrate_button)

        self._export_button = QPushButton("Export")
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._on_export_clicked)
        calib_layout.addWidget(self._export_button)

        results_form = QFormLayout()

        self._rms_label = QLabel("---")
        results_form.addRow("RMS Error:", self._rms_label)

        self._fx_label = QLabel("---")
        results_form.addRow("fx:", self._fx_label)

        self._fy_label = QLabel("---")
        results_form.addRow("fy:", self._fy_label)

        self._cx_label = QLabel("---")
        results_form.addRow("cx:", self._cx_label)

        self._cy_label = QLabel("---")
        results_form.addRow("cy:", self._cy_label)

        self._dist_label = QLabel("---")
        self._dist_label.setWordWrap(True)
        results_form.addRow("Dist:", self._dist_label)

        calib_layout.addLayout(results_form)

        left_layout.addWidget(calib_group)

        left_panel.setFixedWidth(200)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(left_panel)
        scroll_area.setFixedWidth(220)
        splitter.addWidget(scroll_area)

        # ── Right panel ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setFixedHeight(24)
        right_layout.addWidget(self._status_label, stretch=0)

        self._live_view_frame = QFrame()
        self._live_view_frame.setFrameShape(QFrame.Shape.NoFrame)
        self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")
        frame_inner_layout = QVBoxLayout(self._live_view_frame)
        frame_inner_layout.setContentsMargins(0, 0, 0, 0)

        self._live_view_label = QLabel("カメラを選択してください")
        self._live_view_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._live_view_label.setStyleSheet("background-color: #1a1a1a; color: #888;")
        self._live_view_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        frame_inner_layout.addWidget(self._live_view_label)

        right_layout.addWidget(self._live_view_frame, stretch=1)

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
            overlay_bgr = self._detector.draw_overlay(bgr, result)
        else:
            overlay_bgr = bgr

        state = self._stability_trigger.update(result.success)

        if state.triggered and result.success:
            self._execute_capture(result, bgr)

        self._update_status_display(result, state)

        # Heatmap overlay — auto-display when captures exist
        if self._heatmap_cache is not None:
            overlay_bgr = cv2.addWeighted(overlay_bgr, 0.7, self._heatmap_cache, 0.3, 0)

        self._display_frame(overlay_bgr)

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

    def _update_status_display(self, result: DetectionResult, state: StabilityState) -> None:
        """Update status label based on detection result and stability state."""
        if state.triggered:
            return  # _execute_capture() sets the status

        if state.phase == Phase.COOLDOWN:
            self._status_label.setText(f"Cooldown: {state.cooldown_remaining:.1f}s")
            return

        if result.success:
            total = self._detector.max_corners
            if state.stability_elapsed > 0:
                self._status_label.setText(
                    f"Detected: {result.num_corners}/{total} | "
                    f"Stability: {state.stability_elapsed:.1f}s / "
                    f"{StabilityTrigger.STABILITY_THRESHOLD:.1f}s"
                )
            else:
                self._status_label.setText(
                    f"Detected: {result.num_corners}/{total} corners"
                )
        elif result.failure_reason:
            self._status_label.setText(result.failure_reason)
        else:
            self._status_label.setText("No board detected")

    # ── Capture ──

    _FLASH_DURATION_MS: int = 300
    _FLASH_BORDER: str = "border: 3px solid #00cc00;"

    def _execute_capture(
        self,
        result: DetectionResult,
        raw_bgr: numpy.ndarray,
    ) -> None:
        """Execute capture on stability trigger."""
        h, w = raw_bgr.shape[:2]
        current_size = (w, h)

        if self._capture_image_size is None:
            self._capture_image_size = current_size
        elif self._capture_image_size != current_size:
            self._status_label.setText("Image size mismatch")
            logger.warning("Image size mismatch: expected %s, got %s",
                           self._capture_image_size, current_size)
            return

        capture = CaptureData(
            image_points=result.image_points.copy(),
            object_points=result.object_points.copy(),
            charuco_ids=result.charuco_ids.copy() if result.charuco_ids is not None else None,
            num_corners=result.num_corners,
            raw_bgr=raw_bgr.copy(),
        )
        self._captures.append(capture)
        n = len(self._captures)

        self._clear_calibration_result()
        self._update_heatmap_cache()
        self._update_capture_list_ui()
        self._update_button_states()
        self._flash_live_view()

        self._status_label.setText(f"Captured #{n} ({capture.num_corners} corners)")
        logger.info("Capture #%d: %d corners", n, capture.num_corners)

    def _flash_live_view(self) -> None:
        """Flash the live view border green briefly."""
        self._live_view_frame.setStyleSheet(
            f"background-color: #1a1a1a; {self._FLASH_BORDER}"
        )
        QTimer.singleShot(self._FLASH_DURATION_MS, self._reset_live_view_style)

    def _reset_live_view_style(self) -> None:
        """Reset live view frame style after flash."""
        self._live_view_frame.setStyleSheet("background-color: #1a1a1a;")

    def _update_capture_list_ui(self) -> None:
        """Rebuild the captures QListWidget."""
        self._captures_list.clear()
        for i, cap in enumerate(self._captures):
            text = f"#{i+1:02d}: {cap.num_corners} corners"
            if (self._calibration_result is not None
                    and i < len(self._calibration_result.per_image_errors)):
                err = self._calibration_result.per_image_errors[i]
                text += f" | err: {err:.2f} px"
            self._captures_list.addItem(text)

    def _update_button_states(self, _row: int = -1) -> None:
        """Update Delete/Clear All/Calibrate/Export button enabled states."""
        has_captures = len(self._captures) > 0
        has_selection = self._captures_list.currentRow() >= 0

        self._delete_button.setEnabled(has_captures and has_selection)
        self._clear_all_button.setEnabled(has_captures)
        self._save_button.setEnabled(has_captures)
        self._calibrate_button.setEnabled(
            len(self._captures) >= CalibrationEngine.MIN_CAPTURES
        )
        self._export_button.setEnabled(self._calibration_result is not None)

    def _on_delete_clicked(self) -> None:
        """Delete selected capture."""
        row = self._captures_list.currentRow()
        if row < 0 or row >= len(self._captures):
            return
        self._captures.pop(row)
        if not self._captures:
            self._capture_image_size = None
            self._save_dir = None
        self._clear_calibration_result()
        self._update_heatmap_cache()
        self._update_capture_list_ui()
        self._update_button_states()
        logger.info("Deleted capture #%d", row + 1)

    def _on_clear_all_clicked(self) -> None:
        """Clear all captures."""
        self._captures.clear()
        self._capture_image_size = None
        self._save_dir = None
        self._clear_calibration_result()
        self._update_heatmap_cache()
        self._update_capture_list_ui()
        self._update_button_states()
        logger.info("Cleared all captures")

    # ── Calibration ──

    def _on_calibrate_clicked(self) -> None:
        """Execute calibration calculation."""
        if len(self._captures) < CalibrationEngine.MIN_CAPTURES:
            return

        object_points_list = [cap.object_points for cap in self._captures]
        image_points_list = [cap.image_points for cap in self._captures]

        try:
            result = self._calibration_engine.calibrate(
                object_points_list,
                image_points_list,
                self._capture_image_size,
            )
        except cv2.error as e:
            self._status_label.setText(f"Calibration failed: {e}")
            logger.warning("Calibration failed: %s", e)
            return

        self._calibration_result = result
        self._display_calibration_result(result)
        self._update_capture_list_ui()
        self._update_button_states()
        self._status_label.setText(
            f"Calibration done: RMS={result.rms_error:.4f} px"
        )

    def _on_export_clicked(self) -> None:
        """Export calibration result to TOML and JSON files."""
        if self._calibration_result is None or self._capture_image_size is None:
            return

        try:
            export_dir = self._ensure_save_dir()
        except OSError as e:
            self._status_label.setText(f"Export failed: {e}")
            logger.error("Export failed: %s", e)
            return

        try:
            exporter = CalibrationExporter()
            paths = exporter.export(
                result=self._calibration_result,
                serial=self._current_serial,
                image_size=self._capture_image_size,
                num_images=len(self._captures),
                output_dir=export_dir,
            )
        except OSError as e:
            self._status_label.setText(f"Export failed: {e}")
            logger.error("Export failed: %s", e)
            return

        resolved = export_dir.resolve()
        self._status_label.setText(f"Exported to {resolved}")
        logger.info("Exported: %s", [str(p) for p in paths])

        QMessageBox.information(
            self,
            "Export Complete",
            f"Exported to:\n{resolved}",
        )

    def _display_calibration_result(self, result: CalibrationResult) -> None:
        """Update result labels with calibration values."""
        self._rms_label.setText(f"{result.rms_error:.4f} px")
        self._fx_label.setText(f"{result.camera_matrix[0, 0]:.1f}")
        self._fy_label.setText(f"{result.camera_matrix[1, 1]:.1f}")
        self._cx_label.setText(f"{result.camera_matrix[0, 2]:.1f}")
        self._cy_label.setText(f"{result.camera_matrix[1, 2]:.1f}")

        d = result.dist_coeffs.flatten()
        self._dist_label.setText(
            f"k1={d[0]:.4f}, k2={d[1]:.4f}\n"
            f"p1={d[2]:.4f}, p2={d[3]:.4f}\n"
            f"k3={d[4]:.4f}, k4={d[5]:.4f}\n"
            f"k5={d[6]:.4f}, k6={d[7]:.4f}"
        )

    def _clear_calibration_result(self) -> None:
        """Clear result labels and internal result state."""
        self._calibration_result = None
        self._rms_label.setText("---")
        self._fx_label.setText("---")
        self._fy_label.setText("---")
        self._cx_label.setText("---")
        self._cy_label.setText("---")
        self._dist_label.setText("---")

    # ── Heatmap ──

    def _update_heatmap_cache(self) -> None:
        """Recompute heatmap cache. Clear to None if no captures."""
        if not self._captures or self._capture_image_size is None:
            self._heatmap_cache = None
            return

        # CaptureData.image_points: shape=(N,1,2) -> reshape(-1,2) -> (N,2)
        all_points = numpy.concatenate(
            [cap.image_points.reshape(-1, 2) for cap in self._captures],
            axis=0,
        )

        if self._heatmap_generator is None:
            self._heatmap_generator = CoverageHeatmap(self._capture_image_size)

        self._heatmap_cache = self._heatmap_generator.generate(all_points)
        logger.info("Heatmap updated: %d points, sigma=%.1f",
                     len(all_points), self._heatmap_generator._sigma)

    # ── Save directory ──

    def _ensure_save_dir(self) -> Path:
        """Return save directory, creating it on first call.

        mkdir is called on every invocation because Save and Export
        can be called in any order, and the directory may not yet
        exist when _save_dir is already set.

        Raises:
            OSError: If mkdir fails (e.g. permission denied, disk full).
        """
        if self._save_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._save_dir = Path("captures") / timestamp / "intrinsics" / f"cam{self._current_serial}"
        self._save_dir.mkdir(parents=True, exist_ok=True)
        return self._save_dir

    # ── Image saving ──

    def _on_save_clicked(self) -> None:
        """Save all captured raw frames as PNG files."""
        if not self._captures:
            return

        try:
            cam_dir = self._ensure_save_dir()
        except OSError as e:
            logger.error("Failed to create save dir %s: %s", self._save_dir, e)
            self._status_label.setText(f"Save failed: {e}")
            return

        saved = 0
        for i, cap in enumerate(self._captures):
            filename = f"capture_{i+1:03d}.png"
            filepath = cam_dir / filename
            try:
                cv2.imwrite(str(filepath), cap.raw_bgr)
                saved += 1
            except Exception as e:
                logger.error("Failed to save %s: %s", filepath, e)

        self._status_label.setText(f"Saved {saved} images to {cam_dir}")
        logger.info("Saved %d images to %s", saved, cam_dir)

    # ── Board settings ──

    def _save_board_settings(self) -> None:
        """Save current board settings to persistent storage."""
        self._board_settings_store.save({
            "board_type": self._board_type,
            "cols": self._cols,
            "rows": self._rows,
            "square_mm": self._square_mm,
            "marker_mm": self._marker_mm,
        })

    def _load_board_settings(self) -> None:
        """Load board settings from persistent storage."""
        data = self._board_settings_store.load()
        if data is None:
            return

        bt = data.get("board_type")
        if bt in ("charuco", "checkerboard"):
            self._board_type = bt

        cols = data.get("cols")
        if isinstance(cols, int) and 3 <= cols <= 20:
            self._cols = cols

        rows = data.get("rows")
        if isinstance(rows, int) and 3 <= rows <= 20:
            self._rows = rows

        sq = data.get("square_mm")
        if isinstance(sq, (int, float)) and 1.0 <= sq <= 200.0:
            self._square_mm = float(sq)

        mk = data.get("marker_mm")
        if isinstance(mk, (int, float)) and 1.0 <= mk <= 200.0:
            self._marker_mm = float(mk)

    def _update_board_settings_ui(self) -> None:
        """Update board settings button texts from internal state."""
        self._type_button.setText("ChArUco" if self._board_type == "charuco" else "Checkerboard")
        self._cols_button.setText(str(self._cols))
        self._rows_button.setText(str(self._rows))
        self._square_button.setText(f"{self._square_mm:.1f} mm")
        self._marker_button.setText(f"{self._marker_mm:.1f} mm")

    def _apply_board_config(self) -> None:
        """Apply current board config to detector. Enforce marker_mm < square_mm."""
        if self._marker_mm >= self._square_mm:
            self._marker_mm = max(1.0, self._square_mm - 1.0)
            if self._square_mm < 2.0:
                self._marker_mm = 1.0
            self._marker_button.setText(f"{self._marker_mm:.1f} mm")
            logger.info("marker_mm adjusted to %.1f", self._marker_mm)

        self._marker_button.setEnabled(self._board_type == "charuco")

        self._detector.reconfigure(
            self._board_type, self._cols, self._rows,
            self._square_mm, self._marker_mm,
        )

    def _on_type_button_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Board Type")
        layout = QVBoxLayout(dlg)

        combo = QComboBox()
        combo.addItems(["ChArUco", "Checkerboard"])
        combo.setCurrentIndex(0 if self._board_type == "charuco" else 1)
        layout.addWidget(combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._board_type = "charuco" if combo.currentIndex() == 0 else "checkerboard"
        self._type_button.setText("ChArUco" if self._board_type == "charuco" else "Checkerboard")
        self._apply_board_config()
        self._save_board_settings()

    def _on_cols_button_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Columns")
        layout = QVBoxLayout(dlg)

        spin = QSpinBox()
        spin.setRange(3, 20)
        spin.setValue(self._cols)
        layout.addWidget(spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._cols = spin.value()
        self._cols_button.setText(str(self._cols))
        self._apply_board_config()
        self._save_board_settings()

    def _on_rows_button_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Rows")
        layout = QVBoxLayout(dlg)

        spin = QSpinBox()
        spin.setRange(3, 20)
        spin.setValue(self._rows)
        layout.addWidget(spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._rows = spin.value()
        self._rows_button.setText(str(self._rows))
        self._apply_board_config()
        self._save_board_settings()

    def _on_square_button_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Square Size")
        layout = QVBoxLayout(dlg)

        spin = QDoubleSpinBox()
        spin.setRange(1.0, 200.0)
        spin.setSingleStep(0.5)
        spin.setSuffix(" mm")
        spin.setValue(self._square_mm)
        layout.addWidget(spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._square_mm = spin.value()
        self._square_button.setText(f"{self._square_mm:.1f} mm")
        self._apply_board_config()
        self._save_board_settings()

    def _on_marker_button_clicked(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Marker Size")
        layout = QVBoxLayout(dlg)

        spin = QDoubleSpinBox()
        spin.setRange(1.0, 200.0)
        spin.setSingleStep(0.5)
        spin.setSuffix(" mm")
        spin.setValue(self._marker_mm)
        layout.addWidget(spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self._marker_mm = spin.value()
        self._marker_button.setText(f"{self._marker_mm:.1f} mm")
        self._apply_board_config()
        self._save_board_settings()
