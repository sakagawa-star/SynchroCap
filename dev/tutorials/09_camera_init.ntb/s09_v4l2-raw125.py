import sys
import time
import shlex
import subprocess

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


def configure_camera_for_bayer_gr8(grabber: ic4.Grabber, width: int, height: int, fps: float) -> str | None:
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
    # Prefer BGR8; fall back to RGB8 if unsupported.  Actual format is printed once.
    applied_format = None
    try:
        dmap.set_value(ic4.PropId.PIXEL_FORMAT, "BGR8")
        applied_format = "BGR8"
    except ic4.IC4Exception:
        pass
    if applied_format is None:
        try:
            dmap.set_value(ic4.PropId.PIXEL_FORMAT, "RGB8")
            applied_format = "RGB8"
        except ic4.IC4Exception:
            pass
    if applied_format is None:
        # Fail fast when neither BGR8 nor RGB8 could be applied.
        raise RuntimeError("Failed to set PIXEL_FORMAT to BGR8 or RGB8")
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

    try:
        # PropertyMap does not expose get_value() for strings; use get_value_str().
        current_pf = dmap.get_value_str(ic4.PropId.PIXEL_FORMAT)
        if current_pf:
            applied_format = str(current_pf)
    except ic4.IC4Exception:
        pass
    print(f"Configured PixelFormat: {applied_format or 'unknown'}")
    return applied_format


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
    # Accept color 8-bit format; RGB8 is absent in this ic4 build, so avoid AttributeError.
    accepted_formats = [ic4.PixelFormat.BGR8]
    if hasattr(ic4.PixelFormat, "RGB8"):
        accepted_formats.append(ic4.PixelFormat.RGB8)
    sink = ic4.QueueSink(
        listener,
        accepted_pixel_formats=accepted_formats,
    )
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
    fps: float = 30.0,
    width: int = 1920,
    height: int = 1080,
    pixel_format: str | None = None,
) -> None:
    # Launch ffmpeg to convert BGR/RGB 8-bit -> yuv420p and push into v4l2loopback.
    ffmpeg_pix_fmt = "bgr24" if pixel_format and "BGR" in str(pixel_format).upper() else "rgb24"
    ffmpeg_cmd = (
        "ffmpeg -loglevel error "
        f"-f rawvideo -pix_fmt {ffmpeg_pix_fmt} -s {width}x{height} -framerate {fps} -i - "
        "-vf format=yuv420p "
        "-f v4l2 /dev/video1"
    )
    try:
        proc = subprocess.Popen(shlex.split(ffmpeg_cmd), stdin=subprocess.PIPE)
    except Exception as exc:
        print(f"Failed to start ffmpeg: {exc}", file=sys.stderr)
        raise
    if proc.stdin is None:
        print("ffmpeg stdin pipe is not available", file=sys.stderr)
        proc.kill()
        proc.wait()
        raise RuntimeError("ffmpeg stdin unavailable")

    try:
        grabber.acquisition_start()

        trigger_cmd = None
        try:
            prop = grabber.driver_property_map.find(ic4.PropId.TRIGGER_SOFTWARE)
            if isinstance(prop, ic4.PropCommand):
                trigger_cmd = prop
        except ic4.IC4Exception:
            trigger_cmd = None

        # Compute an inter‑trigger delay to approximate the desired frame rate
        inter_trigger = 1.0 / fps if fps > 0 else 0.0

        # Stream frame bytes directly into ffmpeg's stdin.
        try:
            while True:
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
                # stream its raw bytes immediately. For BGR/RGB8 the array has
                # shape (height, width, 3) and dtype uint8.
                arr = buf.numpy_wrap()
                try:
                    # Push raw color data straight into ffmpeg (v4l2loopback output).
                    proc.stdin.write(arr.tobytes())
                except Exception as exc:
                    print(f"Failed to pipe frame to ffmpeg: {exc}", file=sys.stderr)
                    raise
                # Release the buffer back to the sink so it can be reused
                buf.release()
                # Delay before sending the next trigger to roughly match the
                # desired frame rate.  The time spent retrieving the buffer is
                # included in the measured duration, so only sleep if there's
                # time left.
                elapsed = time.perf_counter() - start_trigger
                remaining = inter_trigger - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("Stopping capture due to KeyboardInterrupt", file=sys.stderr)
    finally:
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
        try:
            proc.stdin.close()
        except Exception as exc:
            print(f"Failed to close ffmpeg stdin: {exc}", file=sys.stderr)
        try:
            proc.wait()
        except Exception as exc:
            print(f"Failed to wait for ffmpeg termination: {exc}", file=sys.stderr)


def main() -> None:
    """Main entry point for raw frame capture."""
    # Settings for capture.  Adjust these constants as needed.
    SERIAL_NUMBER = "05520125"
    WIDTH, HEIGHT = 1920, 1080
    FRAME_RATE = 30.0

    # Initialize the library.  This call must precede any other IC4
    # operations.  A matching Library.exit() is executed in a finally
    # block to ensure proper cleanup even if errors occur.
    ic4.Library.init()
    grabber = ic4.Grabber()
    sink = None
    sink_listener = None
    device_info = None
    try:
        # Locate the camera by serial number and open it
        device_info = find_device_by_serial(SERIAL_NUMBER)
        grabber.device_open(device_info)
        # Configure resolution, pixel format, frame rate and trigger
        pixel_format = configure_camera_for_bayer_gr8(grabber, WIDTH, HEIGHT, FRAME_RATE)
        # Set up queue sink and allocate buffers
        sink, sink_listener = allocate_queue_sink(grabber, WIDTH, HEIGHT)
        # Record raw frames indefinitely until interrupted
        record_raw_frames(
            grabber,
            sink,
            fps=FRAME_RATE,
            width=WIDTH,
            height=HEIGHT,
            pixel_format=pixel_format,
        )
    finally:
        # Ensure the camera and library are cleanly closed
        try:
            if grabber.is_device_open:
                grabber.device_close()
        except ic4.IC4Exception:
            pass
        # Drop references to IC4 objects while the library is still initialized
        sink = None
        sink_listener = None
        device_info = None
        grabber = None
        ic4.Library.exit()


if __name__ == "__main__":
    main()
