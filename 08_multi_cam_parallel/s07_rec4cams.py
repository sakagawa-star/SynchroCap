import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from datetime import datetime, timedelta, timezone
from itertools import count
from typing import BinaryIO, Dict, Iterable, List, Optional
import gc

try:
    # The imagingcontrol4 library is provided by The Imaging Source.  It
    # exposes a GenTL based API for controlling industrial cameras.  See
    # the IC4 Python user guide for details.  ImportError will occur
    # here if the package is not installed.
    import imagingcontrol4 as ic4
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "imagingcontrol4 package is required; please install it before running"
    ) from exc


SERIAL_NUMBERS = ["05520125", "05520126", "05520128", "05520129"]


def find_device_by_serial(serial: str) -> ic4.DeviceInfo:
    devices = ic4.DeviceEnum.devices()
    for dev in devices:
        if getattr(dev, "serial", None) == serial:
            return dev
    raise RuntimeError(f"Camera with serial {serial!r} not found")


def log_warning(serial: str, message: str, exc: Optional[Exception] = None) -> None:
    if exc is not None:
        sys.stderr.write(f"[{serial}] Warning: {message}: {exc}\n")
    else:
        sys.stderr.write(f"[{serial}] Warning: {message}\n")


_PMC_COUNTER = count()


def _find_pmc_path() -> Optional[str]:
    preferred = "/usr/sbin/pmc"
    if os.path.exists(preferred):
        return preferred
    return shutil.which("pmc")


def _run_pmc_get_current_dataset() -> tuple[bool, str]:
    pmc_path = _find_pmc_path()
    if not pmc_path:
        return False, "pmc not found"
    client_socket = f"/tmp/pmc.{os.getuid()}.{os.getpid()}.{next(_PMC_COUNTER)}"
    cmd = [
        pmc_path,
        "-u",
        "-i",
        client_socket,
        "-s",
        "/var/run/ptp4l",
        "-b",
        "0",
        "-d",
        "0",
        "GET CURRENT_DATA_SET",
    ]
    try:
        cp = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10.0)
        return True, cp.stdout
    except Exception as e:
        msg = getattr(e, "stderr", "") or getattr(e, "stdout", "") or str(e)
        return False, msg
    finally:
        try:
            os.unlink(client_socket)
        except OSError:
            pass


def _ptp_precheck() -> None:
    ok, out = _run_pmc_get_current_dataset()
    if not ok:
        sys.stderr.write(f"[PTP] Warning: pre-check skipped ({out.strip()})\n")
        return
    m = re.search(r"stepsRemoved\s*=?\s*(\d+)", out)
    if not m:
        sys.stderr.write("[PTP] Warning: could not parse stepsRemoved\n")
        return
    steps = int(m.group(1))
    if steps == 0:
        print("[PTP] OK: stepsRemoved=0", file=sys.stderr)
    else:
        sys.stderr.write(f"[PTP] Warning: stepsRemoved={steps} (PTP may not be converged)\n")


def _find_camera_property(pm: ic4.PropertyMap, names: Iterable[str]):
    for name in names:
        try:
            return pm.find(name)
        except ic4.IC4Exception:
            continue
    return None


def _ensure_camera_ptp_enabled(grabber: ic4.Grabber) -> None:
    prop = _find_camera_property(
        grabber.device_property_map, ["PtpEnable", "GevIEEE1588Enable"]
    )
    if prop is None:
        return
    try:
        if getattr(prop, "value", None) is False:
            prop.value = True
    except ic4.IC4Exception:
        pass


def _get_camera_ptp_status(grabber: ic4.Grabber) -> Optional[str]:
    prop = _find_camera_property(
        grabber.device_property_map, ["PtpStatus", "GevIEEE1588Status"]
    )
    if prop is None:
        return None
    try:
        return f"{prop.value}"
    except ic4.IC4Exception:
        return None


def _wait_for_cameras_slave(camera_contexts: Dict[str, Dict[str, object]]) -> None:
    timeout = 30.0
    poll_interval = 1.0
    deadline = time.monotonic() + timeout
    total = len(camera_contexts)
    while True:
        slave_count = 0
        master_count = 0
        other_count = 0
        for serial, ctx in camera_contexts.items():
            grabber = ctx.get("grabber")
            if not isinstance(grabber, ic4.Grabber):
                other_count += 1
                continue
            status = _get_camera_ptp_status(grabber)
            if status == "Slave":
                slave_count += 1
            elif status == "Master":
                master_count += 1
            else:
                other_count += 1
        if slave_count == total:
            print("[PTP] OK: all cameras report Slave status", file=sys.stderr)
            return
        if time.monotonic() >= deadline:
            sys.stderr.write(
                "[PTP] Error: cameras not converged within timeout "
                f"(total={total}, Slave={slave_count}, Master={master_count}, Other={other_count})\n"
            )
            sys.exit(2)
        time.sleep(poll_interval)


def _check_offsets_and_schedule(
    camera_contexts: Dict[str, Dict[str, object]],
    start_delay_s: float,
    threshold_ms: float,
) -> None:
    threshold_ns = int(threshold_ms * 1_000_000)
    host_ref_before_ns = time.time_ns()
    for serial, ctx in camera_contexts.items():
        grabber = ctx.get("grabber")
        if not isinstance(grabber, ic4.Grabber):
            sys.stderr.write(f"[{serial}] Warning: grabber unavailable for offset scheduling\n")
            continue
        prop_map = grabber.device_property_map
        try:
            try:
                prop_map.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)
            except AttributeError:
                prop_map.set_value(ic4.PropId.TIMESTAMP_LATCH, True)
        except ic4.IC4Exception as exc:
            sys.stderr.write(f"[{serial}] Warning: failed to trigger TIMESTAMP_LATCH: {exc}\n")
    host_ref_after_ns = time.time_ns()
    host_ref_ns = (host_ref_before_ns + host_ref_after_ns) // 2

    deltas: Dict[str, int] = {}
    violations: List[tuple[str, float]] = []

    for serial, ctx in camera_contexts.items():
        grabber = ctx.get("grabber")
        if not isinstance(grabber, ic4.Grabber):
            sys.stderr.write(f"[{serial}] Warning: grabber unavailable for offset scheduling\n")
            continue
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
            sys.stderr.write(f"[{serial}] Warning: TIMESTAMP_LATCH_VALUE unavailable\n")
            continue
        try:
            camera_time_ns = int(float(raw_value))
        except (TypeError, ValueError) as exc:
            sys.stderr.write(f"[{serial}] Warning: invalid TIMESTAMP_LATCH_VALUE: {exc}\n")
            continue
        delta_ns = camera_time_ns - host_ref_ns
        deltas[serial] = delta_ns
        verdict = "OK" if abs(delta_ns) <= threshold_ns else "NG"
        delta_ms = delta_ns / 1_000_000.0
        print(
            f"serial={serial}, host_ref_ns={host_ref_ns}, camera_time_ns={camera_time_ns}, "
            f"delta_ns={delta_ns}, verdict={verdict}",
            file=sys.stderr,
        )
        if verdict == "NG":
            violations.append((serial, delta_ms))

    if violations:
        for serial, delta_ms in violations:
            sys.stderr.write(
                f"[PTP] Error: offset too large for serial={serial}, "
                f"delta_ms={delta_ms:+.3f} (>±{threshold_ms:.3f} ms)\n"
            )
        sys.exit(2)

    host_target_ns = time.time_ns() + int(start_delay_s * 1_000_000_000)

    for serial, ctx in camera_contexts.items():
        grabber = ctx.get("grabber")
        if not isinstance(grabber, ic4.Grabber):
            sys.stderr.write(f"[{serial}] Warning: grabber unavailable for scheduling\n")
            continue
        delta_ns = deltas.get(serial)
        if delta_ns is None:
            sys.stderr.write(f"[{serial}] Warning: missing delta for scheduling\n")
            continue
        camera_target_ns = host_target_ns + delta_ns
        prop_map = grabber.device_property_map
        try:
            prop_map.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
        except ic4.IC4Exception:
            pass
        try:
            prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, int(camera_target_ns))
        except ic4.IC4Exception as exc:
            sys.stderr.write(f"[PTP] Error: failed to set ACTION_SCHEDULER_TIME for serial={serial}: {exc}\n")
            sys.exit(2)
        try:
            prop_map.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
        except ic4.IC4Exception as exc:
            sys.stderr.write(f"[PTP] Error: failed to commit scheduler for serial={serial}: {exc}\n")
            sys.exit(2)


    for serial, delta_ns in deltas.items():
        delta_ms = delta_ns / 1_000_000.0
        print(f"[PTP] serial={serial}, delta_to_master_ms={delta_ms:+.3f}", file=sys.stderr)

    return host_target_ns



def configure_camera_for_bayer_gr8(
    serial: str, grabber: ic4.Grabber, width: int, height: int, fps: float
) -> None:
    dmap = grabber.device_property_map
    try:
        dmap.set_value(ic4.PropId.WIDTH, width)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set WIDTH", e)
    try:
        dmap.set_value(ic4.PropId.HEIGHT, height)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set HEIGHT", e)
    try:
        dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BayerGR8")
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set PIXEL_FORMAT BayerGR8", e)
    try:
        dmap.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(fps))
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set ACQUISITION_FRAME_RATE", e)

    drmap = grabber.driver_property_map

    device_time_ns = 0
    try:
        dmap.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)
        try:
            device_time_ns = int(dmap.get_value_float(ic4.PropId.TIMESTAMP_LATCH_VALUE))
        except AttributeError:
            device_time_ns = int(dmap.get_value(ic4.PropId.TIMESTAMP_LATCH_VALUE))
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to latch TIMESTAMP", e)
        device_time_ns = 0
    if not device_time_ns:
        device_time_ns = time.time_ns()

    start_time_ns = device_time_ns + 10_000_000_000
    interval_us = round(1_000_000 / fps)

    try:
        dmap.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to cancel action scheduler", e)
    try:
        dmap.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, start_time_ns)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set ACTION_SCHEDULER_TIME", e)
    try:
        dmap.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, interval_us)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set ACTION_SCHEDULER_INTERVAL", e)
    try:
        dmap.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to commit action scheduler", e)

    try:
        drmap.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set TRIGGER_SELECTOR FrameStart", e)
    try:
        drmap.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set TRIGGER_SOURCE Action0", e)
    try:
        drmap.set_value(ic4.PropId.TRIGGER_MODE, "On")
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to set TRIGGER_MODE On", e)


class _RawQueueSinkListener(ic4.QueueSinkListener):
    """Minimal listener that keeps the queue sink active."""

    def sink_connected(
        self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int
    ) -> bool:
        return True

    def frames_queued(self, sink: ic4.QueueSink) -> None:  # pragma: no cover
        return


def allocate_queue_sink(
    grabber: ic4.Grabber, width: int, height: int
) -> tuple[ic4.QueueSink, _RawQueueSinkListener]:
    listener = _RawQueueSinkListener()
    sink = ic4.QueueSink(listener, accepted_pixel_formats=[ic4.PixelFormat.BayerGR8])
    grabber.stream_setup(
        sink,
        setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START,
    )
    sink.alloc_and_queue_buffers(500)
    return sink, listener


def record_raw_frames(
    serial: str,
    grabber: ic4.Grabber,
    sink: ic4.QueueSink,
    duration_sec: float,
    output_stream: Optional[BinaryIO],
    ffmpeg_proc: Optional[subprocess.Popen[bytes]],
) -> int:
    if output_stream is None:
        log_warning(serial, "output stdin is unavailable; skipping capture")
        return 0

    try:
        grabber.acquisition_start()
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to start acquisition", e)
        return 0

    end_time = datetime.now() + timedelta(seconds=duration_sec)
    frame_count = 0

    while datetime.now() < end_time:
        if ffmpeg_proc is not None and ffmpeg_proc.poll() is not None:
            log_warning(serial, "ffmpeg terminated unexpectedly; stopping capture early")
            break

        buf = sink.try_pop_output_buffer()
        if buf is None:
            time.sleep(0.001)
            continue
        arr = buf.numpy_wrap()
        try:
            output_stream.write(arr.tobytes())
            frame_count += 1
            if frame_count % 30 == 0:
                output_stream.flush()
        except (BrokenPipeError, ValueError) as e:
            log_warning(serial, "failed to write frame to ffmpeg stdin", e)
            buf.release()
            break
        buf.release()

    try:
        output_stream.flush()
    except (BrokenPipeError, ValueError) as e:
        log_warning(serial, "failed to flush ffmpeg stdin", e)

    try:
        grabber.acquisition_stop()
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to stop acquisition", e)
    try:
        grabber.stream_stop()
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to stop stream", e)
    return frame_count


def make_output_filename(serial: str) -> str:
    timestamp = datetime.now()
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S%f")[:-3]
    return f"cam{serial}_{date_part}_{time_part}.mp4"


def make_raw_output_filename(serial: str) -> str:
    timestamp = datetime.now()
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S%f")[:-3]
    return f"cam{serial}_{date_part}_{time_part}.raw"


def build_ffmpeg_command(width: int, height: int, frame_rate: float, output_filename: str) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel", "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bayer_grbg8",
        "-s",
        f"{width}x{height}",
        "-framerate",
        f"{frame_rate}",
        "-i",
        "-",
        "-vf",
        "format=yuv420p",
        "-c:v",
        "hevc_nvenc",
        "-b:v",
        "2200k",
        "-maxrate",
        "2200k",
        "-bufsize",
        "4400k",
        "-preset",
        "p4",
        output_filename,
    ]




def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--start-delay-s",
        type=float,
        default=10.0,
        help="Delay in seconds before scheduled start",
    )
    parser.add_argument(
        "--offset-threshold-ms",
        type=float,
        default=3.0,
        help="PTP master–slave offset threshold in milliseconds",
    )
    parser.add_argument(
        "--raw-output",
        action="store_true",
        help="Write raw BayerGR8 stream to .raw without ffmpeg",
    )
    return parser.parse_args()
def main() -> None:
    args = parse_args()
    threshold_ms = args.offset_threshold_ms
    raw_mode = args.raw_output
    WIDTH, HEIGHT = 1920, 1080
    FRAME_RATE = 30.0
    CAPTURE_DURATION = 60.0
    EXPECTED_FRAMES = int(round(CAPTURE_DURATION * FRAME_RATE))

    ic4.Library.init()
    _ptp_precheck()
    camera_contexts: Dict[str, Dict[str, object]] = {}
    threads: Dict[str, threading.Thread] = {}
    result_map: Dict[str, int] = {}
    serial_order: List[str] = []
    capture_start_time: Optional[float] = None
    ffmpeg_proc: Optional[subprocess.Popen[bytes]] = None
    grabber: Optional[ic4.Grabber] = None
    sink: Optional[ic4.QueueSink] = None
    listener: Optional[_RawQueueSinkListener] = None
    device_info: Optional[ic4.DeviceInfo] = None

    def _worker(
        serial: str,
        grabber: ic4.Grabber,
        sink: ic4.QueueSink,
        duration_sec: float,
        output_stream: Optional[BinaryIO],
        ffmpeg_proc: Optional[subprocess.Popen[bytes]],
        results: Dict[str, int],
    ) -> None:
        try:
            count = record_raw_frames(
                serial, grabber, sink, duration_sec, output_stream, ffmpeg_proc
            )
        except Exception as exc:
            log_warning(serial, "record_raw_frames raised exception", exc)
            count = 0
        results[serial] = count
        print(f"[{serial}] frames={count}", file=sys.stderr)

    try:
        # Set up each camera and its encoder.
        for serial in SERIAL_NUMBERS:
            try:
                device_info = find_device_by_serial(serial)
            except RuntimeError as exc:
                log_warning(serial, "device not found", exc)
                continue

            grabber = ic4.Grabber()
            try:
                grabber.device_open(device_info)
            except ic4.IC4Exception as e:
                log_warning(serial, "failed to open device", e)
                continue

            _ensure_camera_ptp_enabled(grabber)
            configure_camera_for_bayer_gr8(serial, grabber, WIDTH, HEIGHT, FRAME_RATE)
            sink, listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)

            if raw_mode:
                raw_path = make_raw_output_filename(serial)
                try:
                    raw_file = open(raw_path, "wb")
                except OSError as e:
                    log_warning(serial, "failed to open raw output file", e)
                    try:
                        grabber.device_close()
                    except ic4.IC4Exception as close_exc:
                        log_warning(serial, "failed to close device after raw open failure", close_exc)
                    continue
                print(f"[RAW] Saving raw stream: {raw_path}", file=sys.stderr)
                camera_contexts[serial] = {
                    "grabber": grabber,
                    "sink": sink,
                    "listener": listener,
                    "device_info": device_info,
                    "ffmpeg_proc": None,
                    "raw_file": raw_file,
                }
                continue

            output_filename = make_output_filename(serial)
            ffmpeg_cmd = build_ffmpeg_command(WIDTH, HEIGHT, FRAME_RATE, output_filename)

            try:
                ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE,
                )
            except Exception as e:
                log_warning(serial, "failed to launch ffmpeg", e)
                try:
                    grabber.device_close()
                except ic4.IC4Exception as close_exc:
                    log_warning(serial, "failed to close device after ffmpeg launch failure", close_exc)
                continue

            if ffmpeg_proc.stdin is None:
                log_warning(serial, "ffmpeg stdin was not created")
                try:
                    ffmpeg_proc.terminate()
                except Exception as term_exc:
                    log_warning(serial, "failed to terminate ffmpeg without stdin", term_exc)
                try:
                    grabber.device_close()
                except ic4.IC4Exception as close_exc:
                    log_warning(serial, "failed to close device after stdin error", close_exc)
                continue

            camera_contexts[serial] = {
                "grabber": grabber,
                "sink": sink,
                "listener": listener,
                "device_info": device_info,
                "ffmpeg_proc": ffmpeg_proc,
            }

        if not camera_contexts:
            sys.stderr.write("No cameras initialized successfully; exiting.\n")
            return

        serial_order = list(camera_contexts.keys())

        if raw_mode:
            bytes_per_frame = WIDTH * HEIGHT
            per_cam_bytes = EXPECTED_FRAMES * bytes_per_frame
            total_bytes = per_cam_bytes * len(camera_contexts)
            per_cam_gib = per_cam_bytes / (1024 ** 3)
            total_gib = total_bytes / (1024 ** 3)
            sys.stderr.write(
                f"[RAW] Warning: estimated size ≈ {per_cam_gib:.2f} GiB per camera, total ≈ {total_gib:.2f} GiB\n"
            )

        _wait_for_cameras_slave(camera_contexts)
        host_target_ns = _check_offsets_and_schedule(
            camera_contexts, args.start_delay_s, threshold_ms
        )
        ts = host_target_ns / 1_000_000_000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        formatted = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(
            f"[SCHEDULE] Recording will start at (PC clock): {formatted}",
            file=sys.stderr,
        )
        # Start capture threads for each camera.
        capture_start_time = time.monotonic()
        for serial, ctx in camera_contexts.items():
            grabber = ctx["grabber"]  # type: ignore[assignment]
            sink = ctx["sink"]  # type: ignore[assignment]
            ffmpeg_proc = ctx.get("ffmpeg_proc")  # type: ignore[assignment]
            raw_file = ctx.get("raw_file")  # type: ignore[assignment]
            if raw_mode:
                output_stream = raw_file
                proc_for_thread = None
            else:
                output_stream = ffmpeg_proc.stdin  # type: ignore[assignment]
                proc_for_thread = ffmpeg_proc
            thread = threading.Thread(
                target=_worker,
                args=(
                    serial,
                    grabber,
                    sink,
                    CAPTURE_DURATION,
                    output_stream,
                    proc_for_thread,
                    result_map,
                ),
                name=f"CaptureThread-{serial}",
            )
            threads[serial] = thread
            thread.start()

        # Wait for all threads to finish.
        for serial, thread in threads.items():
            thread.join()

    finally:
        # Ensure worker threads have finished even if exceptions occurred.
        for serial, thread in list(threads.items()):
            if thread.is_alive():
                try:
                    thread.join(timeout=5.0)
                except Exception as e:
                    log_warning(serial, "thread join failed during cleanup", e)

        # Clean up resources.
        for serial, ctx in list(camera_contexts.items()):
            ffmpeg_proc = ctx.get("ffmpeg_proc")  # type: ignore[assignment]
            if isinstance(ffmpeg_proc, subprocess.Popen):
                try:
                    if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                        ffmpeg_proc.stdin.close()
                except Exception as e:
                    log_warning(serial, "failed to close ffmpeg stdin during cleanup", e)
                try:
                    ffmpeg_proc.wait()
                except Exception as e:
                    log_warning(serial, "ffmpeg wait failed during cleanup", e)
            ctx.pop("ffmpeg_proc", None)

            raw_file = ctx.pop("raw_file", None)
            if raw_file is not None:
                try:
                    raw_file.flush()
                except Exception:
                    pass
                try:
                    raw_file.close()
                except Exception:
                    pass

            grabber = ctx.pop("grabber", None)
            if isinstance(grabber, ic4.Grabber):
                try:
                    grabber.acquisition_stop()
                except ic4.IC4Exception as e:
                    log_warning(serial, "failed to stop acquisition during cleanup", e)
                try:
                    grabber.stream_stop()
                except ic4.IC4Exception as e:
                    log_warning(serial, "failed to stop stream during cleanup", e)
                try:
                    if grabber.is_device_open:
                        grabber.device_close()
                except ic4.IC4Exception as e:
                    log_warning(serial, "failed to close grabber device", e)

            ctx.pop("sink", None)
            ctx.pop("listener", None)
            ctx.pop("device_info", None)

        t1 = time.monotonic()
        actual_duration = 0.0
        if capture_start_time is not None:
            actual_duration = t1 - capture_start_time
            if actual_duration <= 0:
                actual_duration = 0.0

        if serial_order:
            for serial in serial_order:
                count = result_map.get(serial, 0)
                print(f"[REPORT] serial={serial} frames={count}", file=sys.stderr)
            for serial in serial_order:
                expected = EXPECTED_FRAMES
                got = result_map.get(serial, 0)
                delta = got - expected
                actual_fps = got / actual_duration if actual_duration > 0 else 0.0
                drift_ms = (delta / FRAME_RATE) * 1000.0
                print(
                    f"[REPORT] serial={serial} expected={expected} got={got} delta={delta:+d} "
                    f"actual_duration={actual_duration:.3f}s actual_fps={actual_fps:.3f} drift_ms={drift_ms:+.3f}",
                    file=sys.stdout,
                )
                threshold = max(2, int(0.001 * expected))
                if abs(delta) > threshold:
                    print(f"[{serial}] Warning: frame delta too large: {delta}", file=sys.stderr)

        camera_contexts.clear()
        threads.clear()

        # Break remaining references in this scope before exiting the library.
        ffmpeg_proc = None
        grabber = None
        sink = None
        listener = None
        device_info = None

        gc.collect()
        ic4.Library.exit()


if __name__ == "__main__":
    main()
