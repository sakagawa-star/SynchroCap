import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import BinaryIO

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


def find_device_by_serial(serial: str) -> ic4.DeviceInfo:
    devices = ic4.DeviceEnum.devices()
    for dev in devices:
        # DeviceInfo.serial returns a string representing the serial number
        if getattr(dev, "serial", None) == serial:
            return dev
    raise RuntimeError(f"Camera with serial {serial!r} not found")


def configure_camera_for_bayer_gr8(grabber: ic4.Grabber, width: int, height: int, fps: float) -> None:
    # Configure device properties (resolution and pixel format)
    dmap = grabber.device_property_map
    try:
        dmap.set_value(ic4.PropId.WIDTH, width)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set WIDTH: {e}\n")
    try:
        dmap.set_value(ic4.PropId.HEIGHT, height)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set HEIGHT: {e}\n")
    # PixelFormat is an enumeration property.  The valid string for
    # Bayer GR8 is "BayerGR8" according to the IC4 documentation.  If
    # setting this property fails the camera will continue using its
    # current pixel format.
    try:
        dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BayerGR8")
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set PIXEL_FORMAT BayerGR8: {e}\n")
    # Configure frame rate.  Some devices expose AcquisitionFrameRate as
    # a float property.  Not all cameras support manual frame rate
    # control, so ignore any exception.
    try:
        dmap.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(fps))
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set ACQUISITION_FRAME_RATE: {e}\n")

    drmap = grabber.driver_property_map

    # Determine the device's current timestamp so we can schedule 10 seconds ahead.
    device_time_ns = 0
    try:
        dmap.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)
        try:
            device_time_ns = int(dmap.get_value_float(ic4.PropId.TIMESTAMP_LATCH_VALUE))
        except AttributeError:
            device_time_ns = int(dmap.get_value(ic4.PropId.TIMESTAMP_LATCH_VALUE))
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to latch TIMESTAMP: {e}\n")
        device_time_ns = 0
    if not device_time_ns:
        device_time_ns = time.time_ns()

    start_time_ns = device_time_ns + 10_000_000_000  # 10 seconds in nanoseconds
    interval_us = 20_000  # 50 fps in microseconds

    try:
        dmap.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to cancel action scheduler: {e}\n")
    try:
        dmap.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, start_time_ns)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set ACTION_SCHEDULER_TIME: {e}\n")
    try:
        dmap.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, interval_us)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set ACTION_SCHEDULER_INTERVAL: {e}\n")
    try:
        dmap.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to commit action scheduler: {e}\n")

    # Ensure the trigger reacts to action scheduler events.
    try:
        drmap.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set TRIGGER_SELECTOR FrameStart: {e}\n")
    try:
        drmap.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set TRIGGER_SOURCE Action0: {e}\n")
    try:
        drmap.set_value(ic4.PropId.TRIGGER_MODE, "On")
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to set TRIGGER_MODE On: {e}\n")


class _RawQueueSinkListener(ic4.QueueSinkListener):
    """Minimal listener that keeps the queue sink active."""

    def sink_connected(
        self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int
    ) -> bool:
        # Accept the sink connection without additional configuration.
        return True

    def frames_queued(self, sink: ic4.QueueSink) -> None:  # pragma: no cover - hardware callback
        # The capture loop waits on the sink directly, so nothing to do here.
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
    num_buffers = 1000
    sink.alloc_and_queue_buffers(num_buffers)
    return sink, listener


def record_raw_frames(
    grabber: ic4.Grabber,
    sink: ic4.QueueSink,
    duration_sec: float,
    output_stream: BinaryIO,
    ffmpeg_proc: subprocess.Popen[bytes] | None = None,
) -> None:
    grabber.acquisition_start()

    end_time = datetime.now() + timedelta(seconds=duration_sec)

    frame_count = 0

    while datetime.now() < end_time:
        if ffmpeg_proc is not None and ffmpeg_proc.poll() is not None:
            sys.stderr.write("ffmpeg terminated unexpectedly; stopping capture.\n")
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
            sys.stderr.write(f"Warning: failed to write frame to ffmpeg stdin: {e}\n")
            buf.release()
            break
        buf.release()

    try:
        output_stream.flush()
    except (BrokenPipeError, ValueError) as e:
        sys.stderr.write(f"Warning: failed to flush ffmpeg stdin: {e}\n")

    try:
        grabber.acquisition_stop()
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to stop acquisition: {e}\n")
    try:
        grabber.stream_stop()
    except ic4.IC4Exception as e:
        sys.stderr.write(f"Warning: failed to stop stream: {e}\n")


def main() -> None:
    """Main entry point for raw frame capture."""
    SERIAL_NUMBER = "05520125"
    WIDTH, HEIGHT = 1920, 1080
    FRAME_RATE = 50.0
    CAPTURE_DURATION = 600.0  # seconds

    timestamp = datetime.now()
    date_part = timestamp.strftime("%Y%m%d")
    time_part = timestamp.strftime("%H%M%S%f")[:-3]
    output_filename = f"cam{SERIAL_NUMBER}_{date_part}_{time_part}.mp4"

    ffmpeg_cmd = [
        "ffmpeg",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bayer_grbg8",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-framerate",
        f"{FRAME_RATE}",
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

    ic4.Library.init()
    grabber = ic4.Grabber()
    sink: ic4.QueueSink | None = None
    sink_listener: _RawQueueSinkListener | None = None
    device_info = None
    ffmpeg_proc: subprocess.Popen[bytes] | None = None
    try:
        device_info = find_device_by_serial(SERIAL_NUMBER)
        grabber.device_open(device_info)
        configure_camera_for_bayer_gr8(grabber, WIDTH, HEIGHT, FRAME_RATE)
        sink, sink_listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
        )
        if ffmpeg_proc.stdin is None:
            raise RuntimeError("ffmpeg stdin was not created")

        record_raw_frames(
            grabber,
            sink,
            CAPTURE_DURATION,
            ffmpeg_proc.stdin,
            ffmpeg_proc=ffmpeg_proc,
        )
    finally:
        try:
            if grabber.is_device_open:
                grabber.device_close()
        except ic4.IC4Exception as e:
            sys.stderr.write(f"Warning: failed to close grabber device: {e}\n")
        if ffmpeg_proc is not None:
            try:
                if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                    ffmpeg_proc.stdin.close()
            except Exception as e:
                sys.stderr.write(f"Warning: failed to close ffmpeg stdin during cleanup: {e}\n")
            try:
                ffmpeg_proc.wait()
            except Exception as e:
                sys.stderr.write(f"Warning: ffmpeg wait failed during cleanup: {e}\n")
        sink = None
        sink_listener = None
        device_info = None
        grabber = None
        ic4.Library.exit()


if __name__ == "__main__":
    main()
