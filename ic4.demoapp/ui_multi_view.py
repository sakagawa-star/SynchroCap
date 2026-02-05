from __future__ import annotations

from typing import List, Optional

import imagingcontrol4 as ic4
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from channel_registry import ChannelEntry, ChannelRegistry
from ui_channel_manager import ChannelManagerWidget
from recording_controller import RecordingController, RecordingState


class _SlotListener(ic4.QueueSinkListener):
    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        sink.alloc_and_queue_buffers(min_buffers_required + 2)
        return True

    def sink_disconnected(self, sink: ic4.QueueSink):
        pass

    def frames_queued(listener, sink: ic4.QueueSink):
        sink.pop_output_buffer()


class MultiViewWidget(QWidget):
    tabs_lock_changed = Signal(bool)

    def __init__(self, registry: ChannelRegistry, resolver, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.resolver = resolver
        self._channel_entries: List[ChannelEntry] = []
        self.slots: list[dict[str, object]] = []
        self._ptp_timer = QTimer(self)
        self._ptp_timer.setInterval(1000)
        self._ptp_timer.timeout.connect(self._update_ptp_all)
        self._recording = False
        self._recording_controller = RecordingController(on_state_changed=self._on_recording_state_changed)
        self._build_ui()
        self.refresh_channels()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout()
        self.recording_checkbox = QCheckBox("Simulate Recording", self)
        self.recording_checkbox.setChecked(False)
        self.recording_checkbox.toggled.connect(self._on_recording_toggled)
        self.lock_tabs_checkbox = QCheckBox("Lock Tab1/Tab2 while recording", self)
        self.lock_tabs_checkbox.setChecked(False)
        self.lock_tabs_checkbox.toggled.connect(self._on_lock_toggled)
        controls_layout.addWidget(self.recording_checkbox)
        controls_layout.addWidget(self.lock_tabs_checkbox)
        controls_layout.addStretch(1)
        main_layout.addLayout(controls_layout)
        recording_group = QGroupBox("Recording", self)
        recording_layout = QFormLayout(recording_group)
        self.rec_start_after_sec = QSpinBox(recording_group)
        self.rec_start_after_sec.setRange(1, 86400)
        self.rec_start_after_sec.setSuffix(" sec")
        self.rec_start_after_sec.setValue(8)
        self.rec_duration_sec = QSpinBox(recording_group)
        self.rec_duration_sec.setRange(1, 86400)
        self.rec_duration_sec.setSuffix(" sec")
        self.rec_duration_sec.setValue(30)
        recording_layout.addRow("Start after", self.rec_start_after_sec)
        recording_layout.addRow("Duration", self.rec_duration_sec)
        self.rec_status_label = QLabel("Ready", recording_group)
        self.rec_status_label.setStyleSheet("font-weight: bold;")
        recording_layout.addRow("Status", self.rec_status_label)
        buttons_layout = QHBoxLayout()
        self.rec_start_button = QPushButton("Start", recording_group)
        self.rec_start_button.clicked.connect(self._on_start_recording)
        self.rec_stop_button = QPushButton("Stop", recording_group)
        self.rec_stop_button.setEnabled(False)  # 本フェーズでは無効
        buttons_layout.addWidget(self.rec_start_button)
        buttons_layout.addWidget(self.rec_stop_button)
        buttons_layout.addStretch(1)
        recording_layout.addRow(buttons_layout)
        main_layout.addWidget(recording_group)
        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)
        grid = QGridLayout()
        main_layout.addLayout(grid, 1)

        for index in range(4):
            slot = self._create_slot(index)
            self.slots.append(slot)
            grid.addWidget(slot["container"], index // 2, index % 2)

    def _create_slot(self, index: int) -> dict[str, object]:
        container = QWidget(self)
        layout = QVBoxLayout(container)

        header_layout = QHBoxLayout()
        title = QLabel(f"Cam{index + 1}", container)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        combo = QComboBox(container)
        combo.currentIndexChanged.connect(
            lambda _idx, slot_index=index: self._on_channel_changed(slot_index)
        )
        header_layout.addWidget(title)
        header_layout.addWidget(combo, 1)
        layout.addLayout(header_layout)

        ptp_label = QLabel("PTP: N/A", container)
        ptp_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        role_label = QLabel("Role: N/A", container)
        role_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(ptp_label)
        layout.addWidget(role_label)

        display_widget = ic4.pyside6.DisplayWidget()
        display_widget.setMinimumSize(320, 240)
        try:
            display = display_widget.as_display()
            display.set_render_position(ic4.DisplayRenderPosition.STRETCH_CENTER)
        except Exception:
            display = None

        disconnected_label = QLabel("Disconnected", container)
        disconnected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disconnected_label.setWordWrap(True)

        stack = QStackedLayout()
        stack.addWidget(display_widget)
        stack.addWidget(disconnected_label)
        stack.setCurrentWidget(disconnected_label)

        preview_container = QWidget(container)
        preview_container.setLayout(stack)
        layout.addWidget(preview_container, 1)

        grabber = ic4.Grabber()
        listener = _SlotListener()
        sink = ic4.QueueSink(listener)

        return {
            "slot_index": index,
            "container": container,
            "combo": combo,
            "grabber": grabber,
            "sink": sink,
            "display_widget": display_widget,
            "display": display,
            "stack": stack,
            "disconnected_label": disconnected_label,
            "ptp_label": ptp_label,
            "role_label": role_label,
            "ptp_polling": False,
            "ptp_last_error": None,
            "entry": None,
            "channel_id": None,
        }

    def refresh_channels(self) -> None:
        self._channel_entries = self.registry.list_channels()
        for slot in self.slots:
            combo = slot["combo"]
            assert isinstance(combo, QComboBox)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("None", None)
            for entry in self._channel_entries:
                label = ChannelManagerWidget.format_device(entry.device_identity)
                combo.addItem(f"Channel {entry.channel_label}: {label}", entry)
            channel_id = slot.get("channel_id")
            if channel_id is None:
                combo.setCurrentIndex(0)
            else:
                entry = next((e for e in self._channel_entries if e.channel_id == channel_id), None)
                if entry is None:
                    combo.setCurrentIndex(0)
                    self._slot_stop(slot, log=True)
                else:
                    idx = combo.findData(entry)
                    combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def stop_all(self) -> None:
        self._stop_ptp_timer()
        for slot in self.slots:
            try:
                self._slot_stop(slot, log=False, clear_selection=False)
            except Exception:
                pass

    def resume_selected(self) -> None:
        for slot in self.slots:
            channel_id = slot.get("channel_id")
            if channel_id is None:
                continue
            entry = next((e for e in self._channel_entries if e.channel_id == channel_id), None)
            if entry is None:
                try:
                    self._slot_stop(slot, log=True, clear_selection=True)
                except Exception:
                    pass
                continue
            slot_index = slot.get("slot_index", 0)
            try:
                self._slot_start(slot, entry, int(slot_index))
            except Exception:
                pass
        self._start_ptp_timer()

    def refresh_and_resume(self) -> None:
        self.refresh_channels()
        self.resume_selected()

    def is_tabs_locked(self) -> bool:
        return self._recording and self.lock_tabs_checkbox.isChecked()

    def _emit_tabs_lock(self) -> None:
        self.tabs_lock_changed.emit(self.is_tabs_locked())

    def _on_recording_toggled(self, checked: bool) -> None:
        self._recording = checked
        if checked:
            if not self.lock_tabs_checkbox.isChecked():
                self.lock_tabs_checkbox.setChecked(True)
            self.lock_tabs_checkbox.setEnabled(False)
        else:
            self.lock_tabs_checkbox.setEnabled(True)
        self._emit_tabs_lock()

    def _on_lock_toggled(self, checked: bool) -> None:
        _ = checked
        self._emit_tabs_lock()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._start_ptp_timer()

    def hideEvent(self, event) -> None:
        self._stop_ptp_timer()
        super().hideEvent(event)

    def _on_channel_changed(self, slot_index: int) -> None:
        slot = self.slots[slot_index]
        combo = slot["combo"]
        assert isinstance(combo, QComboBox)
        entry = combo.currentData()
        if entry is None:
            self._slot_stop(slot, log=True)
            return
        if not isinstance(entry, ChannelEntry):
            self._slot_stop(slot, log=True)
            return
        self._slot_start(slot, entry, slot_index)

    def _slot_start(self, slot: dict[str, object], entry: ChannelEntry, slot_index: int) -> None:
        self._slot_stop(slot, log=False)
        device_info = None
        try:
            device_info = self.resolver.find_device_for_entry(entry)
        except Exception as exc:
            self._log(slot_index, f"start failed exc={type(exc).__name__}: {exc}")
        if device_info is None:
            self._set_disconnected(slot)
            self._log(slot_index, "start failed device not found")
            return

        grabber = slot["grabber"]
        sink = slot["sink"]
        display = slot["display"]
        stack = slot["stack"]
        display_widget = slot["display_widget"]
        assert isinstance(grabber, ic4.Grabber)
        assert isinstance(sink, ic4.QueueSink)
        assert isinstance(stack, QStackedLayout)
        assert isinstance(display_widget, QWidget)

        try:
            if display is None:
                self._set_disconnected(slot)
                self._log(slot_index, "start failed display unavailable")
                self._set_ptp_na(slot)
                return
            grabber.device_open(device_info)
            grabber.stream_setup(sink, display)
            stack.setCurrentWidget(display_widget)
            slot["ptp_polling"] = True
            slot["entry"] = entry
            slot["channel_id"] = entry.channel_id
            serial = getattr(device_info, "serial", "") or getattr(device_info, "serial_number", "")
            self._log(slot_index, f"start ok serial={serial}")
            self._read_ptp(slot, slot_index, log_success=True)
        except ic4.IC4Exception as exc:
            self._log(slot_index, f"start failed exc={type(exc).__name__}: {exc}")
            self._slot_stop(slot, log=False)
        except Exception as exc:
            self._log(slot_index, f"start failed exc={type(exc).__name__}: {exc}")
            self._slot_stop(slot, log=False)

    def _slot_stop(self, slot: dict[str, object], log: bool, clear_selection: bool = True) -> None:
        grabber = slot["grabber"]
        display = slot["display"]
        stack = slot["stack"]
        disconnected_label = slot["disconnected_label"]
        assert isinstance(grabber, ic4.Grabber)
        assert isinstance(stack, QStackedLayout)
        assert isinstance(disconnected_label, QWidget)

        try:
            if grabber.is_streaming:
                grabber.stream_stop()
        except ic4.IC4Exception:
            pass
        except Exception:
            pass

        try:
            if grabber.is_device_valid:
                grabber.device_close()
        except ic4.IC4Exception:
            pass
        except Exception:
            pass

        if display is not None:
            try:
                display.display_buffer(None)
            except ic4.IC4Exception:
                pass
            except Exception:
                pass

        stack.setCurrentWidget(disconnected_label)
        slot["ptp_polling"] = False
        slot["entry"] = None
        if clear_selection:
            slot["channel_id"] = None
        self._set_ptp_na(slot)
        if log:
            slot_index = slot.get("slot_index", 0)
            self._log(int(slot_index), "stopped")

    def _set_disconnected(self, slot: dict[str, object]) -> None:
        stack = slot["stack"]
        disconnected_label = slot["disconnected_label"]
        assert isinstance(stack, QStackedLayout)
        assert isinstance(disconnected_label, QWidget)
        stack.setCurrentWidget(disconnected_label)

    def _set_ptp_na(self, slot: dict[str, object]) -> None:
        ptp_label = slot["ptp_label"]
        role_label = slot["role_label"]
        assert isinstance(ptp_label, QLabel)
        assert isinstance(role_label, QLabel)
        ptp_label.setText("PTP: N/A")
        role_label.setText("Role: N/A")
        slot["ptp_last_error"] = None

    def _start_ptp_timer(self) -> None:
        if not self._ptp_timer.isActive():
            self._ptp_timer.start()

    def _stop_ptp_timer(self) -> None:
        if self._ptp_timer.isActive():
            self._ptp_timer.stop()

    def _update_ptp_all(self) -> None:
        for slot in self.slots:
            if not slot.get("ptp_polling"):
                continue
            slot_index = slot.get("slot_index", 0)
            self._read_ptp(slot, int(slot_index), log_success=False)

    def _read_ptp(self, slot: dict[str, object], slot_index: int, log_success: bool) -> None:
        grabber = slot["grabber"]
        ptp_label = slot["ptp_label"]
        role_label = slot["role_label"]
        assert isinstance(grabber, ic4.Grabber)
        assert isinstance(ptp_label, QLabel)
        assert isinstance(role_label, QLabel)

        try:
            if not grabber.is_device_valid:
                self._set_ptp_na(slot)
                return
        except ic4.IC4Exception:
            self._set_ptp_na(slot)
            return

        enable_str = None
        status_str = None
        enable_error = None
        status_error = None
        try:
            enable_str = grabber.device_property_map.get_value_str("PtpEnable")
        except Exception as exc:
            enable_error = exc
        try:
            status_str = grabber.device_property_map.get_value_str("PtpStatus")
        except Exception as exc:
            status_error = exc

        if enable_error is not None or status_error is not None:
            if enable_error is not None and status_error is not None:
                error_message = (
                    f"{type(enable_error).__name__}: {enable_error}; "
                    f"{type(status_error).__name__}: {status_error}"
                )
            elif enable_error is not None:
                error_message = f"{type(enable_error).__name__}: {enable_error}"
            else:
                error_message = f"{type(status_error).__name__}: {status_error}"
            last_error = slot.get("ptp_last_error")
            if error_message != last_error:
                self._log_ptp(slot_index, f"read failed exc={error_message}")
                slot["ptp_last_error"] = error_message

        enable_text = "PTP: N/A"
        if enable_str is not None:
            normalized = str(enable_str).strip().lower()
            if normalized in {"true", "1", "on"}:
                enable_text = "PTP: ON"
            elif normalized in {"false", "0", "off"}:
                enable_text = "PTP: OFF"

        role_text = "Role: N/A"
        if status_str is not None:
            status = str(status_str).strip()
            if status == "Master":
                role_text = "Role: Master"
            elif status == "Slave":
                role_text = "Role: Slave"
            else:
                role_text = "Role: Unknown"

        ptp_label.setText(enable_text)
        role_label.setText(role_text)
        if enable_error is None and status_error is None:
            slot["ptp_last_error"] = None
            if log_success:
                role_value = role_text.replace("Role: ", "")
                self._log_ptp(slot_index, f"enable={enable_str} status={status_str} role={role_value}")

    @staticmethod
    def _log(slot_index: int, message: str) -> None:
        print(f"[multi-view][slot{slot_index + 1}] {message}")

    @staticmethod
    def _log_ptp(slot_index: int, message: str) -> None:
        print(f"[ptp][slot{slot_index + 1}] {message}")

    # -------------------------------------------------------------------------
    # 録画制御
    # -------------------------------------------------------------------------

    def _on_start_recording(self) -> None:
        """録画開始ボタンのクリックハンドラ"""
        # 有効なカメラがあるスロットを収集
        active_slots = [
            slot for slot in self.slots
            if slot.get("channel_id") is not None
            and isinstance(slot.get("grabber"), ic4.Grabber)
            and slot["grabber"].is_device_valid
        ]

        if not active_slots:
            QMessageBox.warning(
                self,
                "No Cameras",
                "No cameras are connected. Please select cameras first.",
            )
            return

        start_delay_s = self.rec_start_after_sec.value()
        duration_s = self.rec_duration_sec.value()

        # UI無効化
        self._set_recording_ui_enabled(False)

        # タブロック
        self._recording = True
        self.tabs_lock_changed.emit(True)

        # 録画準備開始
        success = self._recording_controller.prepare(
            slots=active_slots,
            start_delay_s=float(start_delay_s),
            duration_s=float(duration_s),
        )

        if not success:
            error_msg = self._recording_controller.get_error_message()
            QMessageBox.critical(
                self,
                "Recording Failed",
                f"Failed to start recording:\n{error_msg}",
            )
            self._on_recording_finished()
            return

        # 録画スレッド開始
        self._recording_controller.start()

    def _on_recording_state_changed(self, state: RecordingState, message: str) -> None:
        """RecordingControllerからの状態変更コールバック（別スレッドから呼ばれる可能性あり）"""
        # QTimerを使ってメインスレッドで実行
        QTimer.singleShot(0, lambda: self._update_recording_ui(state, message))

    def _update_recording_ui(self, state: RecordingState, message: str) -> None:
        """録画UIを更新（メインスレッドで実行）"""
        self.rec_status_label.setText(message)

        if state == RecordingState.IDLE:
            self._on_recording_finished()
        elif state == RecordingState.ERROR:
            self._on_recording_finished()

    def _on_recording_finished(self) -> None:
        """録画終了時の処理"""
        self._recording = False
        self.tabs_lock_changed.emit(False)
        self._set_recording_ui_enabled(True)

        # プレビュー再開
        self.resume_selected()

    def _set_recording_ui_enabled(self, enabled: bool) -> None:
        """録画関連UIの有効/無効を切り替え"""
        self.rec_start_after_sec.setEnabled(enabled)
        self.rec_duration_sec.setEnabled(enabled)
        self.rec_start_button.setEnabled(enabled)
        self.recording_checkbox.setEnabled(enabled)
        self.lock_tabs_checkbox.setEnabled(enabled)

        if enabled:
            self.rec_status_label.setText("Ready")
