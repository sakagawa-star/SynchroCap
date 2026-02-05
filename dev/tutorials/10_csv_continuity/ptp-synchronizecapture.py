import os
import cv2
import time
import imagingcontrol4 as ic4
import csv

# ===== ユーザー設定 =====
# すべての出力（BMP/CSV）のルートディレクトリ
OUT_DIR = "captures"
os.makedirs(OUT_DIR, exist_ok=True)

# カメラの初期設定（機種やドライバによって受け付ける型・単位が異なる点に注意）
DEFAULT_SETTINGS = {
    "WIDTH": 320,                 # 画像幅（px）
    "HEIGHT": 320,                # 画像高さ（px）
    "FPS": 30,                    # フレームレート
    "PIXEL_FORMAT": "BayerGR8",   # カラーフォーマット
    "TRIGGER_MODE": "On",         # トリガーモード
    "GAIN_AUTO": "Continuous",    # ゲインオート　ON
    "EXPOSURE_TIME": 16335,       # 露光時間（単位はµs）
    "EXPOSURE_AUTO": "Off",       # 露光時間の自動OFF
    "PTP_ENABLE": True,           # PTPでカメラ時刻同期ON
}

# Action Scheduler：開始時刻と間隔
START_DELAY_SEC      = 5.0        # 未来開始の遅延（秒）
ACTION_INTERVAL_SEC  = 1000.0 / 30.0  # ここは“ミリ秒”として使う（後で µs に変換）
USE_ACTION_SCHEDULER = True       # True: 同期撮影を使う ソフトウェアトリガー・ハードウェアトリガーの場合はFalseにしてください

# 4台ぶんの書き出し完了待ち用フラグ
EndFlag = 0

# QueueSinkに渡す受け付け可能なピクセルフォーマットの候補
PIXELFORMAT_CANDIDATES = [ic4.PixelFormat.BayerGR8]


# ===== QueueSink Listener =====
# 各カメラに1つ割り当て。バッファ確保と、取得中の逐次保存（CSV/BMP）を担う。
class CamListener(ic4.QueueSinkListener):
    def __init__(self, cam_index, cam_name, save_dir):
        """
        cam_index: 1,2,... のカメラID
        cam_name : "cam1" 等の表示・保存用名
        save_dir : 出力ルート
        """
        super().__init__()
        self.cam_index       = cam_index
        self.cam_name        = cam_name
        self.save_dir        = save_dir
        self.max_frames      = 300        # 出力キューに保持したい上限（これ以上は貯めない）
        self.target_frames   = 300        # 1カメラあたりの保存目標枚数
        self.stop_dropping   = False      # True になったら以後は貯めない（PAUSEにする）
        self.saved_frames    = 0          # 既に保存したフレーム数
        self.csv_buffer      = []         # CSVの10件バッファ
        self.csv_flush_count = 0          # flush回数（ログ用）

        # --- CSV（camごと）を準備。取得中に frame_no/timestamp を逐次書く。
        os.makedirs(self.save_dir, exist_ok=True)
        csv_dir = os.path.join(self.save_dir, "csv")
        os.makedirs(csv_dir, exist_ok=True)
        self.csv_path = os.path.join(csv_dir, f"{self.cam_name}.csv")
        new_file = (not os.path.exists(self.csv_path)) or os.path.getsize(self.csv_path) == 0
        self.csv_f = open(self.csv_path, "a", newline="", encoding="utf-8")
        self.csv_w = csv.writer(self.csv_f)
        if new_file:
            self.csv_w.writerow(["frame_number", "device_timestamp_ns"])  # ヘッダ

    def sink_connected(self, sink, image_type, min_buffers_required):
        """
        接続時：入力キューへ“使い回しバッファ”を大量投入。
        - 320x320xBGR8 ≒ 0.3MB/枚 → 1000枚 ≒ 0.3GB/台（機種・フォーマットで変動）
        - 4台同時なら 1.2GB 程度（解像度・枚数を環境に合わせて調整）
        """
        sink.alloc_and_queue_buffers(1000)
        return True

    def sink_disconnected(self, sink):
        """
        停止時：CSVバッファの残りflush/close を行う。出力キューに残りがあれば保険で処理。
        """
        global EndFlag
        print(f"{self.cam_name} sink_disconnected  → CSV: {self.csv_path}")

        while True:
            buf = sink.try_pop_output_buffer()
            if buf is None:
                break
            try:
                if self.saved_frames < self.target_frames:
                    md = buf.meta_data
                    frame_no  = f"{md.device_frame_number:04}"
                    timestamp = md.device_timestamp_ns
                    self._save_frame(buf, frame_no, timestamp)
            finally:
                buf.release()  # ★必ず返却

        self._flush_csv_buffer(force=True)
        self.csv_f.close()  # バッファを確実に吐き出して閉じる
        EndFlag += 1         # このカメラは完了
        return

    def frames_queued(self, sink):
        """
        取得中は重い処理を避ける
        取得中に逐次popして保存し、300枚到達でPAUSEにする。
        """
        if self.stop_dropping:
            return

        while True:
            buf = sink.try_pop_output_buffer()
            if buf is None:
                break
            try:
                if self.saved_frames >= self.target_frames:
                    self.stop_dropping = True
                    sink.mode = ic4.Sink.Mode.PAUSE  # 以降、受信フレームは無視＝出力キューは増えない
                    break

                md = buf.meta_data
                frame_no  = f"{md.device_frame_number:04}"
                timestamp = md.device_timestamp_ns
                self._save_frame(buf, frame_no, timestamp)

                if self.saved_frames >= self.target_frames:
                    self.stop_dropping = True
                    sink.mode = ic4.Sink.Mode.PAUSE
                    print(f"{self.cam_name} reached {self.target_frames} frames")
                    break
            finally:
                buf.release()  # ★必ず返却
        return

    def _save_frame(self, buf, frame_no, timestamp):
        # 画像は可逆のBMPで保存（検証向き）。容量が気になればPNG/JPEGへ変更可能。
        bmp_name = f"{self.cam_name}_{frame_no}_{timestamp}.bmp"
        buf.save_as_bmp(os.path.join(OUT_DIR, bmp_name))

        self.csv_buffer.append([frame_no, timestamp])
        self.saved_frames += 1

        if len(self.csv_buffer) >= 10:
            self._flush_csv_buffer(force=False)

    def _flush_csv_buffer(self, force=False):
        if not self.csv_buffer:
            return
        if not force and len(self.csv_buffer) < 10:
            return
        self.csv_w.writerows(self.csv_buffer)
        self.csv_buffer.clear()
        self.csv_f.flush()
        self.csv_flush_count += 1
        print(f"{self.cam_name} CSV flush #{self.csv_flush_count}")


# ===== 基本プロパティ設定 =====
def apply_basic_properties(grabber: ic4.Grabber):
    
    #解像度・FPS・露光・ゲイン・カラーフォーマットなどの基本設定
    mp = grabber.device_property_map
    mp.set_value(ic4.PropId.WIDTH,  int(DEFAULT_SETTINGS["WIDTH"]))
    mp.set_value(ic4.PropId.HEIGHT, int(DEFAULT_SETTINGS["HEIGHT"]))
    mp.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(DEFAULT_SETTINGS["FPS"]))
    try:
        mp.set_value(ic4.PropId.PIXEL_FORMAT, DEFAULT_SETTINGS["PIXEL_FORMAT"])
    except Exception as exc:
        print(f"PIXEL_FORMAT set error={exc}, retry with ic4.PixelFormat.BayerGR8")
        mp.set_value(ic4.PropId.PIXEL_FORMAT, ic4.PixelFormat.BayerGR8)

    # TRIGGER_MODE/GAIN/EXPOSURE の設定
    mp.set_value(ic4.PropId.TRIGGER_MODE, DEFAULT_SETTINGS["TRIGGER_MODE"])
    mp.set_value(ic4.PropId.GAIN_AUTO, DEFAULT_SETTINGS["GAIN_AUTO"])
    mp.set_value(ic4.PropId.EXPOSURE_AUTO, DEFAULT_SETTINGS["EXPOSURE_AUTO"])
    mp.set_value(ic4.PropId.EXPOSURE_TIME, DEFAULT_SETTINGS["EXPOSURE_TIME"])

    # PTP 同期ON
    mp.set_value(ic4.PropId.PTP_ENABLE, DEFAULT_SETTINGS["PTP_ENABLE"])

    # 念のため、以前の Action スケジュールをキャンセル
    mp.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)

    # ハードウェアトリガーの場合はLine1にする
    # ソフトウェアトリガーの場合はSoftwareにする
    # ハードウェアトリガー・ソフトウェアどちらも使う場合にはAnyにする
    #mp.set_value(ic4.PropId.TRIGGER_SOURCE, "Any")  # 環境により変更

# ===== デバイス時刻（ns）取得 =====
def get_device_time_ns(grabber: ic4.Grabber) -> int:
    """
    代表カメラの“現在デバイス時刻(ns)”を取得。
    """
    mp = grabber.device_property_map
    try:
        mp.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)  # タイムスタンプの現在値を取得
        return mp.get_value_float(ic4.PropId.TIMESTAMP_LATCH_VALUE) #タイムスタンプを取得
    except:
        return 0


# ===== アクションスケジューラ設定 =====
def schedule_action(grabber: ic4.Grabber, start_ns: int, interval_us: int, cam_label: str = "cam"):
    """
    “未来の開始時刻（単位：ns）”と“発火間隔（単位：µs）”をセットし、COMMITでアクションスケジューラを開始。
    """
    mp = grabber.device_property_map

    prefix = f"[{cam_label}]"

    def _read_enum(prop_id, name, set_value=None):
        if set_value is not None:
            try:
                mp.set_value(prop_id, set_value)
                print(f"{prefix} {name} set={set_value}")
            except Exception as exc:
                print(f"{prefix} {name} set={set_value} error={exc}")
        try:
            prop = mp.find(prop_id)
        except Exception as exc:
            print(f"{prefix} {name} find error={exc}")
            return

        value_map = {}
        entries = getattr(prop, "entries", None)
        if entries is None:
            print(f"{prefix} {name} entries unavailable")
        else:
            try:
                labels = []
                for entry in entries:
                    entry_id = getattr(entry, "string_identifier", None)
                    if entry_id is None:
                        entry_id = getattr(entry, "name", None)
                    entry_value = getattr(entry, "value", None)
                    if entry_value is not None and entry_id is not None:
                        value_map[entry_value] = entry_id
                    if entry_id is None and entry_value is not None:
                        entry_id = str(entry_value)
                    if entry_value is None:
                        labels.append(f"{entry_id}")
                    else:
                        labels.append(f"{entry_id}:{entry_value}")
                print(f"{prefix} {name} entries={labels}")
            except Exception as exc:
                print(f"{prefix} {name} entries error={exc}")

        try:
            current = prop.value
        except Exception as exc:
            print(f"{prefix} {name} readback error={exc}")
            return
        if isinstance(current, str):
            print(f"{prefix} {name} readback={current}")
            return
        label = value_map.get(current)
        if label is not None:
            print(f"{prefix} {name} readback={label} (raw={current})")
        else:
            print(f"{prefix} {name} readback={current}")

    _read_enum(ic4.PropId.TRIGGER_SOURCE, "TRIGGER_SOURCE", set_value="Action0")  # 環境により変更

    # 古いスケジュールをクリアしてから新規設定
    mp.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
    try:
        mp.set_value(ic4.PropId.ACTION_SCHEDULER_TIME, int(start_ns))    # ns
        try:
            readback = mp.get_value_int(ic4.PropId.ACTION_SCHEDULER_TIME)
            print(f"{prefix} ACTION_SCHEDULER_TIME set={int(start_ns)} readback={readback}")
        except Exception as exc:
            print(f"{prefix} ACTION_SCHEDULER_TIME set={int(start_ns)} readback error={exc}")
    except Exception as exc:
        print(f"{prefix} ACTION_SCHEDULER_TIME set={int(start_ns)} error={exc}")

    try:
        mp.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, int(interval_us)) # µs
        try:
            readback = mp.get_value_int(ic4.PropId.ACTION_SCHEDULER_INTERVAL)
            print(f"{prefix} ACTION_SCHEDULER_INTERVAL set={int(interval_us)} readback={readback}")
        except Exception as exc:
            print(f"{prefix} ACTION_SCHEDULER_INTERVAL set={int(interval_us)} readback error={exc}")
    except Exception as exc:
        print(f"{prefix} ACTION_SCHEDULER_INTERVAL set={int(interval_us)} error={exc}")

    try:
        result = mp.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)
        print(f"{prefix} ACTION_SCHEDULER_COMMIT set=True result={result}")
    except Exception as exc:
        print(f"{prefix} ACTION_SCHEDULER_COMMIT set=True error={exc}")

    _read_enum(ic4.PropId.TRIGGER_MODE, "TRIGGER_MODE")
    try:
        trigger_selector = ic4.PropId.TRIGGER_SELECTOR
    except AttributeError as exc:
        print(f"{prefix} TRIGGER_SELECTOR get error={exc}")
    else:
        _read_enum(trigger_selector, "TRIGGER_SELECTOR")


# ===== メイン =====
def main():
    global EndFlag

    # デバイス列挙：4台見つからなければ中断
    devs = ic4.DeviceEnum.devices()
    if len(devs) < 4:
        raise RuntimeError(f"カメラが {len(devs)} 台しか見つかりません。4台必要です。")

    # 各デバイスをオープン
    grabbers = []
    for i in range(4):
        g = ic4.Grabber()
        g.device_open(devs[i])
        grabbers.append(g)
        print(f"[open] cam{i+1}: {devs[i].model_name}")

    # 基本設定を適用
    for g in grabbers:
        apply_basic_properties(g)

    # PTP 同期安定待ち（構成によっては 5〜10秒程度に延ばす）
    print("PTP同期中…数秒待機"); time.sleep(3)

    # QueueSink/Listener 準備 → 取得開始（ACQUISITION_START）
    sinks, listeners = [], []
    for i, g in enumerate(grabbers):
        name = f"cam{i+1}"
        listener = CamListener(i, name, OUT_DIR)
        # max_output_buffers=1000 を指定：出力キューは1000枚で頭打ち（古いものから捨てる）
        sink = ic4.QueueSink(listener, PIXELFORMAT_CANDIDATES, 1000)
        g.stream_setup(sink, setup_option=ic4.StreamSetupOption.ACQUISITION_START)
        listeners.append(listener)
        sinks.append(sink)

    # Action Scheduler 起動（必ず“未来の時刻”を指定）
    # ハードウェアトリガーの場合は使用しない
    if USE_ACTION_SCHEDULER:
        ref_ns = get_device_time_ns(grabbers[0]) or time.time_ns()  # 取得不可ならホスト時刻で代用
        start_ns    = ref_ns + int(START_DELAY_SEC * 1e9)       # ns
        interval_us =           round(ACTION_INTERVAL_SEC * 1e3)  # ms → µs 変換
        for i, g in enumerate(grabbers):
            label = f"cam{i+1}:{devs[i].model_name}"
            schedule_action(g, start_ns, interval_us, label)
        print(f"[ActionScheduler] start_ns={start_ns/1e9:.3f} sec, interval_us={interval_us} µs")

    # 目標枚数に到達したカメラから順次停止（切断時に一括保存が走る）
    EndFlag = 0
    stopped = set()
    while True:
        for l in listeners:
            # PAUSEに入った＝これ以上は貯めない → このカメラは停止して書き出しへ
            if l.stop_dropping and l.cam_index not in stopped:
                g = grabbers[l.cam_index]
                try:
                    g.stream_stop()  # ここで sink_disconnected が呼ばれ CSV/BMP 書き出し
                except:
                    pass
                stopped.add(l.cam_index)

        # 全カメラ停止＆書き出し完了なら終了
        if len(stopped) == len(listeners) and EndFlag >= 4:
            print("全カメラ既定枚数に達しました。終了します。")
            break

        cv2.waitKey(1)  


if __name__ == "__main__":
    # IC4ライブラリをwithブロックの間だけ有効にする（初期化と後始末を自動化）
    with ic4.Library.init_context(api_log_level=ic4.LogLevel.INFO,
                                  log_targets=ic4.LogTarget.STDERR):
        try:
            main()
        except ic4.IC4Exception as ex:
            print(f"IC4 エラー: {ex.message}")
        except Exception as e:
            print("エラー:", e)
