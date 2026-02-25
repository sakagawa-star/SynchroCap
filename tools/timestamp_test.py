#!/usr/bin/env python3
"""
timestamp_test.py — device_timestamp_ns の意味を切り分ける実験スクリプト

DFK33GR0234 (GigE Vision) カメラの ImageBuffer.MetaData.device_timestamp_ns が
露光開始・露光終了・読み出し完了のどれを指すかを、ソフトウェアトリガーと
TIMESTAMP_LATCH を使って切り分ける。

測定方式:
  T0: TIMESTAMP_LATCH (TriggerSoftware 直前に取得) — トリガー発行時刻の近似値
  C:  device_timestamp_ns                          — ImageBuffer メタデータ
  E:  ExposureTime (設定値)                        — 露光時間

  C - T0 ≈ 0   → device_timestamp_ns は露光開始を表す
  C - T0 ≈ E   → device_timestamp_ns は露光終了を表す
  C - T0 > E   → device_timestamp_ns は読み出し完了を表す

使い方:
  python timestamp_test.py
  python timestamp_test.py --frames 5
  python timestamp_test.py --exposure 50000 --frames 3
  python timestamp_test.py --timeout 30
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
from dataclasses import dataclass, field

try:
    import imagingcontrol4 as ic4
except ImportError as exc:
    print(f"ERROR: imagingcontrol4 をインポートできません: {exc}")
    print("micromamba 環境 synchrocap を activate してください。")
    sys.exit(1)


# ---------------------------------------------------------------------------
# データ構造
# ---------------------------------------------------------------------------
@dataclass
class CollectedData:
    """全フレームの収集結果。"""

    trigger_latch_ns: list[int] = field(default_factory=list)
    frame_timestamps_ns: list[int] = field(default_factory=list)
    frame_numbers: list[int] = field(default_factory=list)
    exposure_time_ns: int = 0


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------
def _try_set(prop_map: ic4.PropertyMap, name: str, value) -> bool:
    """PropertyMap に値をセット。失敗時は False を返す。"""
    try:
        prop_map.set_value(name, value)
        return True
    except ic4.IC4Exception as exc:
        print(f"  WARNING: {name} = {value} の設定に失敗: {exc}")
        return False


def _get_latch_timestamp_ns(prop_map: ic4.PropertyMap) -> int | None:
    """TIMESTAMP_LATCH を実行して TIMESTAMP_LATCH_VALUE (ns) を取得する。

    本番コード (chktimestat.py:203-236) と同じパターン。
    """
    try:
        try:
            prop_map.try_set_value(ic4.PropId.TIMESTAMP_LATCH, True)
        except AttributeError:
            prop_map.set_value(ic4.PropId.TIMESTAMP_LATCH, True)
    except ic4.IC4Exception:
        return None

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
        return None
    try:
        return int(float(raw_value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# QueueSink リスナー
# ---------------------------------------------------------------------------
class _FrameListener(ic4.QueueSinkListener):
    def sink_connected(
        self, sink: ic4.QueueSink, image_type: ic4.ImageType, min_buffers_required: int
    ) -> bool:
        return True

    def sink_disconnected(self, sink: ic4.QueueSink) -> None:
        pass

    def frames_queued(self, sink: ic4.QueueSink) -> None:
        pass


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> None:
    num_frames: int = args.frames
    timeout_sec: float = args.timeout
    exposure_us: float = args.exposure
    exposure_ns: int = int(exposure_us * 1000)

    print("=" * 60)
    print("device_timestamp_ns 切り分け実験")
    print("=" * 60)
    print(f"  モード        : ソフトウェアトリガー")
    print(f"  露光時間      : {exposure_us:.0f} μs ({exposure_us / 1000:.1f} ms)")
    print(f"  取得フレーム数: {num_frames}")
    print(f"  タイムアウト  : {timeout_sec} 秒")
    print()

    with ic4.Library.init_context():
        # --- デバイス列挙 ---
        devices = list(ic4.DeviceEnum.devices())
        if not devices:
            print("ERROR: カメラが見つかりません。接続を確認してください。")
            del devices
            gc.collect()
            return

        dev = devices[0]
        model = getattr(dev, "model_name", "Unknown")
        serial = getattr(dev, "serial", "Unknown")
        print(f"カメラ: {model}  (S/N: {serial})")
        print()

        grabber = ic4.Grabber()
        grabber.device_open(dev)
        prop_map = grabber.device_property_map

        # --- カメラ設定 ---
        print("[1] カメラ設定")
        _try_set(prop_map, ic4.PropId.TRIGGER_SELECTOR, "FrameStart")
        _try_set(prop_map, ic4.PropId.TRIGGER_MODE, "On")
        _try_set(prop_map, ic4.PropId.TRIGGER_SOURCE, "Software")
        _try_set(prop_map, ic4.PropId.EXPOSURE_AUTO, "Off")
        _try_set(prop_map, ic4.PropId.EXPOSURE_TIME, exposure_us)

        # TIMESTAMP_LATCH が動作するか確認
        latch_test = _get_latch_timestamp_ns(prop_map)
        if latch_test is None:
            print()
            print("ERROR: TIMESTAMP_LATCH が動作しません。")
            print("       このカメラでは LATCH ベースの測定ができません。")
            grabber.device_close()
            del prop_map, grabber, dev, devices
            gc.collect()
            return
        print(f"  TIMESTAMP_LATCH 動作確認: {latch_test} ns")
        print()

        # --- ストリーム開始 ---
        print("[2] ストリーム開始")
        listener = _FrameListener()
        sink = ic4.QueueSink(listener)
        grabber.stream_setup(sink)
        sink.alloc_and_queue_buffers(10)
        print("  ストリーム開始しました。")
        print()

        # --- フレーム取得ループ ---
        collected = CollectedData(exposure_time_ns=exposure_ns)

        print(f"[3] ソフトウェアトリガーで {num_frames} フレーム取得中...")

        for i in range(num_frames):
            # 前回のフレームと区別するため少し待つ
            time.sleep(0.05)

            # T0: トリガー直前の LATCH タイムスタンプ
            t0 = _get_latch_timestamp_ns(prop_map)
            if t0 is None:
                print(f"  WARNING: Frame #{i + 1} の LATCH 取得に失敗")

            # ソフトウェアトリガー発行
            try:
                prop_map.execute_command(ic4.PropId.TRIGGER_SOFTWARE)
                print(f"  → トリガー #{i + 1} 発行 (T0 = {t0})")
            except ic4.IC4Exception as exc:
                print(f"  ERROR: TriggerSoftware 実行失敗: {exc}")
                break

            # フレーム待ち
            deadline = time.monotonic() + timeout_sec
            buf = None
            while time.monotonic() < deadline:
                buf = sink.try_pop_output_buffer()
                if buf is not None:
                    break
                time.sleep(0.001)

            if buf is None:
                print(f"  ERROR: フレーム #{i + 1} のタイムアウト ({timeout_sec}秒)")
                break

            md = buf.meta_data
            ts_ns = md.device_timestamp_ns
            frame_no = md.device_frame_number
            collected.trigger_latch_ns.append(t0 if t0 is not None else 0)
            collected.frame_timestamps_ns.append(ts_ns)
            collected.frame_numbers.append(frame_no)
            print(f"  Frame #{i + 1}: C = {ts_ns}, frame_number = {frame_no}")
            buf.release()

        # --- ストリーム停止 ---
        print()
        print("[4] ストリーム停止")
        grabber.stream_stop()
        grabber.device_close()

        # --- 結果出力 ---
        _print_results(collected)

        # --- IC4 オブジェクトのクリーンアップ ---
        del sink
        del listener
        del prop_map
        del grabber
        del dev
        del devices
        gc.collect()


# ---------------------------------------------------------------------------
# 結果出力
# ---------------------------------------------------------------------------
def _print_results(data: CollectedData) -> None:
    exposure_ns = data.exposure_time_ns
    exposure_ms = exposure_ns / 1_000_000

    print()
    print("=" * 70)
    print("=== Timestamp Comparison ===")
    print("=" * 70)
    print()
    print(f"  ExposureTime (E)           : {exposure_ns:,} ns ({exposure_ms:.1f} ms)")
    print(f"  device_timestamp_ns 単位   : ns (ナノ秒)")
    print(f"  TIMESTAMP_LATCH 単位       : ns (ナノ秒)")
    print()

    for i in range(len(data.frame_timestamps_ns)):
        t0 = data.trigger_latch_ns[i]
        c_ns = data.frame_timestamps_ns[i]
        frame_no = data.frame_numbers[i]

        diff = c_ns - t0
        diff_ms = diff / 1_000_000
        diff_minus_e = diff - exposure_ns
        diff_minus_e_ms = diff_minus_e / 1_000_000

        print(f"--- Frame #{i + 1} (frame_number={frame_no}) ---")
        print()
        print(f"  T0 (トリガー直前 LATCH):      {t0:,} ns")
        print(f"  C  (device_timestamp_ns):      {c_ns:,} ns")
        print(f"  E  (ExposureTime):             {exposure_ns:,} ns ({exposure_ms:.1f} ms)")
        print()
        print(f"  C - T0          = {diff:+,} ns  ({diff_ms:+.3f} ms)")
        print(f"  C - T0 - E      = {diff_minus_e:+,} ns ({diff_minus_e_ms:+.3f} ms)")
        print()

        # 判定
        abs_diff = abs(diff)
        abs_diff_minus_e = abs(diff_minus_e)

        if abs_diff < 1_000_000:  # C - T0 < 1ms
            print("  → device_timestamp_ns は露光開始 (≈トリガー時刻) を表す")
        elif abs_diff_minus_e < 1_000_000:  # C - T0 ≈ E (差が1ms以内)
            print("  → device_timestamp_ns は露光終了を表す")
        elif diff > exposure_ns:
            print("  → device_timestamp_ns は読み出し完了 (露光終了後) を表す可能性")
            print(f"     (露光終了からの遅延: {diff_minus_e_ms:+.3f} ms)")
        else:
            print(f"  → 判定困難 (C - T0 = {diff_ms:+.3f} ms, E = {exposure_ms:.1f} ms)")

        print()

    # 複数フレームのサマリ
    if len(data.frame_timestamps_ns) > 1:
        diffs = [
            data.frame_timestamps_ns[i] - data.trigger_latch_ns[i]
            for i in range(len(data.frame_timestamps_ns))
        ]
        avg_diff = sum(diffs) / len(diffs)
        avg_diff_ms = avg_diff / 1_000_000
        min_diff_ms = min(diffs) / 1_000_000
        max_diff_ms = max(diffs) / 1_000_000

        print("--- サマリ ---")
        print(f"  C - T0 平均: {avg_diff_ms:+.3f} ms")
        print(f"  C - T0 最小: {min_diff_ms:+.3f} ms")
        print(f"  C - T0 最大: {max_diff_ms:+.3f} ms")
        print(f"  ExposureTime: {exposure_ms:.1f} ms")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="device_timestamp_ns の意味を切り分ける実験スクリプト",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=3,
        help="取得するフレーム数 (デフォルト: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="フレーム待ちタイムアウト秒数 (デフォルト: 15)",
    )
    parser.add_argument(
        "--exposure",
        type=float,
        default=100_000.0,
        help="露光時間 μs (デフォルト: 100000 = 100ms)",
    )
    args = parser.parse_args()

    try:
        run(args)
    except ic4.IC4Exception as exc:
        print(f"\nIC4 エラー: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n中断されました。")
        sys.exit(130)


if __name__ == "__main__":
    main()
