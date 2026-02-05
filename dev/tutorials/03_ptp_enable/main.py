"""Enable PTP on Imaging Source DFK 33GR0234 cameras and report status."""

from __future__ import annotations

import sys
from typing import Any, Iterable, Optional

try:
    import imagingcontrol4 as ic4
except ImportError as exc:  # pragma: no cover
    print("Failed to import imagingcontrol4.")
    print("Install IC Imaging Control 4 and ensure PYTHONPATH is configured.")
    print(f"Import error: {exc}")
    sys.exit(1)

TARGET_MODEL = "DFK 33GR0234"
PTP_ENABLE_NAMES = (
    "GevIEEE1588",
    "PtpEnable",
)
PTP_STATUS_NAMES = (
    "GevIEEE1588StatusLatched",
    "GevIEEE1588Status",
    "PtpStatusLatched",
    "PtpStatus",
)
PTP_LATCH_COMMANDS = (
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


def first_value(obj: object, names: Iterable[str]) -> Optional[str]:
    """Return the first truthy attribute value found on obj."""
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
    # Preserve order while removing duplicates
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def property_exists(prop_names: Iterable[str], candidate: str) -> bool:
    candidate_lower = candidate.lower()
    for name in prop_names:
        if name.lower() == candidate_lower:
            return True
    return False


def find_property_name(prop_names: Iterable[str], explicit: Iterable[str], keyword_groups: Iterable[str]) -> Optional[str]:
    for name in explicit:
        if property_exists(prop_names, name):
            return name
    for group in keyword_groups:
        tokens = group.split()
        for name in prop_names:
            lower = name.lower()
            if all(token in lower for token in tokens):
                return name
    return None


def is_target_device(info: ic4.DeviceInfo) -> bool:
    model = first_value(info, ("model_name", "model", "display_name"))
    return bool(model and TARGET_MODEL in model)


def list_target_devices() -> list[ic4.DeviceInfo]:
    print("Enumerating connected cameras...")
    devices = list(ic4.DeviceEnum.devices())
    targets = [info for info in devices if is_target_device(info)]

    if not targets:
        print(f"No {TARGET_MODEL} cameras detected.")
    else:
        print(f"Detected {len(targets)} {TARGET_MODEL} device(s).")

    return targets


def _is_feature_not_found(exc: ic4.IC4Exception) -> bool:
    return getattr(exc, "code", None) == getattr(ic4.Error, "GenICamFeatureNotFound", None)


def read_bool(prop_map: Any, name: str) -> Optional[bool]:
    getter = getattr(prop_map, "try_get_value_bool", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return bool(value)
        except ic4.IC4Exception:
            pass
    try:
        return bool(prop_map.get_value_bool(name))
    except ic4.IC4Exception:
        return None


def try_set_ptp_enabled(prop_map: Any, prop_names: list[str]) -> tuple[bool, Optional[str]]:
    name = find_property_name(prop_names, PTP_ENABLE_NAMES, ENABLE_KEYWORD_GROUPS)
    if not name:
        print("PTP enable property not found on device.")
        return False, None
    try:
        setter = getattr(prop_map, "try_set_value", None)
        if callable(setter):
            success = setter(name, True)
            if success is False:
                print(f"PTP enable property '{name}' rejected the requested value.")
                return False, name
            if success:
                value = read_bool(prop_map, name)
                return (bool(value) if value is not None else True), name
        prop_map.set_value(name, True)
        value = read_bool(prop_map, name)
        return (bool(value) if value is not None else True), name
    except ic4.IC4Exception as exc:
        print(f"Failed to enable PTP using property '{name}'.")
        print(f"Error: {exc}")
        return False, name


def latch_ptp_dataset(prop_map: Any, prop_names: list[str]) -> Optional[str]:
    name = find_property_name(prop_names, PTP_LATCH_COMMANDS, LATCH_KEYWORD_GROUPS)
    if not name:
        return None
    try:
        prop_map.execute_command(name)
        return name
    except ic4.IC4Exception as exc:
        if _is_feature_not_found(exc):
            return None
        raise
    except AttributeError:  # pragma: no cover
        return None


def read_ptp_status(prop_map: Any, prop_names: list[str]) -> Optional[str]:
    name = find_property_name(prop_names, PTP_STATUS_NAMES, STATUS_KEYWORD_GROUPS)
    if not name:
        return None
    getter = getattr(prop_map, "try_get_value_str", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return str(value)
        except ic4.IC4Exception as exc:
            if _is_feature_not_found(exc):
                return None
    try:
        return prop_map.get_value_str(name)
    except ic4.IC4Exception as exc:
        if _is_feature_not_found(exc):
            return None
        raise
    except AttributeError:
        return None


def read_ptp_offset(prop_map: Any, prop_names: list[str]) -> Optional[int]:
    name = find_property_name(prop_names, PTP_OFFSET_NAMES, OFFSET_KEYWORD_GROUPS)
    if not name:
        return None
    getter = getattr(prop_map, "try_get_value_int", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return int(value)
        except ic4.IC4Exception as exc:
            if _is_feature_not_found(exc):
                return None
    try:
        return int(prop_map.get_value_int(name))
    except ic4.IC4Exception as exc:
        if _is_feature_not_found(exc):
            return None
        raise
    except (AttributeError, TypeError):
        return None


def handle_device(info: ic4.DeviceInfo, label: str) -> None:
    model = first_value(info, ("model_name", "model", "display_name")) or "Unknown"
    serial = first_value(info, ("serial", "serial_number", "unique_id")) or "Unknown"

    print(f"Device {label} model_name: {model}")
    print(f"Device {label} serial: {serial}")

    grabber = ic4.Grabber()
    print(f"Opening device {label}...")
    try:
        grabber.device_open(info)
        print(f"Device {label} opened successfully.")
    except ic4.IC4Exception as exc:
        print(f"Failed to open device {label}.")
        print(f"Error: {exc}")
        return

    try:
        prop_map = grabber.device_property_map
        prop_names = collect_property_names(prop_map)
        enabled, enabled_name = try_set_ptp_enabled(prop_map, prop_names)
        try:
            latch_command = latch_ptp_dataset(prop_map, prop_names)
        except ic4.IC4Exception as exc:
            print(f"Failed to latch PTP dataset for device {label}.")
            print(f"Error: {exc}")
            latch_command = None
        status = read_ptp_status(prop_map, prop_names)
        offset = read_ptp_offset(prop_map, prop_names)

        if enabled_name:
            print(f"Device {label} PTP enabled via '{enabled_name}': {'Yes' if enabled else 'No'}")
        else:
            print(f"Device {label} PTP enabled: {'Yes' if enabled else 'No'}")

        if latch_command:
            print(f"Device {label} PTP latch command used: {latch_command}")
        if status is not None:
            print(f"Device {label} PTP status: {status}")
        else:
            print(f"Device {label} PTP status: Unknown")

        if offset is not None:
            print(f"Device {label} PTP offset: {offset} ns")
        else:
            print(f"Device {label} PTP offset: Not available")
    except ic4.IC4Exception as exc:
        print(f"Failed to query PTP information for device {label}.")
        print(f"Error: {exc}")
    finally:
        try:
            grabber.device_close()
            print(f"Device {label} closed successfully.")
        except ic4.IC4Exception:
            pass
        grabber = None


def main() -> None:
    try:
        ic4.Library.init()
    except ic4.IC4Exception as exc:
        print("Failed to initialize IC Imaging Control 4.")
        print(f"Error: {exc}")
        return

    devices: list[Optional[ic4.DeviceInfo]] = []
    try:
        devices = list_target_devices()
        if not devices:
            return

        for index, info in enumerate(devices, start=1):
            handle_device(info, f"#{index}")
            devices[index - 1] = None

        del info
        devices.clear()
        del devices
    finally:
        ic4.Library.exit()
        print("Library shutdown complete.")


if __name__ == "__main__":
    main()
