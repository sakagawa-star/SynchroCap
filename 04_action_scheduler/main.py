"""Schedule action commands on DFK 33GR0234 cameras using PTP time."""

from __future__ import annotations

import threading
from pathlib import Path
import sys
from typing import Any, Iterable, Optional, Tuple

try:
    import imagingcontrol4 as ic4
except ImportError as exc:  # pragma: no cover
    print("Failed to import imagingcontrol4.")
    print("Install IC Imaging Control 4 and ensure PYTHONPATH is configured.")
    print(f"Import error: {exc}")
    sys.exit(1)

ACTION_DELAY_NS = 2_000_000_000  # 2 seconds
TARGET_MODEL = "DFK 33GR0234"

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
    ic4.PropId.TIMESTAMP_LATCH,  # some devices use the standard latch command for PTP data
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

ACTION_ENABLE_NAMES = (
    "ActionSchedulerEnable",
    "ActionScheduledTimeEnable",
)
ACTION_START_NAMES = (
    ic4.PropId.ACTION_SCHEDULER_TIME,
    "ActionSchedulerStartTime",
    "ActionScheduledStartTime",
    "ActionScheduledTime",
)
ACTION_START_LOW_NAMES = (
    "ActionSchedulerStartTimeLow",
    "ActionScheduledTimeLow",
)
ACTION_START_HIGH_NAMES = (
    "ActionSchedulerStartTimeHigh",
    "ActionScheduledTimeHigh",
)
ACTION_INTERVAL_NAMES = (
    ic4.PropId.ACTION_SCHEDULER_INTERVAL,
    "ActionSchedulerInterval",
    "ActionScheduledInterval",
)
ACTION_INTERVAL_LOW_NAMES = (
    "ActionSchedulerIntervalLow",
    "ActionScheduledIntervalLow",
)
ACTION_INTERVAL_HIGH_NAMES = (
    "ActionSchedulerIntervalHigh",
    "ActionScheduledIntervalHigh",
)
ACTION_SELECTOR_NAMES = (
    ic4.PropId.ACTION_SELECTOR,
    "ActionSchedulerSelector",
    "ActionSelector",
)
ACTION_COMMIT_NAMES = (
    ic4.PropId.ACTION_SCHEDULER_COMMIT,
    "ActionSchedulerCommit",
)

SELECTOR_KEYWORD_GROUPS = ("action selector", "scheduler selector")
ACTION_ENABLE_KEYWORDS = ("action scheduler enable", "scheduled time enable")
ACTION_START_KEYWORDS = ("action scheduler start", "scheduled start time")
ACTION_INTERVAL_KEYWORDS = ("action scheduler interval", "scheduled interval")


def first_value(obj: object, names: Iterable[str]) -> Optional[str]:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value:
                return str(value)
    return None


class SingleFrameListener(ic4.QueueSinkListener):
    """Queue sink listener that captures a single frame."""

    def __init__(self) -> None:
        self.connected = threading.Event()
        self.frame_ready = threading.Event()
        self.buffer: Optional[ic4.ImageBuffer] = None
        self.error: Optional[Exception] = None
        self.sink: Optional[ic4.QueueSink] = None

    def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
        self.sink = sink
        buffer_count = max(min_buffers_required, 3)
        sink.alloc_and_queue_buffers(buffer_count)
        self.connected.set()
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        self.connected.clear()
        if not self.frame_ready.is_set():
            self.error = RuntimeError("Stream disconnected before a frame was received")
            self.frame_ready.set()

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        try:
            buffer = sink.pop_output_buffer()
        except ic4.IC4Exception as exc:
            if not self.frame_ready.is_set():
                self.error = exc
                self.frame_ready.set()
            return

        if self.buffer is None:
            self.buffer = buffer
            self.frame_ready.set()
        else:
            try:
                sink.queue_buffer(buffer)
            except ic4.IC4Exception:
                pass


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
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def set_prop_value(prop_map: Any, name: str, value: Any) -> bool:
    setter = getattr(prop_map, "try_set_value", None)
    if callable(setter):
        try:
            if setter(name, value):
                return True
        except ic4.IC4Exception:
            return False
    try:
        prop_map.set_value(name, value)
        return True
    except ic4.IC4Exception:
        return False


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


def read_int(prop_map: Any, name: str) -> Optional[int]:
    getter = getattr(prop_map, "try_get_value_int", None)
    if callable(getter):
        try:
            value = getter(name)
            if value is not None:
                return int(value)
        except ic4.IC4Exception:
            pass
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
            pass
    try:
        return prop_map.get_value_str(name)
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
        print(f"Failed to execute PTP latch command '{name}'.")
        print(f"Error: {exc}")
        return None
    except AttributeError:
        return None


def read_ptp_status(prop_map: Any, prop_names: list[str]) -> Optional[str]:
    name = find_property_name(prop_names, PTP_STATUS_NAMES, STATUS_KEYWORD_GROUPS)
    if not name:
        return None
    return read_str(prop_map, name)


def read_ptp_offset(prop_map: Any, prop_names: list[str]) -> Optional[int]:
    name = find_property_name(prop_names, PTP_OFFSET_NAMES, OFFSET_KEYWORD_GROUPS)
    if not name:
        return None
    return read_int(prop_map, name)


def latch_timestamp(prop_map: Any, prop_names: list[str]) -> Optional[str]:
    name = find_property_name(prop_names, TIMESTAMP_LATCH_COMMANDS, ("timestamp latch",))
    if not name:
        return None
    try:
        prop_map.execute_command(name)
        return name
    except ic4.IC4Exception as exc:
        if _is_feature_not_found(exc):
            return None
        print(f"Failed to execute timestamp latch command '{name}'.")
        print(f"Error: {exc}")
        return None
    except AttributeError:
        return None


def read_timestamp(prop_map: Any, prop_names: list[str]) -> Optional[int]:
    name = find_property_name(prop_names, TIMESTAMP_NAMES, ("timestamp",))
    if not name:
        candidates = [p for p in prop_names if "time" in p.lower() or "timestamp" in p.lower()]
        if candidates:
            print("Timestamp property not found. Candidates:")
            for candidate in candidates:
                print(f"  {candidate}")
        return None
    return read_int(prop_map, name)


def find_selector(prop_names: list[str]) -> Optional[str]:
    return find_property_name(prop_names, ACTION_SELECTOR_NAMES, SELECTOR_KEYWORD_GROUPS)


def set_selector(prop_map: Any, prop_names: list[str], value: int) -> Optional[str]:
    name = find_selector(prop_names)
    if not name:
        return None
    try:
        prop_map.set_value(name, value)
        return name
    except ic4.IC4Exception as exc:
        print(f"Failed to set action selector '{name}' to {value}.")
        print(f"Error: {exc}")
        return name


def write_uint64(prop_map: Any, prop_names: list[str], base_names: Iterable[str],
                 low_names: Iterable[str], high_names: Iterable[str],
                 keyword_groups: Iterable[str], value: int) -> Optional[str]:
    base = find_property_name(prop_names, base_names, keyword_groups)
    if base and property_exists(prop_names, base):
        try:
            prop_map.set_value(base, value)
            return base
        except ic4.IC4Exception as exc:
            print(f"Failed to set property '{base}' to {value}.")
            print(f"Error: {exc}")
            return None
    low_name = find_property_name(prop_names, low_names, keyword_groups)
    high_name = find_property_name(prop_names, high_names, keyword_groups)
    if low_name and high_name:
        low = value & 0xFFFFFFFF
        high = (value >> 32) & 0xFFFFFFFF
        try:
            prop_map.set_value(low_name, low)
            prop_map.set_value(high_name, high)
            return f"{high_name}/{low_name}"
        except ic4.IC4Exception as exc:
            print(f"Failed to set split properties '{high_name}'/'{low_name}'.")
            print(f"Error: {exc}")
            return None
    print("Suitable property for writing 64-bit value not found.")
    return None


def set_boolean(prop_map: Any, prop_names: list[str], explicit: Iterable[str], keywords: Iterable[str], value: bool) -> Optional[str]:
    name = find_property_name(prop_names, explicit, keywords)
    if not name:
        return None
    try:
        setter = getattr(prop_map, "try_set_value", None)
        if callable(setter):
            result = setter(name, value)
            if result:
                return name
            if result is False:
                print(f"Property '{name}' rejected value {value}.")
                return None
        prop_map.set_value(name, value)
        return name
    except ic4.IC4Exception as exc:
        print(f"Failed to set property '{name}' to {value}.")
        print(f"Error: {exc}")
        return None


def schedule_action(
    prop_map: Any,
    prop_names: list[str],
    start_ns: int,
    interval_ns: Optional[int],
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    selector_used = set_selector(prop_map, prop_names, 0)
    enable_name = set_boolean(prop_map, prop_names, ACTION_ENABLE_NAMES, ACTION_ENABLE_KEYWORDS, False)
    start_name = write_uint64(
        prop_map,
        prop_names,
        ACTION_START_NAMES,
        ACTION_START_LOW_NAMES,
        ACTION_START_HIGH_NAMES,
        ACTION_START_KEYWORDS,
        start_ns,
    )
    if start_name is None:
        print("Unable to write action start time.")
        return False, selector_used, None, None
    interval_name = None
    if interval_ns is not None:
        interval_name = write_uint64(
            prop_map,
            prop_names,
            ACTION_INTERVAL_NAMES,
            ACTION_INTERVAL_LOW_NAMES,
            ACTION_INTERVAL_HIGH_NAMES,
            ACTION_INTERVAL_KEYWORDS,
            interval_ns,
        )
        if interval_name is None:
            print("Failed to set action interval property.")
            interval_name = None
    set_boolean(prop_map, prop_names, ACTION_ENABLE_NAMES, ACTION_ENABLE_KEYWORDS, True)
    commit_name = find_property_name(prop_names, ACTION_COMMIT_NAMES, ("action scheduler commit",))
    if commit_name:
        try:
            prop_map.execute_command(commit_name)
        except ic4.IC4Exception as exc:
            print(f"Failed to execute action commit command '{commit_name}'.")
            print(f"Error: {exc}")
            return False, selector_used, interval_name if interval_ns is not None else None, None
    return True, selector_used, interval_name if interval_ns is not None else None, commit_name


def configure_action_trigger(prop_map: Any) -> None:
    try_set = set_prop_value
    try_set(prop_map, ic4.PropId.ACTION_SELECTOR, 0)
    try_set(prop_map, ic4.PropId.ACTION_DEVICE_KEY, 0x12345678)
    try_set(prop_map, ic4.PropId.ACTION_GROUP_KEY, 0x1)
    try_set(prop_map, ic4.PropId.ACTION_GROUP_MASK, 0x1)
    try_set(prop_map, ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
    try_set(prop_map, ic4.PropId.TRIGGER_MODE, "On")
    try_set(prop_map, ic4.PropId.TRIGGER_SOURCE, "Action0")


def capture_single_frame(
    grabber: ic4.Grabber,
    listener: SingleFrameListener,
    start_time_ns: int,
    prop_map: Any,
    prop_names: list[str],
    output_path: Path,
    expected_delay_seconds: float,
) -> Tuple[Optional[Path], Optional[str], Optional[str], Optional[str]]:
    sink = ic4.QueueSink(listener)
    try:
        grabber.stream_setup(sink)
    except ic4.IC4Exception as exc:
        print("Failed to set up stream for capture.")
        print(f"Error: {exc}")
        return None, None, None, None

    if not listener.connected.wait(timeout=2.0):
        print("Queue sink did not connect in time.")
        return None, None, None, None

    scheduled, selector_name, interval_name, commit_name = schedule_action(
        prop_map,
        prop_names,
        start_time_ns,
        None,
    )

    if not scheduled:
        print("Action scheduling aborted due to configuration errors.")
        return None, selector_name, interval_name, commit_name

    wait_seconds = expected_delay_seconds + 5.0
    if not listener.frame_ready.wait(timeout=wait_seconds):
        print("Timed out waiting for action-triggered frame.")
        return None, selector_name, interval_name, commit_name

    if listener.error:
        print(f"Capture listener error: {listener.error}")
        return None, selector_name, interval_name, commit_name

    buffer = listener.buffer
    if buffer is None:
        print("Capture completed without receiving a frame.")
        return None, selector_name, interval_name, commit_name

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        buffer.save_as_png(str(output_path))
    except ic4.IC4Exception as exc:
        print("Failed to save image buffer.")
        print(f"Error: {exc}")
        return None, selector_name, interval_name, commit_name
    listener.buffer = None
    return output_path.resolve(), selector_name, interval_name, commit_name


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
        if enabled_name:
            print(f"Device {label} PTP enable property: {enabled_name}")
        if not enabled:
            print(f"Warning: device {label} PTP could not be confirmed as enabled.")
        latch_ptp_dataset(prop_map, prop_names)
        status = read_ptp_status(prop_map, prop_names)
        offset = read_ptp_offset(prop_map, prop_names)
        if status:
            print(f"Device {label} PTP status: {status}")
        if offset is not None:
            print(f"Device {label} PTP offset: {offset} ns")

        latch_timestamp(prop_map, prop_names)
        current_time = read_timestamp(prop_map, prop_names)
        if current_time is None:
            print(f"Device {label} is missing a timestamp property required for scheduling.")
            return

        start_time = current_time + ACTION_DELAY_NS
        delay_seconds = max((start_time - current_time) / 1_000_000_000, 0.0)
        configure_action_trigger(prop_map)

        listener = SingleFrameListener()
        output_path = Path(f"camera_{serial}.png")

        capture_path, selector_name, interval_name, commit_name = capture_single_frame(
            grabber,
            listener,
            start_time,
            prop_map,
            prop_names,
            output_path,
            delay_seconds,
        )

        if selector_name:
            print(f"Device {label} action selector configured via '{selector_name}'.")
        if commit_name:
            print(f"Device {label} commit command executed: {commit_name}")

        if capture_path:
            print(f"Device {label} scheduled trigger time: {start_time} ns")
            print(f"Device {label} image saved to: {capture_path}")
        else:
            print(f"Device {label} failed to capture image with scheduled action.")
    except ic4.IC4Exception as exc:
        print(f"Failed to configure action scheduler for device {label}.")
        print(f"Error: {exc}")
    finally:
        try:
            grabber.stream_stop()
        except ic4.IC4Exception:
            pass
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
