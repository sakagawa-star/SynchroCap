
import imagingcontrol4 as ic4
import cv2
import numpy as np

def example_record_mp4_h265():
    # Let the user select one of the connected cameras
    device_list = ic4.DeviceEnum.devices()
    for i, dev in enumerate(device_list):
        print(f"[{i}] {dev.model_name} ({dev.serial}) [{dev.interface.display_name}]")
    print(f"Select device [0..{len(device_list) - 1}]: ", end="")
    selected_index = int(input())
    dev_info = device_list[selected_index]

    # Open the selected device in a new Grabber
    grabber = ic4.Grabber(dev_info)
    map = grabber.device_property_map

    map.try_set_value(ic4.PropId.BALANCE_WHITE_AUTO, True)

    # Reset all device settings to default
    # Not all devices support this, so ignore possible errors
    map.try_set_value(ic4.PropId.USER_SET_SELECTOR, "Default")
    map.try_set_value(ic4.PropId.USER_SET_LOAD, 1)

    # OpenCV VideoWriter (H.265)
    fourcc = cv2.VideoWriter_fourcc(*"HEVC")
    writer = None

    # Define a listener class to receive queue sink notifications
    # The listener will pass incoming frames to the video writer
    class Listener(ic4.QueueSinkListener):
        #def __init__(self, video_writer: ic4.VideoWriter):
        def __init__(self):
            #self.video_writer = video_writer
            self.video_writer = None
            self.counter = 0
            self.do_write_frames = False
            self.frame_width = None
            self.frame_height = None
            self._logged_debug = False

        def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
            # No need to configure anything, just accept the connection
            self.frame_width = image_type.width
            self.frame_height = image_type.height
            return True

        def frames_queued(self, sink: ic4.QueueSink):
            #print("frames_queued called")
            buf = sink.pop_output_buffer()
            if buf is None:
                return
            if self.do_write_frames and self.video_writer is not None:
                # numpy 配列に変換
                frame = buf.numpy_wrap()
                if self.frame_width is not None and self.frame_height is not None:
                    frame = frame[:self.frame_height, :self.frame_width]
                if not frame.flags["C_CONTIGUOUS"]:
                    frame = np.ascontiguousarray(frame)
                # GPU転送
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(frame)
                # BayerGR8 -> BGR
                bgr_gpu = cv2.cuda.cvtColor(gpu_mat, cv2.COLOR_BayerGR2BGR)
                bgr = bgr_gpu.download()
                if bgr.shape[0] != self.frame_height:
                    bgr = bgr[:self.frame_height]
                if bgr.shape[1] != self.frame_width:
                    bgr = bgr[:, :self.frame_width]
                if not bgr.flags["C_CONTIGUOUS"]:
                    bgr = np.ascontiguousarray(bgr)
                if not self._logged_debug:
                    print("[debug] raw frame shape", frame.shape, "stride", frame.strides, "dtype", frame.dtype)
                    print("[debug] bgr frame shape", bgr.shape, "stride", bgr.strides, "dtype", bgr.dtype)
                    self._logged_debug = True
                self.video_writer.write(bgr)
                self.counter += 1
            buf.release()

            

        def enable_recording(self, enable: bool):
            if enable:
                self.counter = 0
            self.do_write_frames = enable

        def num_frames_written(self):
            return self.counter

    # Create an instance of the listener type defined above, specifying a partial file name
    #listener = Listener(video_writer)
    listener = Listener()
    # Capture BayerGR8 frames for GPU processing
    sink = ic4.QueueSink(listener, accepted_pixel_formats=[ic4.PixelFormat.BayerGR8])

    # Create a QueueSink to capture all images arriving from the video capture device
    #sink = ic4.QueueSink(listener, accepted_pixel_formats=[ic4.PixelFormat.BGR8])

    # Start the video stream into the sink
    grabber.stream_setup(sink)

    image_type = sink.output_image_type
    frame_rate = map[ic4.PropId.ACQUISITION_FRAME_RATE].value

    print("Stream started.")
    print(f"ImageType: {image_type}")
    print(f"AcquisitionFrameRate {frame_rate}")
    print()

    for i in range(1):
        input("Press ENTER to begin recording a video file")

        file_name = f"video{i}.mp4"

        # Begin writing a video file with a name, image type and playback rate
        #video_writer.begin_file(file_name, image_type, frame_rate)

        # Instruct our QueueSinkListener to write frames into the video writer
        #listener.enable_recording(True)

        #input("Recording started. Press ENTER to stop")

        # Stop writing frames into the video writer
        #listener.enable_recording(False)

        # Finalize the currently opened video file
        #video_writer.finish_file()

        #print(f"Saved video file {file_name}.")
        #print(f"Wrote {listener.num_frames_written()} frames.")
        #print()
        # Open OpenCV VideoWriter
        writer = cv2.VideoWriter(file_name, fourcc, frame_rate, (image_type.width, image_type.height))
        listener.video_writer = writer
        listener.enable_recording(True)
        input("Recording started. Press ENTER to stop")
        listener.enable_recording(False)
        writer.release()
        listener.video_writer = None
        print(f"Saved video file {file_name}.")
        print(f"Wrote {listener.num_frames_written()} frames.")
        print()


    # We have to call streamStop before exiting the function, to make sure the listener object is not destroyed before the stream is stopped
    grabber.stream_stop()
    grabber.device_close()

if __name__ == "__main__":
    with ic4.Library.init_context(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR):

        example_record_mp4_h265()
