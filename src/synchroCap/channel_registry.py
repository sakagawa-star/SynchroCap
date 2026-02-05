from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class DeviceIdentity:
    serial: str
    model: str
    unique_name: str = ""


@dataclass
class ChannelEntry:
    channel_id: int
    device_identity: DeviceIdentity
    notes: str = ""

    @property
    def channel_label(self) -> str:
        return f"{self.channel_id:02d}"

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "channel_label": self.channel_label,
            "device_identity": {
                "serial": self.device_identity.serial,
                "model": self.device_identity.model,
                "unique_name": self.device_identity.unique_name or "",
            },
            "notes": self.notes or "",
        }


class ChannelRegistry:
    VERSION = 1

    def __init__(self, path: str) -> None:
        self.path = path
        self._entries: Dict[int, ChannelEntry] = {}

    def load(self) -> None:
        self._entries = {}
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict):
            raise ValueError("Invalid channels.json format: root is not an object.")

        channels = data.get("channels", [])
        if not isinstance(channels, list):
            raise ValueError("Invalid channels.json format: channels is not a list.")

        for item in channels:
            entry = self._entry_from_dict(item)
            if entry.channel_id in self._entries:
                raise ValueError(f"Duplicate channel_id detected: {entry.channel_id}")
            for existing in self._entries.values():
                if self._matches_device(existing.device_identity, entry.device_identity):
                    raise ValueError(
                        f"Duplicate device assignment detected for channel {existing.channel_id:02d}."
                    )
            self._entries[entry.channel_id] = entry

    def save(self) -> None:
        payload = {
            "version": self.VERSION,
            "updated_at": self._timestamp_now(),
            "channels": [entry.to_dict() for entry in self.list_channels()],
        }
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)

    def list_channels(self) -> List[ChannelEntry]:
        return [self._entries[key] for key in sorted(self._entries)]

    def add(self, channel_id: int, device_identity: DeviceIdentity, notes: str = "") -> None:
        self._validate_channel_id(channel_id)
        if channel_id in self._entries:
            raise ValueError(f"Channel ID {channel_id:02d} is already registered.")
        existing_channel = self.find_channel_id_by_device(device_identity)
        if existing_channel is not None:
            raise ValueError(
                f"Device already registered to channel {existing_channel:02d}."
            )
        self._entries[channel_id] = ChannelEntry(
            channel_id=channel_id,
            device_identity=device_identity,
            notes=notes or "",
        )

    def update_channel_id(self, old_id: int, new_id: int) -> None:
        self._validate_channel_id(new_id)
        if old_id not in self._entries:
            raise ValueError(f"Channel ID {old_id:02d} not found.")
        if new_id in self._entries and new_id != old_id:
            raise ValueError(f"Channel ID {new_id:02d} is already registered.")
        entry = self._entries.pop(old_id)
        entry.channel_id = new_id
        self._entries[new_id] = entry

    def update_device_identity(self, channel_id: int, device_identity: DeviceIdentity) -> None:
        if channel_id not in self._entries:
            raise ValueError(f"Channel ID {channel_id:02d} not found.")
        existing_channel = self.find_channel_id_by_device(device_identity)
        if existing_channel is not None and existing_channel != channel_id:
            raise ValueError(
                f"Device already registered to channel {existing_channel:02d}."
            )
        self._entries[channel_id].device_identity = device_identity

    def remove(self, channel_id: int) -> None:
        if channel_id not in self._entries:
            raise ValueError(f"Channel ID {channel_id:02d} not found.")
        del self._entries[channel_id]

    def is_used(self, channel_id: int) -> bool:
        return channel_id in self._entries

    def get(self, channel_id: int) -> Optional[ChannelEntry]:
        return self._entries.get(channel_id)

    def find_channel_id_by_device(self, device_identity: DeviceIdentity) -> Optional[int]:
        for channel_id, entry in self._entries.items():
            if self._matches_device(entry.device_identity, device_identity):
                return channel_id
        return None

    def move_device_to_channel(self, device_identity: DeviceIdentity, new_channel_id: int, notes: str = "") -> None:
        self._validate_channel_id(new_channel_id)

        existing_channel_for_device = self.find_channel_id_by_device(device_identity)

        if new_channel_id in self._entries:
            current_entry = self._entries[new_channel_id]
            if not self._matches_device(current_entry.device_identity, device_identity):
                raise ValueError(f"Channel ID {new_channel_id:02d} is already registered to another device.")

        if existing_channel_for_device is None:
            if new_channel_id in self._entries:
                raise ValueError(f"Channel ID {new_channel_id:02d} is already registered.")
            self.add(new_channel_id, device_identity, notes)
            return

        entry = self._entries.pop(existing_channel_for_device)
        entry.channel_id = new_channel_id
        entry.device_identity = device_identity
        if notes:
            entry.notes = notes
        self._entries[new_channel_id] = entry

    def _entry_from_dict(self, data: object) -> ChannelEntry:
        if not isinstance(data, dict):
            raise ValueError("Invalid channel entry format.")

        channel_id_raw = data.get("channel_id")
        if channel_id_raw is None:
            raise ValueError("Channel entry missing channel_id.")
        channel_id = int(channel_id_raw)
        self._validate_channel_id(channel_id)

        device_identity = data.get("device_identity", {})
        if not isinstance(device_identity, dict):
            raise ValueError("Invalid device_identity format.")

        serial = device_identity.get("serial") or ""
        model = device_identity.get("model") or ""
        unique_name = device_identity.get("unique_name") or ""

        notes = data.get("notes") or ""

        return ChannelEntry(
            channel_id=channel_id,
            device_identity=DeviceIdentity(
                serial=str(serial),
                model=str(model),
                unique_name=str(unique_name),
            ),
            notes=str(notes),
        )

    def _validate_channel_id(self, channel_id: int) -> None:
        if not 1 <= channel_id <= 99:
            raise ValueError("Channel ID must be between 1 and 99.")

    def _timestamp_now(self) -> str:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        return timestamp.isoformat().replace("+00:00", "Z")

    def _matches_device(self, existing_identity: DeviceIdentity, device_identity: DeviceIdentity) -> bool:
        serial = (device_identity.serial or "").strip()
        if serial:
            return (existing_identity.serial or "").strip() == serial

        unique_name = (device_identity.unique_name or "").strip()
        if unique_name:
            return (existing_identity.unique_name or "").strip() == unique_name

        return False
