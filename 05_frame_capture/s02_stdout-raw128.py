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
    except ic4.IC4Exception:
        pass
    try:
        dmap.set_value(ic4.PropId.HEIGHT, height)
    except ic4.IC4Exception:
        pass
    # PixelFormat is an enumeration property.  The valid string for
    # Bayer GR8 is "BayerGR8" according to the IC4 documentation.  If
    # setting this property fails the camera will continue using its
    # current pixel format.
    try:
        dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BayerGR8")
    except ic4.IC4Exception:
        pass
    # Configure frame rate.  Some devices expose AcquisitionFrameRate as
    # a float property.  Not all cameras support manual frame rate
    # control, so ignore any exception.
    try:
        dmap.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(fps))
    except ic4.IC4Exception:
        pass
    # Configure the trigger mode on the driver property map.  To
    # operate the camera with software triggers, set TriggerSource to
    # "Software", TriggerMode to "On" and TriggerSelector to
    # "FrameStart".  If any property is missing or unsupported the
    # exceptions will be ignored.
    drmap = grabber.driver_property_map
    try:
        drmap.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
    except ic4.IC4Exception:
        pass
    try:
        drmap.set_value(ic4.PropId.TRIGGER_SOURCE, "Software")
    except ic4.IC4Exception:
        pass
    try:
        drmap.set_value(ic4.PropId.TRIGGER_MODE, "On")
    except ic4.IC4Exception:
        pass


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
    num_buffers = 10
    sink.alloc_and_queue_buffers(num_buffers)
    return sink, listener


def record_raw_frames(
    grabber: ic4.Grabber,
    sink: ic4.QueueSink,
    duration_sec: float,
    output_stream: BinaryIO,
    fps: float = 30.0,
) -> None:
    grabber.acquisition_start()

    trigger_cmd = None
    try:
        prop = grabber.driver_property_map.find(ic4.PropId.TRIGGER_SOFTWARE)
        if isinstance(prop, ic4.PropCommand):
            trigger_cmd = prop
    except ic4.IC4Exception:
        trigger_cmd = None

    # Determine when to stop capturing
    end_time = datetime.now() + timedelta(seconds=duration_sec)

    # Compute an inter‑trigger delay to approximate the desired frame rate
    inter_trigger = 1.0 / fps if fps > 0 else 0.0

    # Stream frame bytes directly to the provided binary output.
    while datetime.now() < end_time:
        start_trigger = time.perf_counter()
        # Issue a software trigger if supported.  The trigger command
        # will return immediately; the camera will respond by
        # generating a single frame.
        if trigger_cmd is not None:
            try:
                trigger_cmd.execute()
            except ic4.IC4Exception:
                pass

        buf = None
        deadline = time.perf_counter() + 2.0  # seconds
        while buf is None and time.perf_counter() < deadline:
            buf = sink.try_pop_output_buffer()
            if buf is None:
                time.sleep(0.001)
        if buf is None:
            # No frame arrived within the deadline; continue without writing.
            continue
        # Convert the image buffer into a NumPy array without copying and
        # stream its raw bytes immediately. For BayerGR8 the array has
        # shape (height, width, 1) and dtype uint8.
        arr = buf.numpy_wrap()
        try:
            output_stream.write(arr.tobytes())
            output_stream.flush()
        except (BrokenPipeError, ValueError):
            buf.release()
            break
        # Release the buffer back to the sink so it can be reused
        buf.release()
        # Delay before sending the next trigger to roughly match the
        # desired frame rate.  The time spent retrieving the buffer is
        # included in the measured duration, so only sleep if there's
        # time left.  When the loop is close to the end time, we break
        # without further delays.
        elapsed = time.perf_counter() - start_trigger
        remaining = inter_trigger - elapsed
        if remaining > 0 and datetime.now() + timedelta(seconds=remaining) < end_time:
            time.sleep(remaining)

    # Stop acquisition and the data stream.  Always stop the
    # acquisition before closing the device to release resources.
    try:
        grabber.acquisition_stop()
    except ic4.IC4Exception:
        pass
    try:
        grabber.stream_stop()
    except ic4.IC4Exception:
        pass


def main() -> None:
    """Main entry point for raw frame capture."""
    # Settings for capture.  Adjust these constants as needed.
    SERIAL_NUMBER = "05520128"
    WIDTH, HEIGHT = 1920, 1080
    FRAME_RATE = 30.0
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

    # Initialize the library.  This call must precede any other IC4
    # operations.  A matching Library.exit() is executed in a finally
    # block to ensure proper cleanup even if errors occur.
    ic4.Library.init()
    grabber = ic4.Grabber()
    sink = None
    sink_listener = None
    device_info = None
    ffmpeg_proc: subprocess.Popen[bytes] | None = None
    try:
        # Locate the camera by serial number and open it
        device_info = find_device_by_serial(SERIAL_NUMBER)
        grabber.device_open(device_info)
        # Configure resolution, pixel format, frame rate and trigger
        configure_camera_for_bayer_gr8(grabber, WIDTH, HEIGHT, FRAME_RATE)
        # Set up queue sink and allocate buffers
        sink, sink_listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
        )
        if ffmpeg_proc.stdin is None:
            raise RuntimeError("ffmpeg stdin was not created")

        try:
            # Record raw frames and push them directly to ffmpeg
            record_raw_frames(
                grabber,
                sink,
                CAPTURE_DURATION,
                ffmpeg_proc.stdin,
                fps=FRAME_RATE,
            )
        finally:
            try:
                ffmpeg_proc.stdin.close()
            except Exception:
                pass
            ffmpeg_proc.wait()
    finally:
        # Ensure the camera and library are cleanly closed
        try:
            if grabber.is_device_open:
                grabber.device_close()
        except ic4.IC4Exception:
            pass
        # Close ffmpeg on error paths
        if ffmpeg_proc is not None and ffmpeg_proc.poll() is None:
            try:
                if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                    ffmpeg_proc.stdin.close()
            except Exception:
                pass
            ffmpeg_proc.wait()
        # Drop references to IC4 objects while the library is still initialized
        sink = None
        sink_listener = None
        device_info = None
        grabber = None
        ic4.Library.exit()


if __name__ == "__main__":
    main()
