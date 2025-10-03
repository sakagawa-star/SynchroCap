import subprocess
import sys
import time
import threading
from datetime import datetime, timedelta
from typing import BinaryIO, Dict, Optional
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


SERIAL_NUMBERS = ["05520125", "05520126"]


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
    interval_us = 20_000

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
    sink.alloc_and_queue_buffers(1000)
    return sink, listener


def record_raw_frames(
    serial: str,
    grabber: ic4.Grabber,
    sink: ic4.QueueSink,
    duration_sec: float,
    output_stream: Optional[BinaryIO],
    ffmpeg_proc: Optional[subprocess.Popen[bytes]],
) -> None:
    if output_stream is None:
        log_warning(serial, "ffmpeg stdin is unavailable; skipping capture")
        return

    try:
        grabber.acquisition_start()
    except ic4.IC4Exception as e:
        log_warning(serial, "failed to start acquisition", e)
        return

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


def make_output_filename(serial: str) -> str:
    timestamp = datetime.now()
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S%f")[:-3]
    return f"cam{serial}_{date_part}_{time_part}.mp4"


def build_ffmpeg_command(width: int, height: int, frame_rate: float, output_filename: str) -> list[str]:
    return [
        "ffmpeg",
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


def main() -> None:
    WIDTH, HEIGHT = 1920, 1080
    FRAME_RATE = 50.0
    CAPTURE_DURATION = 600.0

    ic4.Library.init()
    camera_contexts: Dict[str, Dict[str, object]] = {}
    ffmpeg_processes: Dict[str, subprocess.Popen[bytes]] = {}
    threads: Dict[str, threading.Thread] = {}
    ffmpeg_proc: Optional[subprocess.Popen[bytes]] = None
    grabber: Optional[ic4.Grabber] = None
    sink: Optional[ic4.QueueSink] = None
    listener: Optional[_RawQueueSinkListener] = None
    device_info: Optional[ic4.DeviceInfo] = None

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

            configure_camera_for_bayer_gr8(serial, grabber, WIDTH, HEIGHT, FRAME_RATE)
            sink, listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)

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
            ffmpeg_processes[serial] = ffmpeg_proc

        if not camera_contexts:
            sys.stderr.write("No cameras initialized successfully; exiting.\n")
            return

        # Start capture threads for each camera.
        for serial, ctx in camera_contexts.items():
            grabber = ctx["grabber"]  # type: ignore[assignment]
            sink = ctx["sink"]  # type: ignore[assignment]
            ffmpeg_proc = ctx["ffmpeg_proc"]  # type: ignore[assignment]
            thread = threading.Thread(
                target=record_raw_frames,
                args=(
                    serial,
                    grabber,
                    sink,
                    CAPTURE_DURATION,
                    ffmpeg_proc.stdin,  # type: ignore[arg-type]
                    ffmpeg_proc,
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

        camera_contexts.clear()
        ffmpeg_processes.clear()
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
