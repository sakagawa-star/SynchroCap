# ptp_sync_check_multi.py
# 接続されている 2〜8 台のカメラで PTP を有効化し、収束（Master 1台 + 残り Slave）を確認して一覧表示

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import imagingcontrol4 as ic4

PTP_ENABLE_NAMES = ["PtpEnable", "GevIEEE1588Enable"]
PTP_STATUS_NAMES = ["PtpStatus", "GevIEEE1588Status"]

MAX_WAIT_SEC = 30.0   # 収束待ち最大時間
POLL_SEC = 0.5        # ポーリング間隔


@dataclass
class UbuntuPtpStatus:
    success: bool
    role: Optional[str] = None
    steps_removed: Optional[str] = None
    offset_from_master: Optional[str] = None
    mean_path_delay: Optional[str] = None
    port_identity: Optional[str] = None
    grandmaster_clock_id: Optional[str] = None
    error: Optional[str] = None


def find_prop(pm: ic4.PropertyMap, names):
    """候補名を順に探して最初に見つかった Property を返す。なければ None。"""
    for name in names:
        try:
            return pm.find(name)
        except ic4.IC4Exception:
            continue
    return None


def ensure_ptp_enabled(pm: ic4.PropertyMap) -> bool:
    """PTP を有効化（可能なら）。成功/既に有効なら True、ノードが無ければ False。"""
    prop = find_prop(pm, PTP_ENABLE_NAMES)
    if prop is None:
        return False
    try:
        if prop.value is False:
            prop.value = True
        return True
    except ic4.IC4Exception:
        return False


def get_ptp_status(pm: ic4.PropertyMap) -> str | None:
    """PTP ステータスの文字列（例: 'Master', 'Slave'）を返す。取得できなければ None。"""
    prop = find_prop(pm, PTP_STATUS_NAMES)
    if prop is None:
        return None
    try:
        return f"{prop.value}"
    except ic4.IC4Exception:
        return None


def has_converged(statuses: list[str | None]) -> bool:
    """収束条件: ステータスが全て 'Master' か 'Slave' で、Master がちょうど 1、Slave が 1 以上。"""
    s = [st for st in statuses if st is not None]
    if len(s) < 2:
        return False
    if any(st not in {"Master", "Slave"} for st in s):
        return False
    return (s.count("Master") == 1) and (s.count("Slave") >= 1)


def run_pmc_command(arguments: list[str]) -> tuple[bool, str]:
    """UDS経由で pmc コマンドを呼び出し、成功フラグと標準出力（またはエラー文）を返す。"""
    client_socket = f"/tmp/pmc.{os.getuid()}.{os.getpid()}"
    cmd = [
        "/usr/sbin/pmc",
        "-u",
        "-i",
        client_socket,
        "-s",
        "/var/run/ptp4l",
        "-b",
        "0",
        "-d",
        "0",
        " ".join(arguments),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        return True, completed.stdout
    except FileNotFoundError:
        return False, "pmc コマンドが見つかりません"
    except subprocess.TimeoutExpired:
        return False, "pmc コマンドがタイムアウトしました"
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or exc.stdout or str(exc)
        return False, stderr.strip()
    finally:
        cleaned = "removed"
        try:
            os.unlink(client_socket)
        except FileNotFoundError:
            cleaned = "not-found"
        except OSError as exc:
            cleaned = f"error:{exc}"


def fetch_ubuntu_ptp_status() -> UbuntuPtpStatus:
    """Ubuntu側 (linuxptp) の PTP 状態を pmc 経由で取得。"""
    success, current_output = run_pmc_command(["GET", "CURRENT_DATA_SET"])
    if not success:
        return UbuntuPtpStatus(success=False, error=current_output)

    info: dict[str, str] = {}
    for line in current_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.replace("=", " ").split()
        if len(parts) < 2:
            continue
        key = parts[0]
        value = parts[-1]
        if key in {"stepsRemoved", "offsetFromMaster", "meanPathDelay", "portIdentity"}:
            info[key] = value

    gm_success, gm_output = run_pmc_command(["GET", "GRANDMASTER_SETTINGS_NP"])
    gm_clock_id: Optional[str] = None
    if gm_success:
        for line in gm_output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.replace("=", " ").split()
            if len(parts) < 2:
                continue
            key = parts[0]
            value = parts[-1]
            if key in {"clockIdentity", "grandmasterIdentity"}:
                gm_clock_id = value
                break
    else:
        gm_clock_id = None

    steps_removed_val = info.get("stepsRemoved")
    role: Optional[str] = None
    if steps_removed_val is not None:
        try:
            role = "Grandmaster" if int(steps_removed_val) == 0 else "Slave"
        except ValueError:
            role = None

    if gm_clock_id is None:
        if role == "Grandmaster":
            fb_success, fb_output = run_pmc_command(["GET", "DEFAULT_DATA_SET"])
            if fb_success:
                for line in fb_output.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.replace("=", " ").split()
                    if len(parts) < 2:
                        continue
                    key = parts[0]
                    value = parts[-1]
                    if key == "clockIdentity":
                        gm_clock_id = value
                        break
        elif role == "Slave":
            fb_success, fb_output = run_pmc_command(["GET", "TIME_STATUS_NP"])
            if fb_success:
                for line in fb_output.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.replace("=", " ").split()
                    if len(parts) < 2:
                        continue
                    key = parts[0]
                    value = parts[-1]
                    if key in {"gmIdentity", "grandmasterIdentity"}:
                        gm_clock_id = value
                        break

    return UbuntuPtpStatus(
        success=True,
        role=role,
        steps_removed=steps_removed_val,
        offset_from_master=info.get("offsetFromMaster"),
        mean_path_delay=info.get("meanPathDelay"),
        port_identity=info.get("portIdentity"),
        grandmaster_clock_id=gm_clock_id,
        error=None if gm_success else gm_output if gm_output else None,
    )


def main():
    devices = ic4.DeviceEnum.devices()

    if len(devices) < 2:
        print("⚠ カメラが2台未満です。接続を確認してください。")
        return
    if len(devices) > 8:
        print(f"ℹ 8台を想定していますが、現在 {len(devices)} 台接続されています。先頭8台のみ対象にします。")
        devices = devices[:8]

    # 対象カメラの一覧表示
    print("=== 接続カメラ一覧 ===")
    for i, dev in enumerate(devices):
        print(f"[{i}] {dev.model_name} ({dev.serial}) [{dev.interface.display_name}]")
    print()

    # Grabber を開く
    grabbers: list[ic4.Grabber] = []
    try:
        for dev in devices:
            grabbers.append(ic4.Grabber(dev))

        # 各カメラの PropertyMap
        propmaps = [g.device_property_map for g in grabbers]

        # 可能なら PTP を有効化
        enabled_flags = [ensure_ptp_enabled(pm) for pm in propmaps]

        # PTP 収束待ち
        print(f"PTP 収束待ち中…（最大 {int(MAX_WAIT_SEC)} 秒）")
        t0 = time.time()
        statuses: list[str | None] = [None] * len(propmaps)

        while time.time() - t0 < MAX_WAIT_SEC:
            statuses = [get_ptp_status(pm) for pm in propmaps]
            if has_converged(statuses):
                break
            time.sleep(POLL_SEC)

        # Ubuntu側のPTP情報を取得
        ubuntu_status = fetch_ubuntu_ptp_status()

        # 結果表示
        print("\n=== Ubuntu PTP 状態 ===")
        if ubuntu_status.success:
            print(
                "Role={role}, stepsRemoved={steps}, offsetFromMaster={offset}, "
                "meanPathDelay={delay}, GrandmasterClockID={gm}".format(
                    role=ubuntu_status.role or "Unknown",
                    steps=ubuntu_status.steps_removed or "N/A",
                    offset=ubuntu_status.offset_from_master or "N/A",
                    delay=ubuntu_status.mean_path_delay or "N/A",
                    gm=ubuntu_status.grandmaster_clock_id or "N/A",
                )
            )
            if ubuntu_status.error:
                print(f"  注意: {ubuntu_status.error}")
        else:
            print(f"Ubuntu側のPTP状態取得失敗: {ubuntu_status.error}")

        print("\n=== カメラ PTP ステータス ===")
        masters = 0
        slaves = 0
        for i, (dev, st, en) in enumerate(zip(devices, statuses, enabled_flags)):
            st_disp = st or "Unknown"
            en_disp = "Enabled" if en else "N/A"   # ノードなし等は N/A
            print(f"[{i}] {dev.serial}: PTP={en_disp}, Status={st_disp}")
            if st == "Master":
                masters += 1
            elif st == "Slave":
                slaves += 1

        camera_masters = [dev.serial for dev, st in zip(devices, statuses) if st == "Master"]
        known_statuses = [st for st in statuses if st is not None]
        cameras_all_slave = bool(known_statuses) and len(known_statuses) == len(statuses) and all(
            st == "Slave" for st in known_statuses
        )

        print("\n=== 総合判定 ===")
        skip_warnings = False
        if ubuntu_status.success and ubuntu_status.role == "Grandmaster" and cameras_all_slave:
            print("✅ PTP同期 OK: Ubuntu=Grandmaster, Cameras=Slave")
            skip_warnings = True
        else:
            if ubuntu_status.success and ubuntu_status.role == "Grandmaster":
                if masters == 0:
                    print("✅ PTP同期 OK: Ubuntu=Grandmaster, Cameras=Slave")
                else:
                    print("⚠ UbuntuはGrandmasterだが、カメラにもMasterがいます。")
            elif camera_masters:
                if len(camera_masters) == 1:
                    print(
                        f"⚠ UbuntuはSlaveです（MasterはCamera Serial={camera_masters[0]}）"
                    )
                else:
                    masters_list = ", ".join(camera_masters)
                    print(f"⚠ 複数のカメラがMasterになっています: {masters_list}")
            else:
                print("⚠ Grandmasterを特定できませんでした。UbuntuまたはカメラのPTP設定を確認してください。")

        if not skip_warnings and not has_converged(statuses):
            print("  - 注意: カメラ側のPTPステータスが収束していません。")
            if masters == 0:
                print("    ・Master がいません（全台が Unknown/Slave/その他）。")
            elif masters > 1:
                print(f"    ・Master が {masters} 台います（同一ドメインでの衝突の可能性）。")
            print("    ・同一セグメント接続 / PTPドメイン一致 / スイッチのPTP透過設定 / IGMP設定 を確認してください。")
            print("    ・機種によりノード名が異なる場合があります。必要なら pm.dump() でノード探索してください。")

        if (
            ubuntu_status.success
            and ubuntu_status.role == "Slave"
            and ubuntu_status.offset_from_master is not None
        ):
            try:
                offset_val = float(ubuntu_status.offset_from_master)
            except ValueError:
                try:
                    offset_val = float(int(ubuntu_status.offset_from_master, 0))
                except ValueError:
                    offset_val = 0.0
            try:
                mean_delay_val = float(ubuntu_status.mean_path_delay or "0")
            except ValueError:
                try:
                    mean_delay_val = float(int(ubuntu_status.mean_path_delay or "0", 0))
                except ValueError:
                    mean_delay_val = 0.0
            if offset_val >= 1_000_000_000_000 or mean_delay_val > 100_000_000:
                print("  - 注意: PTP未収束の可能性があります（Ubuntuの offset/meanPathDelay が異常値）")

    finally:
        # 後始末：ストリームは使っていないので stream_stop() は不要
        for g in grabbers:
            try:
                g.device_close()
            except Exception:
                pass


if __name__ == "__main__":
    with ic4.Library.init_context(api_log_level=ic4.LogLevel.INFO, log_targets=ic4.LogTarget.STDERR):
        main()
