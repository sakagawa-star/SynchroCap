"""
録画制御モジュール

PTP同期された複数カメラの同時録画を管理する。
設計書: feature_design.md
"""

from __future__ import annotations

import csv
import os
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, TextIO

import imagingcontrol4 as ic4


# =============================================================================
# SRAW file format constants
# =============================================================================

SRAW_MAGIC = b'SRAW'
FRAM_MAGIC = b'FRAM'
SRAW_VERSION = 1
PIXEL_FORMAT_BAYER_GR8 = 0
DEFAULT_FRAMES_PER_FILE = 1000


# =============================================================================
# Phase 1: データ構造
# =============================================================================

class RecordingState(Enum):
    """録画状態を表す列挙型"""
    IDLE = "idle"                # 待機中
    PREPARING = "preparing"      # PTP待機・オフセット計算中
    SCHEDULED = "scheduled"      # スケジュール確定、開始待ち
    RECORDING = "recording"      # 録画中
    STOPPING = "stopping"        # 停止処理中
    ERROR = "error"              # エラー発生


class OutputFormat(Enum):
    """出力フォーマット"""
    MP4 = "mp4"
    RAW = "raw"


@dataclass
class RecordingSlot:
    """各カメラスロットの録画コンテキスト"""
    serial: str
    grabber: ic4.Grabber
    recording_sink: Optional[ic4.QueueSink] = None
    recording_listener: Optional[ic4.QueueSinkListener] = None
    ffmpeg_proc: Optional[subprocess.Popen] = None
    output_path: Optional[Path] = None
    frame_count: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    trigger_interval_fps: float = 50.0  # Action Scheduler用トリガー間隔
    delta_ns: int = 0  # ホストとの時刻オフセット
    # CSV関連
    csv_path: Optional[Path] = None
    csv_file: Optional[TextIO] = None
    csv_writer: Optional[Any] = None
    csv_buffer: List[List] = field(default_factory=list)
    # Raw録画関連
    raw_file: Optional[BinaryIO] = None
    raw_file_start_frame: int = 0
    raw_files_created: List[str] = field(default_factory=list)


class _RecordingQueueSinkListener(ic4.QueueSinkListener):
    """録画用QueueSinkリスナー"""

    def sink_connected(
        self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int
    ) -> bool:
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        pass

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        # フレーム処理は録画スレッドで行うため、ここでは何もしない
        pass


# =============================================================================
# SRAW ヘッダ書き込み関数
# =============================================================================


def _write_file_header(
    file: BinaryIO,
    serial: str,
    recording_start_ns: int,
    width: int,
    height: int,
    pixel_format: int,
) -> None:
    """SRAWファイルヘッダ (40 bytes) を書き込む"""
    serial_bytes = serial.encode('ascii')[:15].ljust(16, b'\x00')
    header = struct.pack(
        '<4sI16sqHHHH',
        SRAW_MAGIC,
        SRAW_VERSION,
        serial_bytes,
        recording_start_ns,
        width,
        height,
        pixel_format,
        0,  # reserved
    )
    file.write(header)


def _write_frame_header(
    file: BinaryIO,
    payload_size: int,
    frame_index: int,
    timestamp_ns: int,
) -> None:
    """SRAWフレームヘッダ (24 bytes) を書き込む"""
    header = struct.pack(
        '<4sIQq',
        FRAM_MAGIC,
        payload_size,
        frame_index,
        timestamp_ns,
    )
    file.write(header)


# =============================================================================
# Phase 2: RecordingController 基本構造
# =============================================================================

class RecordingController:
    """
    録画のライフサイクル全体を管理するクラス

    使用方法:
        controller = RecordingController()
        success = controller.prepare(slots, start_delay_s=8, duration_s=30)
        if success:
            controller.start()
    """

    # 定数
    PTP_SLAVE_TIMEOUT_S = 30.0
    PTP_POLL_INTERVAL_S = 1.0
    QUEUE_BUFFER_COUNT = 500
    FFMPEG_FLUSH_INTERVAL = 30
    RAW_FLUSH_INTERVAL = 30
    CSV_FLUSH_INTERVAL = 10

    def __init__(self, on_state_changed: Optional[Callable[[RecordingState, str], None]] = None):
        """
        Args:
            on_state_changed: 状態変更時のコールバック (state, message) -> None
        """
        self._state = RecordingState.IDLE
        self._slots: List[RecordingSlot] = []
        self._start_delay_s: float = 0.0
        self._duration_s: float = 0.0
        self._output_dir: Optional[Path] = None
        self._threads: Dict[str, threading.Thread] = {}
        self._host_target_ns: int = 0
        self._on_state_changed = on_state_changed
        self._error_message: str = ""
        self._output_format: OutputFormat = OutputFormat.MP4
        self._frames_per_file: int = DEFAULT_FRAMES_PER_FILE

    # -------------------------------------------------------------------------
    # 公開メソッド
    # -------------------------------------------------------------------------

    def get_state(self) -> RecordingState:
        """現在の状態を取得"""
        return self._state

    def get_error_message(self) -> str:
        """エラーメッセージを取得"""
        return self._error_message

    def is_recording(self) -> bool:
        """録画中かどうか"""
        return self._state in (RecordingState.SCHEDULED, RecordingState.RECORDING)

    def prepare(
        self,
        slots: List[Dict[str, Any]],
        start_delay_s: float,
        duration_s: float,
        output_format: OutputFormat = OutputFormat.MP4,
        frames_per_file: int = DEFAULT_FRAMES_PER_FILE,
    ) -> bool:
        """
        録画準備を行う

        Args:
            slots: MultiViewWidgetのスロット情報リスト
            start_delay_s: 開始遅延（秒）
            duration_s: 録画時間（秒）
            output_format: 出力フォーマット（MP4 or RAW）
            frames_per_file: Rawファイル1つあたりのフレーム数

        Returns:
            準備成功したかどうか
        """
        if self._state != RecordingState.IDLE:
            self._set_error("Recording is already in progress")
            return False

        self._start_delay_s = start_delay_s
        self._duration_s = duration_s
        self._output_format = output_format
        self._frames_per_file = frames_per_file
        self._slots = []
        self._threads = {}
        self._error_message = ""

        # 出力ディレクトリ作成
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._output_dir = Path("captures") / timestamp
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._set_error(f"Failed to create output directory: {e}")
            return False

        # スロットからRecordingSlotを構築
        for slot in slots:
            grabber = slot.get("grabber")
            if not isinstance(grabber, ic4.Grabber):
                continue
            if not grabber.is_device_valid:
                continue

            try:
                device_info = grabber.device_info
                serial = getattr(device_info, "serial", None) or getattr(device_info, "serial_number", "unknown")
            except ic4.IC4Exception:
                continue

            trigger_interval_fps = slot.get("trigger_interval_fps", 50.0)
            recording_slot = RecordingSlot(
                serial=str(serial),
                grabber=grabber,
                trigger_interval_fps=float(trigger_interval_fps),
            )
            self._slots.append(recording_slot)

        if not self._slots:
            self._set_error("No valid cameras found")
            return False

        self._set_state(RecordingState.PREPARING, f"Preparing {len(self._slots)} cameras...")

        # Phase 3: PTP Slave待機
        if not self._wait_all_slaves():
            self._cleanup()
            return False

        # Phase 4: オフセット計算とスケジュール設定
        if not self._calculate_and_schedule():
            self._cleanup()
            return False

        # Phase 5: ffmpeg起動と録画sink準備
        if not self._setup_recording():
            self._cleanup()
            return False

        self._set_state(RecordingState.SCHEDULED, f"Scheduled to start in {start_delay_s:.1f}s")
        return True

    def start(self) -> bool:
        """
        録画スレッドを開始する
        prepare()成功後に呼び出す

        Returns:
            開始成功したかどうか
        """
        if self._state != RecordingState.SCHEDULED:
            self._set_error("Not in scheduled state")
            return False

        # 各カメラの録画スレッドを開始
        for slot in self._slots:
            thread = threading.Thread(
                target=self._worker,
                args=(slot,),
                name=f"CaptureThread-{slot.serial}",
                daemon=True,
            )
            self._threads[slot.serial] = thread
            thread.start()

        self._set_state(RecordingState.RECORDING, "Recording...")

        # 録画終了を監視するスレッドを開始
        monitor_thread = threading.Thread(
            target=self._monitor_completion,
            name="RecordingMonitor",
            daemon=True,
        )
        monitor_thread.start()

        return True

    # -------------------------------------------------------------------------
    # Phase 3: PTP Slave待機
    # -------------------------------------------------------------------------

    def _wait_all_slaves(self) -> bool:
        """全カメラがPTP Slave状態になるまで待機"""
        deadline = time.monotonic() + self.PTP_SLAVE_TIMEOUT_S
        total = len(self._slots)

        while time.monotonic() < deadline:
            slave_count = 0
            master_count = 0
            other_count = 0

            for slot in self._slots:
                status = self._get_ptp_status(slot.grabber)
                if status == "Slave":
                    slave_count += 1
                elif status == "Master":
                    master_count += 1
                else:
                    other_count += 1

            if slave_count == total:
                self._log(f"PTP OK: all {total} cameras are Slave")
                return True

            self._set_state(
                RecordingState.PREPARING,
                f"Waiting for PTP... (Slave: {slave_count}/{total})"
            )
            time.sleep(self.PTP_POLL_INTERVAL_S)

        self._set_error(
            f"PTP synchronization failed. Slave: {slave_count}, Master: {master_count}, Other: {other_count}"
        )
        return False

    def _get_ptp_status(self, grabber: ic4.Grabber) -> Optional[str]:
        """カメラのPTPステータスを取得"""
        for prop_name in ["PtpStatus", "GevIEEE1588Status"]:
            try:
                return str(grabber.device_property_map.get_value_str(prop_name))
            except ic4.IC4Exception:
                continue
        return None

    # -------------------------------------------------------------------------
    # Phase 4: オフセット計算とスケジュール設定
    # -------------------------------------------------------------------------

    def _calculate_and_schedule(self) -> bool:
        """オフセット計算とAction Scheduler設定"""

        # カメラパラメータを取得
        for slot in self._slots:
            try:
                prop_map = slot.grabber.device_property_map
                slot.width = prop_map.get_value_int(ic4.PropId.WIDTH)
                slot.height = prop_map.get_value_int(ic4.PropId.HEIGHT)
                slot.fps = prop_map.get_value_float(ic4.PropId.ACQUISITION_FRAME_RATE)
                self._log(f"[{slot.serial}] {slot.width}x{slot.height} @ {slot.fps:.2f}fps")
            except ic4.IC4Exception as e:
                self._set_error(f"Failed to get camera parameters for {slot.serial}: {e}")
                return False

        # TIMESTAMP_LATCHでオフセット計算
        host_ref_before_ns = time.time_ns()
        for slot in self._slots:
            try:
                slot.grabber.device_property_map.set_value(ic4.PropId.TIMESTAMP_LATCH, True)
            except ic4.IC4Exception as e:
                self._log(f"[{slot.serial}] Warning: TIMESTAMP_LATCH failed: {e}")
        host_ref_after_ns = time.time_ns()
        host_ref_ns = (host_ref_before_ns + host_ref_after_ns) // 2

        # 各カメラのオフセットを計算
        for slot in self._slots:
            try:
                camera_time_ns = int(
                    slot.grabber.device_property_map.get_value_float(ic4.PropId.TIMESTAMP_LATCH_VALUE)
                )
                slot.delta_ns = camera_time_ns - host_ref_ns
                delta_ms = slot.delta_ns / 1_000_000.0
                self._log(f"[{slot.serial}] delta_ms={delta_ms:+.3f}")
            except ic4.IC4Exception as e:
                self._set_error(f"Failed to get timestamp for {slot.serial}: {e}")
                return False

        # スケジュール時刻計算
        self._host_target_ns = time.time_ns() + int(self._start_delay_s * 1_000_000_000)

        # 各カメラにAction Scheduler設定
        for slot in self._slots:
            if not self._configure_action_scheduler(slot):
                return False

        return True

    def _configure_action_scheduler(self, slot: RecordingSlot) -> bool:
        """Action SchedulerとTrigger設定"""
        prop_map = slot.grabber.device_property_map

        # Trigger設定（device_property_mapを使用）
        try:
            prop_map.set_value(ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
        except ic4.IC4Exception as e:
            self._log(f"[{slot.serial}] Warning: failed to set TRIGGER_SELECTOR: {e}")

        try:
            prop_map.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")
        except ic4.IC4Exception as e:
            self._log(f"[{slot.serial}] Warning: failed to set TRIGGER_SOURCE: {e}")

        try:
            prop_map.set_value(ic4.PropId.TRIGGER_MODE, "On")
        except ic4.IC4Exception as e:
            self._log(f"[{slot.serial}] Warning: failed to set TRIGGER_MODE: {e}")

        # Action Scheduler設定（これは必須）
        camera_target_ns = self._host_target_ns + slot.delta_ns
        interval_us = round(1_000_000 / slot.trigger_interval_fps)

        try:
            prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
        except ic4.IC4Exception as e:
            self._log(f"[{slot.serial}] Warning: failed to cancel action scheduler: {e}")

        try:
            prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, int(camera_target_ns))
        except ic4.IC4Exception as e:
            self._set_error(f"Failed to set ACTION_SCHEDULER_TIME for {slot.serial}: {e}")
            return False

        try:
            prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, interval_us)
        except ic4.IC4Exception as e:
            self._set_error(f"Failed to set ACTION_SCHEDULER_INTERVAL for {slot.serial}: {e}")
            return False

        try:
            prop_map.set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
        except ic4.IC4Exception as e:
            self._set_error(f"Failed to commit ACTION_SCHEDULER for {slot.serial}: {e}")
            return False

        self._log(f"[{slot.serial}] Scheduled at {camera_target_ns}, interval={interval_us}us")
        return True

    # -------------------------------------------------------------------------
    # Phase 5: ffmpeg起動と録画sink準備
    # -------------------------------------------------------------------------

    def _setup_recording(self) -> bool:
        """録画用リソース準備（ffmpeg or Rawファイル + sink）"""
        for slot in self._slots:
            # CSV初期化（MP4/Raw共通）
            slot.csv_path = self._output_dir / f"cam{slot.serial}.csv"
            try:
                slot.csv_file = open(slot.csv_path, "w", newline="", encoding="utf-8")
                slot.csv_writer = csv.writer(slot.csv_file)
                slot.csv_writer.writerow(["frame_number", "device_timestamp_ns"])
                slot.csv_buffer = []
            except Exception as e:
                self._log(f"[{slot.serial}] Warning: failed to open CSV: {e}")
                slot.csv_file = None
                slot.csv_writer = None

            if self._output_format == OutputFormat.MP4:
                # MP4: 出力パス設定 + ffmpeg起動
                slot.output_path = self._output_dir / f"cam{slot.serial}.mp4"

                ffmpeg_cmd = self._build_ffmpeg_command(slot)
                try:
                    slot.ffmpeg_proc = subprocess.Popen(
                        ffmpeg_cmd,
                        stdin=subprocess.PIPE,
                    )
                except Exception as e:
                    self._set_error(f"Failed to start ffmpeg for {slot.serial}: {e}")
                    return False

                if slot.ffmpeg_proc.stdin is None:
                    self._set_error(f"ffmpeg stdin not available for {slot.serial}")
                    return False
            # Raw: ffmpegは起動しない（ファイルは_worker_raw内で動的に作成）

            # プレビュー停止（MP4/Raw共通）
            try:
                if slot.grabber.is_streaming:
                    slot.grabber.stream_stop()
            except ic4.IC4Exception as e:
                self._log(f"[{slot.serial}] Warning: stream_stop failed: {e}")

            # 録画用sink作成（MP4/Raw共通）
            slot.recording_listener = _RecordingQueueSinkListener()
            slot.recording_sink = ic4.QueueSink(
                slot.recording_listener,
                accepted_pixel_formats=[ic4.PixelFormat.BayerGR8],
            )

            # stream_setup (DEFER)（MP4/Raw共通）
            try:
                slot.grabber.stream_setup(
                    slot.recording_sink,
                    setup_option=ic4.StreamSetupOption.DEFER_ACQUISITION_START,
                )
                slot.recording_sink.alloc_and_queue_buffers(self.QUEUE_BUFFER_COUNT)
            except ic4.IC4Exception as e:
                self._set_error(f"Failed to setup recording stream for {slot.serial}: {e}")
                return False

            self._log(f"[{slot.serial}] Recording setup complete ({self._output_format.value})")

        # Raw: ディスク使用量の推定表示
        if self._output_format == OutputFormat.RAW:
            self._log_raw_disk_estimate()

        return True

    def _build_ffmpeg_command(self, slot: RecordingSlot) -> List[str]:
        """ffmpegコマンドを構築"""
        return [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel", "error",
            "-f", "rawvideo",
            "-pix_fmt", "bayer_grbg8",
            "-s", f"{slot.width}x{slot.height}",
            "-framerate", f"{slot.trigger_interval_fps}",
            "-i", "-",
            "-vf", "format=yuv420p",
            "-c:v", "hevc_nvenc",
            "-b:v", "2200k",
            "-maxrate", "2200k",
            "-bufsize", "4400k",
            "-preset", "p4",
            str(slot.output_path),
        ]

    def _log_raw_disk_estimate(self) -> None:
        """Raw録画の推定ディスク使用量をログ出力"""
        if not self._slots:
            return
        slot = self._slots[0]
        bytes_per_frame = slot.width * slot.height  # BayerGR8: 1 byte/pixel
        expected_frames = int(self._duration_s * slot.trigger_interval_fps)
        per_cam_bytes = expected_frames * bytes_per_frame
        total_bytes = per_cam_bytes * len(self._slots)
        per_cam_gib = per_cam_bytes / (1024 ** 3)
        total_gib = total_bytes / (1024 ** 3)
        self._log(
            f"[RAW] Estimated size: {per_cam_gib:.2f} GiB/camera, "
            f"total {total_gib:.2f} GiB ({len(self._slots)} cameras)"
        )

    # -------------------------------------------------------------------------
    # Phase 6: 録画スレッドと停止処理
    # -------------------------------------------------------------------------

    def _worker(self, slot: RecordingSlot) -> None:
        """録画ワーカースレッド（フォーマットに応じて分岐）"""
        if self._output_format == OutputFormat.RAW:
            self._worker_raw(slot)
        else:
            self._worker_mp4(slot)

    def _worker_mp4(self, slot: RecordingSlot) -> None:
        """MP4録画ワーカースレッド"""
        serial = slot.serial
        grabber = slot.grabber
        sink = slot.recording_sink
        output_stream: BinaryIO = slot.ffmpeg_proc.stdin
        ffmpeg_proc = slot.ffmpeg_proc

        # acquisition開始
        try:
            grabber.acquisition_start()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Failed to start acquisition: {e}")
            return

        end_time = time.monotonic() + self._start_delay_s + self._duration_s
        slot.frame_count = 0

        # フレーム取得ループ
        while time.monotonic() < end_time:
            # ffmpeg異常終了チェック
            if ffmpeg_proc.poll() is not None:
                self._log(f"[{serial}] ffmpeg terminated unexpectedly")
                break

            buf = sink.try_pop_output_buffer()
            if buf is None:
                time.sleep(0.001)
                continue

            # CSV記録
            if slot.csv_writer is not None:
                try:
                    md = buf.meta_data
                    frame_no = f"{md.device_frame_number:05}"
                    timestamp = md.device_timestamp_ns
                    slot.csv_buffer.append([frame_no, timestamp])

                    if len(slot.csv_buffer) >= self.CSV_FLUSH_INTERVAL:
                        slot.csv_writer.writerows(slot.csv_buffer)
                        slot.csv_buffer.clear()
                        slot.csv_file.flush()
                except Exception as e:
                    self._log(f"[{serial}] Warning: CSV write error: {e}")

            try:
                arr = buf.numpy_wrap()
                output_stream.write(arr.tobytes())
                slot.frame_count += 1

                if slot.frame_count % self.FFMPEG_FLUSH_INTERVAL == 0:
                    output_stream.flush()
            except (BrokenPipeError, ValueError) as e:
                self._log(f"[{serial}] Write error: {e}")
                buf.release()
                break

            buf.release()

        # 停止処理
        try:
            output_stream.flush()
        except Exception:
            pass

        try:
            grabber.acquisition_stop()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Warning: acquisition_stop failed: {e}")

        try:
            grabber.stream_stop()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Warning: stream_stop failed: {e}")

        self._log(f"[{serial}] Recording finished: {slot.frame_count} frames")

    def _worker_raw(self, slot: RecordingSlot) -> None:
        """Raw録画ワーカースレッド"""
        serial = slot.serial
        grabber = slot.grabber
        sink = slot.recording_sink

        # acquisition開始
        try:
            grabber.acquisition_start()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Failed to start acquisition: {e}")
            return

        end_time = time.monotonic() + self._start_delay_s + self._duration_s
        slot.frame_count = 0
        slot.raw_files_created = []

        # フレーム取得ループ
        while time.monotonic() < end_time:
            buf = sink.try_pop_output_buffer()
            if buf is None:
                time.sleep(0.001)
                continue

            # CSV記録
            if slot.csv_writer is not None:
                try:
                    md = buf.meta_data
                    frame_no = f"{md.device_frame_number:05}"
                    timestamp = md.device_timestamp_ns
                    slot.csv_buffer.append([frame_no, timestamp])

                    if len(slot.csv_buffer) >= self.CSV_FLUSH_INTERVAL:
                        slot.csv_writer.writerows(slot.csv_buffer)
                        slot.csv_buffer.clear()
                        slot.csv_file.flush()
                except Exception as e:
                    self._log(f"[{serial}] Warning: CSV write error: {e}")

            arr = buf.numpy_wrap()
            payload = arr.tobytes()
            payload_size = len(payload)
            timestamp = buf.meta_data.device_timestamp_ns

            # ファイル分割チェック
            if slot.raw_file is None or (
                self._frames_per_file > 0
                and slot.frame_count > 0
                and slot.frame_count % self._frames_per_file == 0
            ):
                # 現在のファイルをクローズ
                if slot.raw_file is not None:
                    try:
                        slot.raw_file.flush()
                        slot.raw_file.close()
                    except Exception as e:
                        self._log(f"[{serial}] Warning: failed to close raw file: {e}")

                # 新しいファイルを開く
                slot.raw_file_start_frame = slot.frame_count
                raw_filename = f"cam{serial}_{slot.frame_count:06d}.raw"
                raw_path = self._output_dir / raw_filename
                try:
                    slot.raw_file = open(raw_path, "wb")
                    slot.raw_files_created.append(str(raw_path))
                    self._log(f"[{serial}] New raw file: {raw_filename}")

                    # FileHeader書き込み
                    _write_file_header(
                        slot.raw_file, serial, timestamp,
                        slot.width, slot.height, PIXEL_FORMAT_BAYER_GR8,
                    )
                except OSError as e:
                    self._log(f"[{serial}] Failed to open raw file {raw_filename}: {e}")
                    buf.release()
                    break

            # FrameHeader + Payload書き込み
            try:
                _write_frame_header(slot.raw_file, payload_size, slot.frame_count, timestamp)
                slot.raw_file.write(payload)
                slot.frame_count += 1

                if slot.frame_count % self.RAW_FLUSH_INTERVAL == 0:
                    slot.raw_file.flush()
            except OSError as e:
                self._log(f"[{serial}] Write error: {e}")
                buf.release()
                break

            buf.release()

        # 停止処理: Rawファイルクローズ
        if slot.raw_file is not None:
            try:
                slot.raw_file.flush()
                slot.raw_file.close()
            except Exception:
                pass
            slot.raw_file = None

        try:
            grabber.acquisition_stop()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Warning: acquisition_stop failed: {e}")

        try:
            grabber.stream_stop()
        except ic4.IC4Exception as e:
            self._log(f"[{serial}] Warning: stream_stop failed: {e}")

        self._log(
            f"[{serial}] Recording finished: {slot.frame_count} frames, "
            f"{len(slot.raw_files_created)} file(s)"
        )

    def _monitor_completion(self) -> None:
        """録画完了を監視するスレッド"""
        # 全スレッドの終了を待機
        for serial, thread in self._threads.items():
            thread.join()

        # クリーンアップ
        self._set_state(RecordingState.STOPPING, "Finalizing...")
        self._cleanup()
        self._set_state(RecordingState.IDLE, "Recording complete")

    def _cleanup(self) -> None:
        """リソースのクリーンアップ"""
        for slot in self._slots:
            # CSV終了処理（MP4/Raw共通）
            if slot.csv_file is not None:
                try:
                    if slot.csv_writer is not None and slot.csv_buffer:
                        slot.csv_writer.writerows(slot.csv_buffer)
                        slot.csv_buffer.clear()
                    slot.csv_file.flush()
                    slot.csv_file.close()
                except Exception as e:
                    self._log(f"[{slot.serial}] Warning: CSV close error: {e}")

            if self._output_format == OutputFormat.MP4:
                # ffmpeg終了
                if slot.ffmpeg_proc is not None:
                    try:
                        if slot.ffmpeg_proc.stdin and not slot.ffmpeg_proc.stdin.closed:
                            slot.ffmpeg_proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        slot.ffmpeg_proc.wait(timeout=10)
                    except Exception:
                        pass
            else:
                # Raw: 安全策 — raw_fileが閉じられていなければ閉じる
                if slot.raw_file is not None:
                    try:
                        slot.raw_file.flush()
                        slot.raw_file.close()
                    except Exception:
                        pass
                    slot.raw_file = None

            # 保険的な停止処理（MP4/Raw共通）
            try:
                if slot.grabber.is_streaming:
                    slot.grabber.acquisition_stop()
                    slot.grabber.stream_stop()
            except ic4.IC4Exception:
                pass

        # レポート出力（MP4/Raw共通）
        if self._slots:
            self._log("=== Recording Report ===")
            for slot in self._slots:
                expected = int(self._duration_s * slot.trigger_interval_fps)
                delta = slot.frame_count - expected
                self._log(f"  [{slot.serial}] frames={slot.frame_count}, expected={expected}, delta={delta:+d}")

        self._slots = []
        self._threads = {}

    # -------------------------------------------------------------------------
    # ユーティリティ
    # -------------------------------------------------------------------------

    def _set_state(self, state: RecordingState, message: str) -> None:
        """状態を設定してコールバックを呼び出す"""
        self._state = state
        self._log(f"State: {state.value} - {message}")
        if self._on_state_changed:
            self._on_state_changed(state, message)

    def _set_error(self, message: str) -> None:
        """エラー状態を設定"""
        self._error_message = message
        self._set_state(RecordingState.ERROR, message)

    def _log(self, message: str) -> None:
        """ログ出力"""
        print(f"[RecordingController] {message}")
