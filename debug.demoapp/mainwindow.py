
from threading import Lock
import sys

from PySide6.QtCore import QStandardPaths, QDir, QTimer, QEvent, QFileInfo, Qt, QCoreApplication
from PySide6.QtGui import QAction, QKeySequence, QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QLabel, QApplication, QFileDialog, QToolBar

import imagingcontrol4 as ic4

from resourceselector import ResourceSelector

GOT_PHOTO_EVENT = QEvent.Type(QEvent.Type.User + 1)
DEVICE_LOST_EVENT = QEvent.Type(QEvent.Type.User + 2)

class GotPhotoEvent(QEvent):
    def __init__(self, buffer: ic4.ImageBuffer):
        QEvent.__init__(self, GOT_PHOTO_EVENT)
        self.image_buffer = buffer

class MainWindow(QMainWindow):

    def __init__(self):
        QMainWindow.__init__(self)

        # Make sure the %appdata%/demoapp directory exists
        appdata_directory = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        QDir(appdata_directory).mkpath(".")

        self.save_pictures_directory = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        self.save_videos_directory = QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)

        self.device_file = appdata_directory + "/device.json"
        self.codec_config_file = appdata_directory + "/codecconfig.json"

        self.shoot_photo_mutex = Lock()
        self.shoot_photo = False

        self.capture_to_video = False
        self.video_capture_pause = False

        self.grabber = ic4.Grabber()
        self.grabber.event_add_device_lost(lambda g: QApplication.postEvent(self, QEvent(DEVICE_LOST_EVENT)))

        self.device_property_map = None
        self._balance_white_prop = None
        self._balance_white_last_value = None
        self._balance_white_info_logged = False
        self._balance_white_monitor_active = False
        self._balance_white_timer = QTimer(self)
        self._balance_white_timer.setInterval(500)
        self._balance_white_timer.timeout.connect(self._poll_balance_white)
        self._log_balance_white_python()

        class Listener(ic4.QueueSinkListener):
            def sink_connected(self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int) -> bool:
                # Allocate more buffers than suggested, because we temporarily take some buffers
                # out of circulation when saving an image or video files.
                sink.alloc_and_queue_buffers(min_buffers_required + 2)
                return True

            def sink_disconnected(self, sink: ic4.QueueSink):
                pass

            def frames_queued(listener, sink: ic4.QueueSink):
                buf = sink.pop_output_buffer()

                # Connect the buffer's chunk data to the device's property map
                # This allows for properties backed by chunk data to be updated
                self.device_property_map.connect_chunkdata(buf)

                with self.shoot_photo_mutex:
                    if self.shoot_photo:
                        self.shoot_photo = False

                        # Send an event to the main thread with a reference to 
                        # the main thread of our GUI. 
                        QApplication.postEvent(self, GotPhotoEvent(buf))

                if self.capture_to_video and not self.video_capture_pause:
                    try:
                        self.video_writer.add_frame(buf)
                    except ic4.IC4Exception as ex:
                        pass

        self.sink = ic4.QueueSink(Listener())

        self.property_dialog = None

        self.video_writer = ic4.VideoWriter(ic4.VideoWriterType.MP4_H264)

        self.createUI()

        try:
            self.display = self.video_widget.as_display()
            self.display.set_render_position(ic4.DisplayRenderPosition.STRETCH_CENTER)
        except Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

        if QFileInfo.exists(self.device_file):
            try:
                self.grabber.device_open_from_state_file(self.device_file)
                self.onDeviceOpened()
            except ic4.IC4Exception as e:
                QMessageBox.information(self, "", f"Loading last used device failed: {e}", QMessageBox.StandardButton.Ok)

        if QFileInfo.exists(self.codec_config_file):
            try:
                self.video_writer.property_map.deserialize_from_file(self.codec_config_file)
            except ic4.IC4Exception as e:
                QMessageBox.information(self, "", f"Loading last codec configuration failed: {e}", QMessageBox.StandardButton.Ok)

        self.updateControls()

    def createUI(self):
        self.resize(1024, 768)

        selector = ResourceSelector()

        self.device_select_act = QAction(selector.loadIcon("images/camera.png"), "&Select", self)
        self.device_select_act.setStatusTip("Select a video capture device")
        self.device_select_act.setShortcut(QKeySequence.Open)
        self.device_select_act.triggered.connect(self.onSelectDevice)

        self.device_properties_act = QAction(selector.loadIcon("images/imgset.png"), "&Properties", self)
        self.device_properties_act.setStatusTip("Show device property dialog")
        self.device_properties_act.triggered.connect(self.onDeviceProperties)

        self.device_driver_properties_act = QAction("&Driver Properties", self)
        self.device_driver_properties_act.setStatusTip("Show device driver property dialog")
        self.device_driver_properties_act.triggered.connect(self.onDeviceDriverProperties)

        self.trigger_mode_act = QAction(selector.loadIcon("images/triggermode.png"), "&Trigger Mode", self)
        self.trigger_mode_act.setStatusTip("Enable and disable trigger mode")
        self.trigger_mode_act.setCheckable(True)
        self.trigger_mode_act.triggered.connect(self.onToggleTriggerMode)

        self.start_live_act = QAction(selector.loadIcon("images/livestream.png"), "&Live Stream", self)
        self.start_live_act.setStatusTip("Start and stop the live stream")
        self.start_live_act.setCheckable(True)
        self.start_live_act.triggered.connect(self.startStopStream)

        self.shoot_photo_act = QAction(selector.loadIcon("images/photo.png"), "&Shoot Photo", self)
        self.shoot_photo_act.setStatusTip("Shoot and save a photo")
        self.shoot_photo_act.triggered.connect(self.onShootPhoto)

        self.record_start_act = QAction(selector.loadIcon("images/recordstart.png"), "&Capture Video", self)
        self.record_start_act.setToolTip("Capture vidoeo into MP4 file")
        self.record_start_act.setCheckable(True)
        self.record_start_act.triggered.connect(self.onStartStopCaptureVideo)

        self.record_pause_act = QAction(selector.loadIcon("images/recordpause.png"), "&Pause Capture Video", self)
        self.record_pause_act.setStatusTip("Pause video capture")
        self.record_pause_act.setCheckable(True)
        self.record_pause_act.triggered.connect(self.onPauseCaptureVideo)

        self.record_stop_act = QAction(selector.loadIcon("images/recordstop.png"), "&Stop Capture Video", self)
        self.record_stop_act.setStatusTip("Stop video capture")
        self.record_stop_act.triggered.connect(self.onStopCaptureVideo)

        self.codec_property_act = QAction(selector.loadIcon("images/gear.png"), "&Codec Properties", self)
        self.codec_property_act.setStatusTip("Configure the video codec")
        self.codec_property_act.triggered.connect(self.onCodecProperties)

        self.close_device_act = QAction("Close", self)
        self.close_device_act.setStatusTip("Close the currently opened device")
        self.close_device_act.setShortcuts(QKeySequence.Close)
        self.close_device_act.triggered.connect(self.onCloseDevice)

        exit_act = QAction("E&xit", self)
        exit_act.setShortcut(QKeySequence.Quit)
        exit_act.setStatusTip("Exit program")
        exit_act.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(exit_act)

        device_menu = self.menuBar().addMenu("&Device")
        device_menu.addAction(self.device_select_act)
        device_menu.addAction(self.device_properties_act)
        device_menu.addAction(self.device_driver_properties_act)
        device_menu.addAction(self.trigger_mode_act)
        device_menu.addAction(self.start_live_act)
        device_menu.addSeparator()
        device_menu.addAction(self.close_device_act)

        capture_menu = self.menuBar().addMenu("&Capture")
        capture_menu.addAction(self.shoot_photo_act)
        capture_menu.addAction(self.record_start_act)
        capture_menu.addAction(self.record_pause_act)
        capture_menu.addAction(self.record_stop_act)
        capture_menu.addAction(self.codec_property_act)

        toolbar = QToolBar(self)
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        toolbar.addAction(self.device_select_act)
        toolbar.addAction(self.device_properties_act)
        toolbar.addSeparator()
        toolbar.addAction(self.trigger_mode_act)
        toolbar.addSeparator()
        toolbar.addAction(self.start_live_act)
        toolbar.addSeparator()
        toolbar.addAction(self.shoot_photo_act)
        toolbar.addSeparator()
        toolbar.addAction(self.record_start_act)
        toolbar.addAction(self.record_pause_act)
        toolbar.addAction(self.record_stop_act)
        toolbar.addAction(self.codec_property_act)

        self.video_widget = ic4.pyside6.DisplayWidget()
        self.video_widget.setMinimumSize(640, 480)
        self.setCentralWidget(self.video_widget)

        self.statusBar().showMessage("Ready")
        self.statistics_label = QLabel("", self.statusBar())
        self.statusBar().addPermanentWidget(self.statistics_label)
        self.statusBar().addPermanentWidget(QLabel("  "))
        self.camera_label = QLabel(self.statusBar())
        self.statusBar().addPermanentWidget(self.camera_label)

        self.update_statistics_timer = QTimer()
        self.update_statistics_timer.timeout.connect(self.onUpdateStatisticsTimer)
        self.update_statistics_timer.start()

    def onCloseDevice(self):
        if self.grabber.is_streaming:
            self.startStopStream()
        
        try:
            self.grabber.device_close()
        except:
            pass

        self.device_property_map = None
        self._stop_balance_white_monitor()
        self.display.display_buffer(None)

        self.updateControls()

    def closeEvent(self, ev: QCloseEvent):
        if self.grabber.is_streaming:
            self.grabber.stream_stop()

        if self.grabber.is_device_valid:
            self.grabber.device_save_state_to_file(self.device_file)

    def customEvent(self, ev: QEvent):
        if ev.type() == DEVICE_LOST_EVENT:
            self.onDeviceLost()
        elif ev.type() == GOT_PHOTO_EVENT:
            self.savePhoto(ev.image_buffer)

    def onSelectDevice(self):
        dlg = ic4.pyside6.DeviceSelectionDialog(self.grabber, parent=self)
        if dlg.exec() == 1:
            if not self.property_dialog is None:
                self.property_dialog.update_grabber(self.grabber)
            
            self.onDeviceOpened()
        self.updateControls()

    def onDeviceProperties(self):
        self._log_balance_white("OPEN PROPERTYDIALOG")
        if self.property_dialog is None:
            self.property_dialog = ic4.pyside6.PropertyDialog(self.grabber, parent=self, title="Device Properties")
            # set default vis
        
        self.property_dialog.show()

    def onDeviceDriverProperties(self):
        dlg = ic4.pyside6.PropertyDialog(self.grabber.driver_property_map, parent=self, title="Device Driver Properties")
        # set default vis

        dlg.exec()

        self.updateControls()

    def onToggleTriggerMode(self):
        try:
            self.device_property_map.set_value(ic4.PropId.TRIGGER_MODE, self.trigger_mode_act.isChecked())
        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

    def onShootPhoto(self):
        with self.shoot_photo_mutex:
            self.shoot_photo = True

    def onUpdateStatisticsTimer(self):
        if not self.grabber.is_device_valid:
            return
        
        try:
            stats = self.grabber.stream_statistics
            text = f"Frames Delivered: {stats.sink_delivered} Dropped: {stats.device_transmission_error}/{stats.device_underrun}/{stats.transform_underrun}/{stats.sink_underrun}"
            self.statistics_label.setText(text)
            tooltip = (
                f"Frames Delivered: {stats.sink_delivered}"
                f"Frames Dropped:"
                f"  Device Transmission Error: {stats.device_transmission_error}"
                f"  Device Underrun: {stats.device_underrun}"
                f"  Transform Underrun: {stats.transform_underrun}"
                f"  Sink Underrun: {stats.sink_underrun}"
            )
            self.statistics_label.setToolTip(tooltip)
        except ic4.IC4Exception:
            pass

    def onDeviceLost(self):
        QMessageBox.warning(self, "", f"The video capture device is lost!", QMessageBox.StandardButton.Ok)

        # stop video
        self._stop_balance_white_monitor()

        self.updateCameraLabel()
        self.updateControls()

    def onDeviceOpened(self):
        self.device_property_map = self.grabber.device_property_map
        self._setup_balance_white_monitor()
        self._log_balance_white_info_once()

        trigger_mode = self.device_property_map.find(ic4.PropId.TRIGGER_MODE)
        trigger_mode.event_add_notification(self.updateTriggerControl)

        self.updateCameraLabel()

        # if start_stream_on_open
        self.startStopStream()

    def updateTriggerControl(self, p: ic4.Property):
        if not self.grabber.is_device_valid:
            self.trigger_mode_act.setChecked(False)
            self.trigger_mode_act.setEnabled(False)
        else:
            try:
                self.trigger_mode_act.setChecked(self.device_property_map.get_value_str(ic4.PropId.TRIGGER_MODE) == "On")
                self.trigger_mode_act.setEnabled(True)
            except ic4.IC4Exception:
                self.trigger_mode_act.setChecked(False)
                self.trigger_mode_act.setEnabled(False)

    def updateControls(self):
        if not self.grabber.is_device_open:
            self.statistics_label.clear()

        self.device_properties_act.setEnabled(self.grabber.is_device_valid)
        self.device_driver_properties_act.setEnabled(self.grabber.is_device_valid)
        self.start_live_act.setEnabled(self.grabber.is_device_valid)
        self.start_live_act.setChecked(self.grabber.is_streaming)
        self.shoot_photo_act.setEnabled(self.grabber.is_streaming)
        self.record_stop_act.setEnabled(self.capture_to_video)
        self.record_pause_act.setChecked(self.video_capture_pause)
        self.record_start_act.setChecked(self.capture_to_video)
        self.close_device_act.setEnabled(self.grabber.is_device_open)

        self.updateTriggerControl(None)

    def updateCameraLabel(self):
        try:
            info = self.grabber.device_info
            self.camera_label.setText(f"{info.model_name} {info.serial}")
        except ic4.IC4Exception:
            self.camera_label.setText("No Device")

    def onPauseCaptureVideo(self):
        self.video_capture_pause = self.record_pause_act.isChecked()

    def onStartStopCaptureVideo(self):
        if self.capture_to_video:
            self.stopCapturevideo()
            return
        
        filters = [
            "MP4 Video Files (*.mp4)"
        ]
        
        dialog = QFileDialog(self, "Capture Video")
        dialog.setNameFilters(filters)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDirectory(self.save_videos_directory)

        if dialog.exec():
            full_path = dialog.selectedFiles()[0]
            self.save_videos_directory = QFileInfo(full_path).absolutePath()

            fps = float(25)
            try:
                fps = self.device_property_map.get_value_float(ic4.PropId.ACQUISITION_FRAME_RATE)
            except:
                pass

            try:
                self.video_writer.begin_file(full_path, self.sink.output_image_type, fps)
            except ic4.IC4Exception as e:
                QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

            self.capture_to_video = True
            
        self.updateControls()

    def onStopCaptureVideo(self):
        self.capture_to_video = False
        self.video_writer.finish_file()
        self.updateControls()

    def onCodecProperties(self):
        dlg = ic4.pyside6.PropertyDialog(self.video_writer.property_map, self, "Codec Settings")
        # set default vis
        if dlg.exec() == 1:
            self.video_writer.property_map.serialize_to_file(self.codec_config_file)

    def startStopStream(self):
        try:
            if self.grabber.is_device_valid:
                if self.grabber.is_streaming:
                    self._log_balance_white("STREAM STOP")
                    self.grabber.stream_stop()
                    if self.capture_to_video:
                        self.onStopCaptureVideo()
                else:
                    self._log_balance_white("STREAM START")
                    self.grabber.stream_setup(self.sink, self.display)

        except ic4.IC4Exception as e:
            QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

        self.updateControls()

    def savePhoto(self, image_buffer: ic4.ImageBuffer):
        filters = [
            "Bitmap(*.bmp)",
            "JPEG (*.jpg)",
            "Portable Network Graphics (*.png)",
            "TIFF (*.tif)"
        ]
        
        dialog = QFileDialog(self, "Save Photo")
        dialog.setNameFilters(filters)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDirectory(self.save_pictures_directory)

        if dialog.exec():
            selected_filter = dialog.selectedNameFilter()

            full_path = dialog.selectedFiles()[0]
            self.save_pictures_directory = QFileInfo(full_path).absolutePath()

            try:
                if selected_filter == filters[0]:
                    image_buffer.save_as_bmp(full_path)
                elif selected_filter == filters[1]:
                    image_buffer.save_as_jpeg(full_path)
                elif selected_filter == filters[2]:
                    image_buffer.save_as_png(full_path)
                else:
                    image_buffer.save_as_tiff(full_path)
            except ic4.IC4Exception as e:
                QMessageBox.critical(self, "", f"{e}", QMessageBox.StandardButton.Ok)

    def _log_balance_white(self, message: str) -> None:
        print(f"[BalanceWhiteAuto] {message}")

    def _log_balance_white_exception(self, prefix: str, exc: Exception) -> None:
        self._log_balance_white(f"{prefix} EXC: {type(exc).__name__} {exc}")

    def _log_balance_white_python(self) -> None:
        self._log_balance_white(f"PYTHON EXECUTABLE: {sys.executable}")

    def _log_balance_white_info_once(self) -> None:
        if self._balance_white_info_logged:
            return
        self._balance_white_info_logged = True

        if self.device_property_map is None:
            self._log_balance_white("STARTUP current: EXC: device_property_map is None")
            self._log_balance_white("STARTUP entries: EXC: device_property_map is None")
            return

        try:
            prop = self.device_property_map.find("BalanceWhiteAuto")
            self._balance_white_prop = prop
        except Exception as exc:
            self._log_balance_white_exception("STARTUP find BalanceWhiteAuto", exc)
            prop = None

        if prop is not None and hasattr(prop, "entries"):
            try:
                entries = prop.entries
                for entry in entries:
                    self._log_balance_white(
                        f"STARTUP entry: {getattr(entry, 'name', None)} {getattr(entry, 'value', None)}"
                    )
            except Exception as exc:
                self._log_balance_white_exception("STARTUP entries", exc)
        else:
            self._log_balance_white("STARTUP entries: EXC: entries not available")

        try:
            current = self.device_property_map.get_value_str("BalanceWhiteAuto")
            self._log_balance_white(f"STARTUP current: {current}")
        except Exception as exc:
            self._log_balance_white_exception("STARTUP current", exc)

    def _setup_balance_white_monitor(self) -> None:
        if self._balance_white_monitor_active:
            return
        self._balance_white_monitor_active = True
        self._balance_white_last_value = None

        if self.device_property_map is None:
            self._log_balance_white("MONITOR setup: EXC: device_property_map is None")
            return

        try:
            self._balance_white_prop = self.device_property_map.find("BalanceWhiteAuto")
        except Exception as exc:
            self._log_balance_white_exception("MONITOR find BalanceWhiteAuto", exc)
            self._balance_white_prop = None

        if self._balance_white_prop is not None and hasattr(self._balance_white_prop, "event_add_notification"):
            try:
                self._balance_white_prop.event_add_notification(self._on_balance_white_notification)
                self._log_balance_white("MONITOR notify: registered")
            except Exception as exc:
                self._log_balance_white_exception("MONITOR notify", exc)
        else:
            self._log_balance_white("MONITOR notify: not available")

        self._balance_white_timer.start()

    def _stop_balance_white_monitor(self) -> None:
        if not self._balance_white_monitor_active:
            return
        self._balance_white_timer.stop()
        self._balance_white_monitor_active = False
        self._balance_white_prop = None
        self._balance_white_last_value = None

    def _poll_balance_white(self) -> None:
        if self.device_property_map is None:
            self._log_balance_white("POLL EXC: device_property_map is None")
            return
        try:
            value = self.device_property_map.get_value_str("BalanceWhiteAuto")
        except Exception as exc:
            self._log_balance_white_exception("POLL", exc)
            return

        if value == self._balance_white_last_value:
            self._log_balance_white(f"POLL {value} (same)")
        else:
            self._log_balance_white(f"POLL {value}")
            self._balance_white_last_value = value

    def _on_balance_white_notification(self, prop: ic4.Property) -> None:
        if self.device_property_map is None:
            self._log_balance_white("NOTIFY EXC: device_property_map is None")
            return
        try:
            value = self.device_property_map.get_value_str("BalanceWhiteAuto")
            self._log_balance_white(f"NOTIFY {value}")
        except Exception as exc:
            self._log_balance_white_exception("NOTIFY", exc)
