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
    "WIDTH": 1920,                # 画像幅（px）
    "HEIGHT": 1080,               # 画像高さ（px）
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
ACTION_INTERVAL_SEC  = 60         # ここは“ミリ秒”として使う（後で µs に変換）
USE_ACTION_SCHEDULER = True       # True: 同期撮影を使う ソフトウェアトリガー・ハードウェアトリガーの場合はFalseにしてください

# 4台ぶんの書き出し完了待ち用フラグ
EndFlag = 0

# QueueSinkに渡す受け付け可能なピクセルフォーマットの候補
PIXELFORMAT_CANDIDATES = [ic4.PixelFormat.BayerGR8]


# ===== QueueSink Listener =====
# 各カメラに1つ割り当て。バッファ確保と、停止時の一括書き出し（CSV/BMP）を担う。
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
        self.max_frames      = 1000       # 出力キューに保持したい上限（これ以上は貯めない）
        self.stop_dropping   = False      # True になったら以後は貯めない（PAUSEにする）

        # --- CSV（camごと）を準備。停止時に frame_no/timestamp をまとめて書く。
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
        return True  # False を返すと stream_setup が失敗

    def sink_disconnected(self, sink):
        """
        停止時：出力キューに残っているフレームを取り出して CSV/BMP へ一括保存。
        """
        global EndFlag
        print(f"{self.cam_name} 書き出し中  → CSV: {self.csv_path}")

        while True:
            buf = sink.try_pop_output_buffer()
            if buf is None:
                break
            try:
                md = buf.meta_data
                frame_no  = f"{md.device_frame_number:04}"
                timestamp = md.device_timestamp_ns
                self.csv_w.writerow([frame_no, timestamp])

                # 画像は可逆のBMPで保存（検証向き）。容量が気になればPNG/JPEGへ変更可能。
                bmp_name = f"{self.cam_name}_{frame_no}_{timestamp}.bmp"
                buf.save_as_bmp(os.path.join(OUT_DIR, bmp_name))
            finally:
                buf.release()  # ★必ず返却

        self.csv_f.close()  # バッファを確実に吐き出して閉じる
        EndFlag += 1         # このカメラは完了
        return

    def frames_queued(self, sink):
        """
        取得中は重い処理を避ける
        「貯め込み上限」に達したらQueueSinkをPAUSE にして、それ以上バッファを貯めない。
        """
        if self.stop_dropping:
            return

        sizes = sink.queue_sizes()
        # 出力キューの長さが上限を超えたら以後は貯めない（PAUSE）
        if sizes.output_queue_length >= self.max_frames:
            self.stop_dropping = True
            sink.mode = ic4.Sink.Mode.PAUSE  # 以降、受信フレームは無視＝出力キューは増えない
        return


# ===== 基本プロパティ設定 =====
def apply_basic_properties(grabber: ic4.Grabber):
    
    #解像度・FPS・露光・ゲイン・カラーフォーマットなどの基本設定
    mp = grabber.device_property_map
    mp.set_value(ic4.PropId.WIDTH,  int(DEFAULT_SETTINGS["WIDTH"]))
    mp.set_value(ic4.PropId.HEIGHT, int(DEFAULT_SETTINGS["HEIGHT"]))
    mp.set_value(ic4.PropId.ACQUISITION_FRAME_RATE, float(DEFAULT_SETTINGS["FPS"]))
    mp.set_value(ic4.PropId.PIXEL_FORMAT, DEFAULT_SETTINGS["PIXEL_FORMAT"])

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
def schedule_action(grabber: ic4.Grabber, start_ns: int, interval_us: int):
    """
    “未来の開始時刻（単位：ns）”と“発火間隔（単位：µs）”をセットし、COMMITでアクションスケジューラを開始。
    """
    mp = grabber.device_property_map
    try:
        mp.set_value(ic4.PropId.TRIGGER_SOURCE, "Action0")  # アクションコマンド専用トリガー
    except:
        pass

    # 古いスケジュールをクリアしてから新規設定
    mp.try_set_value(ic4.PropId.ACTION_SCHEDULER_CANCEL, True)
    mp.set_value(ic4.PropId.ACTION_SCHEDULER_TIME,     int(start_ns))    # ns
    mp.set_value(ic4.PropId.ACTION_SCHEDULER_INTERVAL, int(interval_us)) # µs
    mp.try_set_value(ic4.PropId.ACTION_SCHEDULER_COMMIT, True)


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
    # ソフトウェアトリガー・ハードウェアトリガーの場合は使用しない
    if USE_ACTION_SCHEDULER:
        ref_ns = get_device_time_ns(grabbers[0]) or time.time_ns()  # 取得不可ならホスト時刻で代用
        start_ns    = ref_ns + int(START_DELAY_SEC * 1e9)       # ns
        interval_us =           int(ACTION_INTERVAL_SEC * 1e3)  # ms → µs 変換
        for g in grabbers:
            schedule_action(g, start_ns, interval_us)
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
