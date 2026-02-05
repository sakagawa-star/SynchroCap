from __future__ import annotations

from typing import Optional

import imagingcontrol4 as ic4
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from channel_registry import ChannelRegistry, ChannelEntry, DeviceIdentity
from device_resolver import resolve_status


class ChannelIdSpinBox(QSpinBox):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setRange(1, 99)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def textFromValue(self, value: int) -> str:
        return f"{value:02d}"

    def valueFromText(self, text: str) -> int:
        try:
            return int(text)
        except ValueError:
            return 0


class ChannelManagerWidget(QWidget):
    def __init__(self, registry: ChannelRegistry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.selected_channel_id: Optional[int] = None
        self.selected_device: Optional[DeviceIdentity] = None
        self.selection_grabber = ic4.Grabber()

        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Channel", "Camera", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)

        main_layout.addWidget(self.table, 2)

        side_panel = QVBoxLayout()

        group = QGroupBox("Channel Details", self)
        form = QFormLayout(group)

        self.channel_spin = ChannelIdSpinBox(self)
        self.channel_spin.valueChanged.connect(self.update_action_state)
        form.addRow("Channel ID", self.channel_spin)

        self.camera_label = QLabel("No camera selected", self)
        self.camera_label.setWordWrap(True)
        self.select_camera_btn = QPushButton("Select Camera...", self)
        self.select_camera_btn.clicked.connect(self.on_select_camera)

        camera_container = QWidget(self)
        camera_layout = QVBoxLayout(camera_container)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.addWidget(self.camera_label)
        camera_layout.addWidget(self.select_camera_btn)
        form.addRow("Camera", camera_container)

        buttons_layout = QHBoxLayout()
        self.register_btn = QPushButton("Register", self)
        self.update_btn = QPushButton("Update", self)
        self.delete_btn = QPushButton("Delete", self)

        self.register_btn.clicked.connect(self.on_register)
        self.update_btn.clicked.connect(self.on_update)
        self.delete_btn.clicked.connect(self.on_delete)

        buttons_layout.addWidget(self.register_btn)
        buttons_layout.addWidget(self.update_btn)
        buttons_layout.addWidget(self.delete_btn)

        form.addRow(buttons_layout)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #b00020;")
        form.addRow(self.error_label)

        side_panel.addWidget(group)
        side_panel.addStretch(1)

        main_layout.addLayout(side_panel, 1)

        self.update_action_state()

    def refresh_table(self) -> None:
        entries = self.registry.list_channels()
        statuses = {}
        status_unknown = False
        try:
            statuses = resolve_status(entries)
        except Exception:
            status_unknown = True

        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            channel_item = QTableWidgetItem(entry.channel_label)
            channel_item.setData(Qt.ItemDataRole.UserRole, entry.channel_id)

            camera_item = QTableWidgetItem(self.format_device(entry.device_identity))
            if status_unknown:
                status_text = "Unknown"
            else:
                status_text = "Connected" if statuses.get(entry.channel_id) else "Disconnected"
            status_item = QTableWidgetItem(status_text)

            for item in (channel_item, camera_item, status_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row, 0, channel_item)
            self.table.setItem(row, 1, camera_item)
            self.table.setItem(row, 2, status_item)

        self.table.resizeColumnsToContents()
        self._restore_selection()
        self.update_action_state()

    def on_table_selection_changed(self) -> None:
        selected_items = self.table.selectedItems()
        if not selected_items:
            self.selected_channel_id = None
            self.selected_device = None
            self.camera_label.setText("No camera selected")
            self.update_action_state()
            return

        row = self.table.currentRow()
        channel_item = self.table.item(row, 0)
        if channel_item is None:
            return

        channel_id = channel_item.data(Qt.ItemDataRole.UserRole)
        entry = self.registry.get(int(channel_id))
        if not entry:
            return

        self.selected_channel_id = entry.channel_id
        self.channel_spin.setValue(entry.channel_id)
        self.selected_device = entry.device_identity
        self.camera_label.setText(self.format_device(entry.device_identity))
        self.update_action_state()

    def on_select_camera(self) -> None:
        dlg = ic4.pyside6.DeviceSelectionDialog(self.selection_grabber, parent=self)
        result = dlg.exec()
        try:
            if result != 1:
                return

            try:
                info = self.selection_grabber.device_info
                identity = self.device_identity_from_info(info)
                self.selected_device = identity
                self.camera_label.setText(self.format_device(identity))
            except ic4.IC4Exception as exc:
                QMessageBox.critical(self, "", f"{exc}", QMessageBox.StandardButton.Ok)
        finally:
            try:
                self.selection_grabber.device_close()
            except ic4.IC4Exception:
                pass

        self.update_action_state()

    def on_register(self) -> None:
        channel_id = self.channel_spin.value()
        if self.selected_device is None:
            self.error_label.setText("Select a camera before registering.")
            return

        existing_channel = self.registry.find_channel_id_by_device(self.selected_device)
        if existing_channel is not None and existing_channel != channel_id:
            if not self._confirm_channel_change(existing_channel, channel_id):
                return

        try:
            if existing_channel is not None:
                self.registry.move_device_to_channel(self.selected_device, channel_id)
            else:
                self.registry.add(channel_id, self.selected_device)
            self.registry.save()
        except ValueError as exc:
            QMessageBox.warning(self, "", f"{exc}", QMessageBox.StandardButton.Ok)
            return

        self.selected_channel_id = channel_id
        self.refresh_table()

    def on_update(self) -> None:
        if self.selected_channel_id is None:
            return
        if self.selected_device is None:
            self.error_label.setText("Select a camera before updating.")
            return

        new_channel_id = self.channel_spin.value()

        if new_channel_id != self.selected_channel_id and self.registry.is_used(new_channel_id):
            entry = self.registry.get(new_channel_id)
            if entry and not self._is_same_device(entry.device_identity, self.selected_device):
                QMessageBox.warning(
                    self,
                    "",
                    f"Channel {new_channel_id:02d} is already registered to another device.",
                    QMessageBox.StandardButton.Ok,
                )
                return

        existing_channel = self.registry.find_channel_id_by_device(self.selected_device)
        if existing_channel is not None and existing_channel not in (self.selected_channel_id, new_channel_id):
            if not self._confirm_channel_change(existing_channel, new_channel_id):
                return

        try:
            if existing_channel is not None and existing_channel != self.selected_channel_id:
                self.registry.move_device_to_channel(self.selected_device, new_channel_id)
            else:
                if new_channel_id != self.selected_channel_id:
                    self.registry.update_channel_id(self.selected_channel_id, new_channel_id)
                self.registry.update_device_identity(new_channel_id, self.selected_device)
            self.registry.save()
        except ValueError as exc:
            QMessageBox.warning(self, "", f"{exc}", QMessageBox.StandardButton.Ok)
            return

        self.selected_channel_id = new_channel_id
        self.refresh_table()

    def on_delete(self) -> None:
        if self.selected_channel_id is None:
            return

        channel_label = f"{self.selected_channel_id:02d}"
        if (
            QMessageBox.question(
                self,
                "",
                f"Delete channel {channel_label}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        try:
            self.registry.remove(self.selected_channel_id)
            self.registry.save()
        except ValueError as exc:
            QMessageBox.warning(self, "", f"{exc}", QMessageBox.StandardButton.Ok)
            return

        self.selected_channel_id = None
        self.selected_device = None
        self.camera_label.setText("No camera selected")
        self.refresh_table()

    def update_action_state(self) -> None:
        channel_id = self.channel_spin.value()
        used = self.registry.is_used(channel_id)
        channel_entry = self.registry.get(channel_id)
        existing_channel_for_device = (
            self.registry.find_channel_id_by_device(self.selected_device)
            if self.selected_device is not None
            else None
        )

        if self.selected_device is None:
            self.error_label.setText("Select a camera to continue.")
        elif used and (channel_entry is None or not self._is_same_device(channel_entry.device_identity, self.selected_device)):
            self.error_label.setText("Channel ID already used.")
        elif existing_channel_for_device is not None and existing_channel_for_device not in (self.selected_channel_id, channel_id):
            self.error_label.setText(f"Camera already registered to channel {existing_channel_for_device:02d}.")
        else:
            self.error_label.setText("")

        can_register = False
        if self.selected_device is not None:
            if not used:
                can_register = True
            elif channel_entry and self._is_same_device(channel_entry.device_identity, self.selected_device):
                can_register = True

        self.register_btn.setEnabled(can_register)

        can_update = self.selected_channel_id is not None and self.selected_device is not None
        new_channel_id_conflicts = (
            channel_id != self.selected_channel_id
            and self.registry.is_used(channel_id)
            and not (channel_entry and self._is_same_device(channel_entry.device_identity, self.selected_device))
        )
        if can_update and new_channel_id_conflicts:
            can_update = False

        self.update_btn.setEnabled(can_update)
        self.delete_btn.setEnabled(self.selected_channel_id is not None)

    def _restore_selection(self) -> None:
        if self.selected_channel_id is None:
            return

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == self.selected_channel_id:
                self.table.setCurrentItem(item)
                return

        self.selected_channel_id = None
        self.selected_device = None
        self.camera_label.setText("No camera selected")

    @staticmethod
    def device_identity_from_info(info: ic4.DeviceInfo) -> DeviceIdentity:
        serial = ChannelManagerWidget._first_value(info, ("serial", "serial_number", "unique_id"))
        model = ChannelManagerWidget._first_value(info, ("model_name", "model", "display_name"))
        unique_name = ChannelManagerWidget._first_value(info, ("unique_name", "name"))
        return DeviceIdentity(serial=serial, model=model, unique_name=unique_name)

    @staticmethod
    def format_device(identity: DeviceIdentity) -> str:
        label = identity.model or "Unknown Model"
        if identity.serial:
            label = f"{label} ({identity.serial})"
        elif identity.unique_name:
            label = f"{label} ({identity.unique_name})"
        return label

    @staticmethod
    def _first_value(info: ic4.DeviceInfo, names: tuple[str, ...]) -> str:
        for name in names:
            if hasattr(info, name):
                value = getattr(info, name)
                if value:
                    return str(value)
        return ""

    @staticmethod
    def _is_same_device(a: DeviceIdentity, b: DeviceIdentity) -> bool:
        if a is None or b is None:
            return False

        serial_a = (a.serial or "").strip()
        serial_b = (b.serial or "").strip()
        if serial_a and serial_b and serial_a == serial_b:
            return True
        if serial_a or serial_b:
            return False

        unique_a = (a.unique_name or "").strip()
        unique_b = (b.unique_name or "").strip()
        if unique_a and unique_b and unique_a == unique_b:
            return True
        return False

    def _confirm_channel_change(self, from_channel: int, to_channel: int) -> bool:
        return (
            QMessageBox.question(
                self,
                "チャンネル変更",
                f"このカメラは現在 Channel {from_channel:02d} に登録されています。\n"
                f"Channel {to_channel:02d} に変更しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )
