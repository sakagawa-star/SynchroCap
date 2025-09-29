"""Synchronized still capture for DFK 33GR0234 cameras using PTP and action commands."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import imagingcontrol4 as ic4
except ImportError as exc:  # pragma: no cover
    print("Failed to import imagingcontrol4.")
    print("Install IC Imaging Control 4 and ensure PYTHONPATH is configured.")
    print(f"Import error: {exc}")
    sys.exit(1)

ACTION_DELAY_NS = 2_000_000_000  # 2 seconds
TARGET_MODEL = "DFK 33GR0234"
ACTION_DEVICE_KEY_VALUE = 0x12345678
ACTION_GROUP_KEY_VALUE = 0x1
ACTION_GROUP_MASK_VALUE = 0x1

PTP_ENABLE_NAMES = (
    ic4.PropId.PTP_ENABLE,
    "GevIEEE1588",
    "PtpEnable",
)
PTP_STATUS_NAMES = (
    ic4.PropId.PTP_STATUS,
    "GevIEEE1588StatusLatched",
    "GevIEEE1588Status",
    "PtpStatusLatched",
    "PtpStatus",
)
PTP_LATCH_COMMANDS = (
    ic4.PropId.TIMESTAMP_LATCH,
    "GevIEEE1588DataSetLatch",
    "PtpDataSetLatch",
)
PTP_OFFSET_NAMES = (
    "GevIEEE1588OffsetFromMaster",
    "PtpOffsetFromMaster",
)

ENABLE_KEYWORD_GROUPS = ("ptp enable", "ieee1588 enable", "1588 enable")
STATUS_KEYWORD_GROUPS = ("ptp status", "ieee1588 status", "1588 status")
OFFSET_KEYWORD_GROUPS = ("ptp offset", "ieee1588 offset", "1588 offset")
LATCH_KEYWORD_GROUPS = ("ptp latch", "ieee1588 latch", "1588 latch")

TIMESTAMP_LATCH_COMMANDS = (
    ic4.PropId.TIMESTAMP_LATCH,
    "GevTimestampControlLatch",
    "TimestampControlLatch",
    "TimestampLatch",
)
TIMESTAMP_NAMES = (
    ic4.PropId.TIMESTAMP_LATCH_VALUE,
    "GevTimestampValue",
    "TimestampValue",
    "DeviceTimestamp",
)

TRIGGER_SELECTOR_NAMES = (
    ic4.PropId.TRIGGER_SELECTOR,
    "TriggerSelector",
)
TRIGGER_MODE_NAMES = (
    ic4.PropId.TRIGGER_MODE,
    "TriggerMode",
)
TRIGGER_SOURCE_NAMES = (
    ic4.PropId.TRIGGER_SOURCE,
    "TriggerSource",
)
TRIGGER_SOFTWARE_NAMES = (
    ic4.PropId.TRIGGER_SOFTWARE,
    "TriggerSoftware",
)
ACTION_SELECTOR_NAMES = (
    ic4.PropId.ACTION_SELECTOR,
    "ActionSelector",
)
ACTION_DEVICE_NAMES = (
    ic4.PropId.ACTION_DEVICE_KEY,
    "ActionDeviceKey",
)
ACTION_GROUP_NAMES = (
    ic4.PropId.ACTION_GROUP_KEY,
    "ActionGroupKey",
)
ACTION_MASK_NAMES = (
    ic4.PropId.ACTION_GROUP_MASK,
    "ActionGroupMask",
)


@dataclass
class DeviceSession:
    label: str
    serial: str
    grabber: ic4.Grabber
    sink: ic4.SnapSink
    prop_map: Any
    prop_names: list[str]
    current_time: Optional[int]


@dataclass
class InterfaceSession:
    interface: Any
    prop_names: list[str]


def first_value(obj: object, names: Iterable[str]) -> Optional[str]:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value:
                return str(value)
    return None


def collect_property_names(prop_map: Any) -> list[str]:
    names: list[str] = []
    try:
        all_props = getattr(prop_map, "all", None)
        if all_props is None:
            return names
        for prop in all_props:
            name = getattr(prop, "name", None)
            if name:
                names.append(str(name))
    except Exception:  # pragma: no cover
        return names
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def find_property_name(prop_names: Iterable[str], explicit: Iterable[str], keyword_groups: Iterable[str]) -> Optional[str]:
    for name in explicit:
        if name.lower() in (p.lower() for p in prop_names):
            return name
    for group in keyword_groups:
        tokens = group.split()
        for candidate in prop_names:
            lower = candidate.lower()
            if all(token in lower for token in tokens):
                return candidate
    return None


def set_property(prop_map: Any, prop_names: list[str], explicit: Iterable[str], keywords: Iterable[str], value: Any) -> Optional[str]:
    name = find_property_name(prop_names, explicit, keywords)
    if not name:
        return None
    setter = getattr(prop_map, "try_set_value", None)
    if callable(setter):
        try:
            if setter(name, value):
                return name
        except ic4.IC4Exception:
            return None
    try:
        prop_map.set_value(name, value)
        return name
    except ic4.IC4Exception:
        return None


def read_bool(prop_map: Any, name: str) -> Optional[bool]:
    getter = getattr(prop_map, "try_get_value_bool", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return bool(value)
        except ic4.IC4Exception:
            return None
    try:
        return bool(prop_map.get_value_bool(name))
    except ic4.IC4Exception:
        return None


def read_int(prop_map: Any, name: str) -> Optional[int]:
    getter = getattr(prop_map, "try_get_value_int", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return int(value)
        except ic4.IC4Exception:
            return None
    try:
        return int(prop_map.get_value_int(name))
    except ic4.IC4Exception:
        return None


def read_str(prop_map: Any, name: str) -> Optional[str]:
    getter = getattr(prop_map, "try_get_value_str", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return str(value)
        except ic4.IC4Exception:
            return None
    try:
        return prop_map.get_value_str(name)
    except ic4.IC4Exception:
        return None


def try_enable_ptp(prop_map: Any, prop_names: list[str]) -> Optional[str]:
    name = find_property_name(prop_names, PTP_ENABLE_NAMES, ENABLE_KEYWORD_GROUPS)
    if not name:
        print("PTP enable property not found on device.")
        return None
    setter = getattr(prop_map, "try_set_value", None)
    if callable(setter):
        try:
            result = setter(name, True)
            if result:
                return name
        except ic4.IC4Exception as exc:
            print(f"Failed to enable PTP using property '{name}'.")
            print(f"Error: {exc}")
            return None
    try:
        prop_map.set_value(name, True)
        return name
    except ic4.IC4Exception as exc:
        print(f"Failed to enable PTP using property '{name}'.")
        print(f"Error: {exc}")
        return None


def latch_command(prop_map: Any, prop_names: list[str], explicit: Iterable[str], keywords: Iterable[str]) -> Optional[str]:
    name = find_property_name(prop_names, explicit, keywords)
    if not name:
        return None
    try:
        prop_map.execute_command(name)
        return name
    except ic4.IC4Exception:
        return None


def prepare_device(info: ic4.DeviceInfo, label: str) -> Optional[DeviceSession]:
    serial = first_value(info, ("serial", "serial_number", "unique_id")) or "Unknown"
    print(f"Device {label} serial: {serial}")

    grabber = ic4.Grabber()
    try:
        grabber.device_open(info)
        print(f"Device {label} opened successfully.")
    except ic4.IC4Exception as exc:
        print(f"Failed to open device {label}.")
        print(f"Error: {exc}")
        return None

    prop_map = grabber.device_property_map
    prop_names = collect_property_names(prop_map)

    ptp_name = try_enable_ptp(prop_map, prop_names)
    if ptp_name:
        print(f"Device {label} PTP enable property: {ptp_name}")
    latch_command(prop_map, prop_names, PTP_LATCH_COMMANDS, LATCH_KEYWORD_GROUPS)
    status = read_str(prop_map, find_property_name(prop_names, PTP_STATUS_NAMES, STATUS_KEYWORD_GROUPS) or "")
    if status:
        print(f"Device {label} PTP status: {status}")
    offset_name = find_property_name(prop_names, PTP_OFFSET_NAMES, OFFSET_KEYWORD_GROUPS)
    if offset_name:
        offset_value = read_int(prop_map, offset_name)
        if offset_value is not None:
            print(f"Device {label} PTP offset: {offset_value} ns")

    set_property(prop_map, prop_names, ACTION_SELECTOR_NAMES, ("action selector",), 0)
    set_property(prop_map, prop_names, ACTION_DEVICE_NAMES, ("action device key",), ACTION_DEVICE_KEY_VALUE)
    set_property(prop_map, prop_names, ACTION_GROUP_NAMES, ("action group key",), ACTION_GROUP_KEY_VALUE)
    set_property(prop_map, prop_names, ACTION_MASK_NAMES, ("action group mask",), ACTION_GROUP_MASK_VALUE)
    set_property(prop_map, prop_names, TRIGGER_SELECTOR_NAMES, ("trigger selector",), "FrameStart")
    set_property(prop_map, prop_names, TRIGGER_MODE_NAMES, ("trigger mode",), "On")
    set_property(prop_map, prop_names, TRIGGER_SOURCE_NAMES, ("trigger source",), "Action0")

    latch_command(prop_map, prop_names, TIMESTAMP_LATCH_COMMANDS, ("timestamp latch",))
    current_time = read_int(prop_map, find_property_name(prop_names, TIMESTAMP_NAMES, ("timestamp",)) or "")

    try:
        sink = ic4.SnapSink()
        grabber.stream_setup(sink)
    except ic4.IC4Exception as exc:
        print(f"Failed to set up SnapSink for device {label}.")
        print(f"Error: {exc}")
        try:
            grabber.device_close()
        except ic4.IC4Exception:
            pass
        return None

    return DeviceSession(
        label=label,
        serial=serial,
        grabber=grabber,
        sink=sink,
        prop_map=prop_map,
        prop_names=prop_names,
        current_time=current_time,
    )


def execute_interface_action(interface: Any, prop_names: list[str], start_time_ns: int) -> bool:
    prop_map = interface.property_map
    set_property(prop_map, prop_names, ACTION_DEVICE_NAMES, ("action device key",), ACTION_DEVICE_KEY_VALUE)
    set_property(prop_map, prop_names, ACTION_GROUP_NAMES, ("action group key",), ACTION_GROUP_KEY_VALUE)
    set_property(prop_map, prop_names, ACTION_MASK_NAMES, ("action group mask",), ACTION_GROUP_MASK_VALUE)
    set_property(prop_map, prop_names, ("ActionScheduledTimeEnable",), ("scheduled time enable",), True)
    name = find_property_name(prop_names, ("ActionScheduledTime",), ("scheduled time",))
    if not name:
        print("Interface is missing ActionScheduledTime property.")
        return False
    try:
        interface.property_map.set_value(name, start_time_ns)
    except ic4.IC4Exception as exc:
        print("Failed to set interface scheduled time.")
        print(f"Error: {exc}")
        return False
    command = find_property_name(prop_names, ("ActionCommand",), ("action command",))
    if not command:
        print("Interface is missing ActionCommand property.")
        return False
    try:
        interface.property_map.execute_command(command)
        set_property(prop_map, prop_names, ("ActionScheduledTimeEnable",), ("scheduled time enable",), False)
        return True
    except ic4.IC4Exception as exc:
        print(f"Failed to execute interface action command '{command}'.")
        print(f"Error: {exc}")
        return False


def capture_with_fallback(session: DeviceSession, start_time_ns: int) -> Optional[Path]:
    timeout_ms = max(int(ACTION_DELAY_NS / 1_000_000) + 5000, 3000)
    buffer: Optional[ic4.ImageBuffer]
    try:
        buffer = session.sink.snap_single(timeout_ms)
    except ic4.IC4Exception as exc:
        print(f"Device {session.label} timed out waiting for action command.")
        print(f"Error: {exc}")
        buffer = None

    if buffer is None:
        print(f"Device {session.label} falling back to software trigger.")
        set_property(session.prop_map, session.prop_names, TRIGGER_SOURCE_NAMES, ("trigger source",), "Software")
        set_property(session.prop_map, session.prop_names, TRIGGER_MODE_NAMES, ("trigger mode",), "On")
        trigger_name = find_property_name(session.prop_names, TRIGGER_SOFTWARE_NAMES, ("trigger software",))
        if trigger_name:
            try:
                session.prop_map.execute_command(trigger_name)
            except ic4.IC4Exception as exc:
                print(f"Device {session.label} software trigger failed.")
                print(f"Error: {exc}")
        try:
            buffer = session.sink.snap_single(5000)
        except ic4.IC4Exception as exc:
            print(f"Device {session.label} still failed to deliver a frame.")
            print(f"Error: {exc}")
            buffer = None
        set_property(session.prop_map, session.prop_names, TRIGGER_SOURCE_NAMES, ("trigger source",), "Action0")
        set_property(session.prop_map, session.prop_names, TRIGGER_MODE_NAMES, ("trigger mode",), "On")

    if buffer is None:
        return None

    output_path = Path(f"camera_{session.serial}.png")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        buffer.save_as_png(str(output_path))
        return output_path.resolve()
    except ic4.IC4Exception as exc:
        print(f"Device {session.label} failed to save captured frame.")
        print(f"Error: {exc}")
        return None


def cleanup_session(session: DeviceSession) -> None:
    try:
        session.grabber.stream_stop()
    except ic4.IC4Exception:
        pass
    try:
        session.grabber.device_close()
        print(f"Device {session.label} closed successfully.")
    except ic4.IC4Exception:
        pass


def main() -> None:
    try:
        ic4.Library.init()
    except ic4.IC4Exception as exc:
        print("Failed to initialize IC Imaging Control 4.")
        print(f"Error: {exc}")
        return

    sessions: list[DeviceSession] = []
    interfaces: dict[int, InterfaceSession] = {}
    try:
        devices = [info for info in ic4.DeviceEnum.devices() if TARGET_MODEL in (first_value(info, ("model_name", "model", "display_name")) or "")]
        if not devices:
            print(f"No {TARGET_MODEL} cameras detected.")
            return
        print(f"Detected {len(devices)} {TARGET_MODEL} device(s).")

        for index, info in enumerate(devices, start=1):
            session = prepare_device(info, f"#{index}")
            if session:
                sessions.append(session)
                interface = getattr(info, "interface", None)
                if interface is not None:
                    interfaces[id(interface)] = InterfaceSession(interface, collect_property_names(interface.property_map))

        if not sessions:
            print("No devices ready for capture.")
            return

        times = [s.current_time for s in sessions if s.current_time is not None]
        start_time_ns = (min(times) if times else int(time.time() * 1_000_000_000)) + ACTION_DELAY_NS

        for interface_session in interfaces.values():
            execute_interface_action(interface_session.interface, interface_session.prop_names, start_time_ns)

        for session in sessions:
            path = capture_with_fallback(session, start_time_ns)
            if path:
                print(f"Device {session.label} scheduled trigger time: {start_time_ns} ns")
                print(f"Device {session.label} image saved to: {path}")
            else:
                print(f"Device {session.label} failed to capture image.")
    finally:
        for session in sessions:
            cleanup_session(session)
        ic4.Library.exit()
        print("Library shutdown complete.")


if __name__ == "__main__":
    main()
