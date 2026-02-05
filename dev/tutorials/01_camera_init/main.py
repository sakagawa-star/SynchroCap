"""Enumerate and validate Imaging Source cameras via imagingcontrol4."""

from __future__ import annotations

import sys
from typing import Iterable, Optional

try:
    import imagingcontrol4 as ic4
except ImportError as exc:  # pragma: no cover
    print("Failed to import imagingcontrol4.")
    print("Install IC Imaging Control 4 and ensure PYTHONPATH is configured.")
    print(f"Import error: {exc}")
    sys.exit(1)


def first_value(obj: object, names: Iterable[str]) -> Optional[str]:
    """Return the first truthy attribute value found on obj."""
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value:
                return str(value)
    return None


def enumerate_devices() -> list[ic4.DeviceInfo]:
    """Return all connected devices using DeviceEnum."""
    print("Enumerating connected cameras...")
    devices = list(ic4.DeviceEnum.devices())
    if not devices:
        print("No cameras detected. Check cables, power, and network settings.")
    else:
        print(f"Detected {len(devices)} device(s).")
    return devices


def open_and_close_device(info: ic4.DeviceInfo, label: str) -> None:
    """Open and close a device via Grabber to verify connectivity."""
    model = first_value(info, ("model_name", "model", "display_name")) or "Unknown"
    serial = first_value(info, ("serial", "serial_number", "unique_id")) or "Unknown"

    print(f"Device {label} model_name: {model}")
    print(f"Device {label} serial: {serial}")

    grabber = ic4.Grabber()
    print(f"Opening device {label}...")
    try:
        grabber.device_open(info)
        print(f"Device {label} opened successfully.")
        grabber.device_close()
        print(f"Device {label} closed successfully.")
        print(f"Device {label} connection verified.")
    except ic4.IC4Exception as exc:
        print(f"Failed to open device {label}.")
        print(f"Error: {exc}")
        try:
            grabber.device_close()
        except ic4.IC4Exception:
            pass


def run() -> None:
    print("Initializing IC Imaging Control 4 library...")
    with ic4.Library.init_context():
        devices = enumerate_devices()
        if not devices:
            return

        for index, info in enumerate(devices, start=1):
            open_and_close_device(info, f"#{index}")
            devices[index - 1] = None

        del info
        devices.clear()
        del devices
    print("Library shutdown complete.")


def main() -> None:
    try:
        run()
    except ic4.IC4Exception as exc:
        print("IC Imaging Control 4 error encountered.")
        print(f"Error: {exc}")
    except Exception as exc:  # pragma: no cover
        print("Unexpected error encountered.")
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
