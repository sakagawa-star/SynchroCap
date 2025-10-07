"""Evaluate camera timestamp alignment against Ubuntu PTP grandmaster."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from itertools import count
from statistics import median
from typing import Dict, Iterable, List

import imagingcontrol4 as ic4


@dataclass
class CheckResult:
    exit_code: int


class CheckError(RuntimeError):
    """Fatal error during synchronisation check."""


PMC_PATH: str | None = None
_PMC_COUNTER = count()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check PTP timestamp alignment across cameras")
    parser.add_argument(
        "--serials",
        default="05520125,05520126,05520128,05520129",
        help="Comma-separated list of camera serial numbers",
    )
    parser.add_argument(
        "--iface",
        default="enp3s0",
        help="Network interface name (for logging only)",
    )
    parser.add_argument(
        "--threshold-ns",
        type=int,
        default=100_000_000,
        help="Absolute delta threshold against median in ns",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of capture iterations",
    )
    parser.add_argument(
        "--interval-ms",
        type=float,
        default=0.0,
        help="Interval between samples in milliseconds",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=60.0,
        help="Overall timeout in seconds",
    )
    parser.add_argument(
        "--assume-realtime-ptp",
        action="store_true",
        help="Also compare camera timestamps to time.time_ns() as a reference",
    )

    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be >= 1")
    if args.threshold_ns < 0:
        parser.error("--threshold-ns must be >= 0")
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be > 0")

    args.serial_list = [s.strip() for s in args.serials.split(",") if s.strip()]
    if not args.serial_list:
        parser.error("--serials produced an empty list")

    return args


def init_pmc_path() -> None:
    global PMC_PATH
    preferred = "/usr/sbin/pmc"
    if os.path.exists(preferred):
        PMC_PATH = preferred
        return
    found = shutil.which("pmc")
    if not found:
        raise CheckError("pmc command not found (expected at /usr/sbin/pmc or in PATH)")
    PMC_PATH = found


def run_pmc_command(arguments: Iterable[str]) -> tuple[bool, str]:
    if PMC_PATH is None:
        raise CheckError("pmc path not initialised")

    client_socket = f"/tmp/pmc.{os.getuid()}.{os.getpid()}.{next(_PMC_COUNTER)}"
    cmd = [
        PMC_PATH,
        "-u",
        "-i",
        client_socket,
        "-s",
        "/var/run/ptp4l",
        "-b",
        "0",
        "-d",
        "0",
        " ".join(arguments),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        return True, completed.stdout
    except FileNotFoundError:
        return False, "pmc コマンドが見つかりません"
    except subprocess.TimeoutExpired:
        return False, "pmc コマンドがタイムアウトしました"
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or exc.stdout or str(exc)
        return False, stderr.strip()
    finally:
        try:
            os.unlink(client_socket)
        except OSError:
            pass


def parse_key_values(output: str, keys: Iterable[str]) -> Dict[str, str]:
    target = set(keys)
    result: Dict[str, str] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.replace("=", " ").split()
        if len(parts) < 2:
            continue
        key = parts[0]
        if key in target and key not in result:
            result[key] = parts[-1]
    return result


@dataclass
class GrandmasterInfo:
    role: str
    clock_id: str | None
    steps_removed: int


def verify_grandmaster() -> GrandmasterInfo:
    success, output = run_pmc_command(["GET", "CURRENT_DATA_SET"])
    if not success:
        raise CheckError(f"pmc CURRENT_DATA_SET failed: {output}")

    info = parse_key_values(output, ["stepsRemoved"])
    try:
        steps = int(info["stepsRemoved"])
    except (KeyError, ValueError):
        raise CheckError("Unable to determine stepsRemoved from pmc output")
    if steps != 0:
        raise CheckError(f"Ubuntu is not PTP Grandmaster (stepsRemoved={steps})")

    gm_id: str | None = None
    gm_role = "Grandmaster"

    success, output = run_pmc_command(["GET", "DEFAULT_DATA_SET"])
    if success:
        gm_info = parse_key_values(output, ["clockIdentity", "grandmasterIdentity"])
        gm_id = gm_info.get("clockIdentity") or gm_info.get("grandmasterIdentity")

    if gm_id is None:
        success, output = run_pmc_command(["GET", "TIME_STATUS_NP"])
        if success:
            gm_info = parse_key_values(output, ["gmIdentity", "grandmasterIdentity"])
            gm_id = gm_info.get("gmIdentity") or gm_info.get("grandmasterIdentity")

    return GrandmasterInfo(role=gm_role, clock_id=gm_id, steps_removed=steps)


def find_device_by_serial(serial: str, devices: Iterable[ic4.DeviceInfo]) -> ic4.DeviceInfo:
    for dev in devices:
        if getattr(dev, "serial", None) == serial:
            return dev
    raise CheckError(f"Camera with serial {serial} not found")


def trigger_timestamp_latch(grabber: ic4.Grabber) -> None:
    prop_map = grabber.device_property_map
    try:
        try:
            prop_map.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)
        except AttributeError:
            prop_map.set_value(ic4.PropId.TIMESTAMP_LATCH, True)
    except ic4.IC4Exception as exc:
        raise CheckError(f"Failed to trigger TIMESTAMP_LATCH: {exc}")


def read_latched_timestamp_ns(grabber: ic4.Grabber, serial: str | None = None) -> int:
    prop_map = grabber.device_property_map
    raw_value = None
    for getter in (
        lambda: prop_map.get_value_float(ic4.PropId.TIMESTAMP_LATCH_VALUE),
        lambda: prop_map.get_value(ic4.PropId.TIMESTAMP_LATCH_VALUE),
    ):
        try:
            raw_value = getter()
        except ic4.IC4Exception:
            continue
        if raw_value is not None:
            break
    if raw_value is None:
        if serial is not None:
            raise CheckError(f"TIMESTAMP_LATCH_VALUE unavailable for serial {serial}")
        raise CheckError("TIMESTAMP_LATCH_VALUE unavailable")
    try:
        return int(float(raw_value))
    except (TypeError, ValueError) as exc:
        if serial is not None:
            raise CheckError(f"Invalid TIMESTAMP_LATCH_VALUE for serial {serial}: {exc}")
        raise CheckError(f"Invalid TIMESTAMP_LATCH_VALUE: {exc}")


def compute_statistics(values: List[float]) -> tuple[float, float, float]:
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    stddev = math.sqrt(variance)
    max_abs = max(abs(v) for v in values)
    return mean_val, stddev, max_abs


def run_check(args: argparse.Namespace) -> CheckResult:
    init_pmc_path()
    gm_info = verify_grandmaster()

    devices = ic4.DeviceEnum.devices()
    contexts = []
    for serial in args.serial_list:
        dev_info = find_device_by_serial(serial, devices)
        grabber = ic4.Grabber()
        try:
            grabber.device_open(dev_info)
        except ic4.IC4Exception as exc:
            raise CheckError(f"Failed to open camera {serial}: {exc}")
        contexts.append({"serial": serial, "grabber": grabber})

    try:
        all_deltas: Dict[str, List[float]] = {ctx["serial"]: [] for ctx in contexts}
        threshold = args.threshold_ns
        any_ng = False

        start_time = time.monotonic()
        deadline = start_time + args.timeout_s
        interval_sec = max(0.0, args.interval_ms / 1000.0)

        for sample_idx in range(args.samples):
            if time.monotonic() > deadline:
                raise CheckError("Overall timeout exceeded")

            sample_gm = verify_grandmaster()
            print(f"[Sample {sample_idx + 1}]")
            print(
                f"Ubuntu(host) PTP: role={sample_gm.role}, gmClockID={sample_gm.clock_id or 'unknown'}"
            )

            # Stage A: trigger latch for all cameras first.
            for ctx in contexts:
                if time.monotonic() > deadline:
                    raise CheckError("Overall timeout exceeded")
                grabber = ctx["grabber"]
                try:
                    trigger_timestamp_latch(grabber)
                except CheckError as exc:
                    raise CheckError(f"Failed to trigger TIMESTAMP_LATCH for serial {ctx['serial']}: {exc}")

            # Stage B: read latched values.
            camera_times = []
            for ctx in contexts:
                if time.monotonic() > deadline:
                    raise CheckError("Overall timeout exceeded")
                serial = ctx["serial"]
                grabber = ctx["grabber"]
                camera_time_ns = read_latched_timestamp_ns(grabber, serial)
                camera_times.append((serial, camera_time_ns))

            median_ns = int(median(val for _, val in camera_times))
            ref_time_ns = time.time_ns() if args.assume_realtime_ptp else None

            for serial, camera_time_ns in camera_times:
                delta_ns = camera_time_ns - median_ns
                all_deltas[serial].append(delta_ns)
                verdict = "OK" if abs(delta_ns) <= threshold else "NG"
                if verdict == "NG":
                    any_ng = True
                delta_ms = delta_ns / 1_000_000.0
                line = (
                    f"serial={serial}, camera_time_ns={camera_time_ns}, "
                    f"delta_to_median_ms={delta_ms:.6f}, verdict={verdict}"
                )
                if ref_time_ns is not None:
                    ref_delta = camera_time_ns - ref_time_ns
                    line += f", ref_delta_ns={ref_delta}"
                print(line)

            if sample_idx + 1 < args.samples and interval_sec > 0:
                next_deadline = time.monotonic() + interval_sec
                if next_deadline > deadline:
                    raise CheckError("Overall timeout exceeded during interval wait")
                time.sleep(interval_sec)

        if args.samples > 1:
            print("\n=== Statistics ===")
            for serial in args.serial_list:
                deltas = all_deltas[serial]
                mean_val, stddev, max_abs = compute_statistics(deltas)
                verdict = "OK" if all(abs(v) <= threshold for v in deltas) else "NG"
                if verdict == "NG":
                    any_ng = True
                print(
                    f"serial={serial}, mean_delta_ns={mean_val:.0f}, stddev_ns={stddev:.0f}, "
                    f"max_abs_delta_ns={max_abs:.0f}, verdict={verdict}"
                )

            overall_max = max(
                abs(delta)
                for deltas in all_deltas.values()
                for delta in deltas
            )
            print(f"Max_abs_delta_ns={overall_max:.0f}")

        return CheckResult(exit_code=2 if any_ng else 0)

    finally:
        for ctx in contexts:
            grabber = ctx["grabber"]
            try:
                if grabber.is_device_open:
                    grabber.device_close()
            except ic4.IC4Exception:
                pass


def main() -> int:
    args = parse_args()
    try:
        with ic4.Library.init_context(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR):
            result = run_check(args)
            return result.exit_code
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except ic4.IC4Exception as exc:
        print(f"ERROR: imagingcontrol4 failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
