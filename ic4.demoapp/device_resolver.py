from __future__ import annotations

from typing import Iterable, Optional

import imagingcontrol4 as ic4

from channel_registry import ChannelEntry


def resolve_status(entries: list[ChannelEntry]) -> dict[int, bool]:
    try:
        devices = list(ic4.DeviceEnum.devices())
    except ic4.IC4Exception:
        return {entry.channel_id: False for entry in entries}

    return {
        entry.channel_id: _find_device_for_entry(entry, devices) is not None
        for entry in entries
    }


def find_device_for_entry(entry: ChannelEntry) -> Optional[ic4.DeviceInfo]:
    try:
        devices = list(ic4.DeviceEnum.devices())
    except ic4.IC4Exception:
        return None

    return _find_device_for_entry(entry, devices)


def _find_device_for_entry(
    entry: ChannelEntry,
    devices: Iterable[ic4.DeviceInfo],
) -> Optional[ic4.DeviceInfo]:
    serial = (entry.device_identity.serial or "").strip()
    unique_name = (entry.device_identity.unique_name or "").strip()

    if serial:
        for info in devices:
            if _first_value(info, ("serial", "serial_number", "unique_id")) == serial:
                return info
        return None

    if unique_name:
        for info in devices:
            if _first_value(info, ("unique_name", "name", "display_name")) == unique_name:
                return info
    return None


def _first_value(obj: object, names: Iterable[str]) -> str:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value:
                return str(value)
    return ""
