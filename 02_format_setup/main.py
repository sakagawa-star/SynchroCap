"""Configure Imaging Source DFK 33GR0234 devices for BGR8 1920x1080 at 30 fps."""

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
TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FRAME_RATE = 30.0
TARGET_PIXEL_FORMAT = ic4.PixelFormat.BGR8


def first_value(obj: object, names: Iterable[str]) -> Optional[str]:
    """Return the first truthy attribute value found on obj."""
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value:
                return str(value)
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


def enable_frame_rate_control(prop_map: Any) -> None:
    try:
        prop_map.set_value(ic4.PropId.ACQUISITION_FRAME_RATE_ENABLE, True)
    except ic4.IC4Exception:
        pass


def apply_target_format(grabber: ic4.Grabber) -> bool:
    prop_map = grabber.device_property_map
    try:
        enable_frame_rate_control(prop_map)
        prop_map.set_value(ic4.PropId.PIXEL_FORMAT, TARGET_PIXEL_FORMAT)
        prop_map.set_value(ic4.PropId.WIDTH, TARGET_WIDTH)
        prop_map.set_value(ic4.PropId.HEIGHT, TARGET_HEIGHT)
        prop_map.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, TARGET_FRAME_RATE)
        print("Target video format applied successfully.")
        return True
    except ic4.IC4Exception as exc:
        print("Failed to apply target video format.")
        print(f"Error: {exc}")
        return False


def query_active_format(prop_map: Any) -> tuple[str, int, int, Optional[float]]:
    try:
        pixel = prop_map.get_value_str(ic4.PropId.PIXEL_FORMAT)
    except ic4.IC4Exception:
        pixel = "Unknown"

    try:
        width = prop_map.get_value_int(ic4.PropId.WIDTH)
    except ic4.IC4Exception:
        width = -1

    try:
        height = prop_map.get_value_int(ic4.PropId.HEIGHT)
    except ic4.IC4Exception:
        height = -1

    try:
        frame_rate = prop_map.get_value_float(ic4.PropId.ACQUISITION_FRAME_RATE)
    except ic4.IC4Exception:
        frame_rate = None

    return pixel, width, height, frame_rate


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

        applied = apply_target_format(grabber)

        pixel, width, height, frame_rate = query_active_format(grabber.device_property_map)
        print("Confirmed video settings:")
        print(f"  Pixel format: {pixel}")
        print(f"  Resolution: {width}x{height}")
        if frame_rate is not None:
            print(f"  Frame rate: {frame_rate:.2f} fps")
        else:
            print("  Frame rate: Unknown")

        if not applied:
            print("Device is using the active format shown above.")

        grabber.device_close()
        print(f"Device {label} closed successfully.")
    except ic4.IC4Exception as exc:
        print(f"Failed to configure device {label}.")
        print(f"Error: {exc}")
        try:
            grabber.device_close()
        except ic4.IC4Exception:
            pass


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
