# ptp_sync_check.py

Utility to enable and verify PTP synchronization across 2–8 industrial cameras on Ubuntu.
It toggles each camera’s PTP property (if available), waits for convergence, queries the host’s `linuxptp` status via `pmc` (UDS), and prints a clear summary (Ubuntu role/GM ID, each camera’s PTP status, and an overall verdict).

## Requirements

* Ubuntu with `linuxptp` installed (`pmc` accessible; UDS at `/var/run/ptp4l`)
* The Imaging Source `imagingcontrol4` (IC4) Python package
* Cameras exposing PTP properties (any of: `PtpEnable`/`GevIEEE1588Enable` and `PtpStatus`/`GevIEEE1588Status`)
* No `sudo` required (script uses `pmc -u` over UDS)

## What the script does

1. Enumerates up to 8 connected cameras and opens each with IC4.
2. Enables PTP on each camera if the property exists.
3. Polls camera PTP status until either convergence or timeout:

   * Convergence = exactly one `Master` and at least one `Slave`.
4. Queries Ubuntu host PTP via `pmc`:

   * `GET CURRENT_DATA_SET` to infer role (`stepsRemoved == 0` → Grandmaster)
   * `GET GRANDMASTER_SETTINGS_NP` for GM clock identity
   * Fallbacks: `GET DEFAULT_DATA_SET` (host GM) or `GET TIME_STATUS_NP` (host Slave)
5. Prints:

   * Ubuntu(host) PTP role and Grandmaster Clock ID
   * Each camera’s “PTP=Enabled/N/A, Status=Master/Slave/Unknown”
   * Overall judgement with actionable hints if not converged

## Usage

```bash
python ptp_sync_check.py
```

No CLI flags are required; the script auto-detects 2–8 cameras and uses sensible defaults:

* Convergence wait: up to 30 seconds (poll every 0.5 s)
* Uses UDS: `/var/run/ptp4l`
* Calls `pmc` as `/usr/sbin/pmc` (if not present, falls back to `pmc` in `PATH`)

## Example output

```
=== 接続カメラ一覧 ===
[0] DFK 33GR0234 (05520129) [enp3s0]
[1] DFK 33GR0234 (05520125) [enp3s0]
[2] DFK 33GR0234 (05520128) [enp3s0]
[3] DFK 33GR0234 (05520126) [enp3s0]

PTP 収束待ち中…（最大 30 秒）

=== Ubuntu PTP 状態 ===
Role=Grandmaster, stepsRemoved=0, offsetFromMaster=0.0, meanPathDelay=0.0, GrandmasterClockID=bcfce7.fffe.244daf

=== カメラ PTP ステータス ===
[0] 05520129: PTP=Enabled, Status=Slave
[1] 05520125: PTP=Enabled, Status=Slave
[2] 05520128: PTP=Enabled, Status=Slave
[3] 05520126: PTP=Enabled, Status=Slave

=== 総合判定 ===
✅ PTP同期 OK: Ubuntu=Grandmaster, Cameras=Slave
```

If not converged, it prints helpful diagnostics (e.g., multiple Masters, no Master, domain/switch settings to check).

## Notes & limits

* Cameras without a PTP enable/status node are shown as `PTP=N/A` and `Status=Unknown` and don’t block the run.
* The host NIC does **not** need to support PHC; the script relies on `pmc` over UDS, not PHC reads.
* Property names vary by model; the script checks both GenICam-style (`PtpEnable`, `PtpStatus`) and GigE Vision names (`GevIEEE1588Enable`, `GevIEEE1588Status`).

## Troubleshooting

* “pmc コマンドが見つかりません”
  Install `linuxptp` and ensure `/usr/sbin/pmc` or `pmc` is in `PATH`.
* “Ubuntu側のPTP状態取得失敗” or empty pmc output
  Ensure `ptp4l` is running and its management socket is at `/var/run/ptp4l`.
* Cameras never reach `Slave`
  Check PTP domain alignment, switch PTP transparency, IGMP/multicast, and that only one GM wins the BMCA.
  Verify camera properties via IC4 (you can dump available nodes if needed).


---
# `chktimestat.py` — Check camera timestamps against Ubuntu (PTP GM)

A small CLI tool to verify time alignment of multiple network cameras against the host PC acting as PTP Grandmaster (GM).
It latches each camera’s device timestamp, takes a host reference time around the latch, and prints the per-camera deltas and pass/fail.

## What it does

* Verifies the host’s PTP role via `pmc` (`CURRENT_DATA_SET`) and shows the GM clock ID.
* For each sample:

  * Records the host time just **before** and **after** issuing a **simultaneous TIMESTAMP_LATCH** to all cameras.
  * Uses the **midpoint** of the two host times as the GM reference.
  * Reads each camera’s `TIMESTAMP_LATCH_VALUE` (ns) and computes `camera_time_ns - host_ref_ns`.
  * Prints deltas in **milliseconds** (display only) and OK/NG based on a threshold (default ±3 ms).
* Optionally prints simple statistics when taking multiple samples.
* Returns exit code `0` if all cameras pass, otherwise `2` (non-fatal per camera; no early abort).

## Requirements

* Ubuntu with `linuxptp` installed and `pmc` accessible (e.g. `/usr/sbin/pmc`).
* `ptp4l` running and the host synchronized as **Grandmaster** (or the tool will error).
* Python 3.9+.
* The Imaging Source **IC Imaging Control 4** Python package (`imagingcontrol4`) and supported cameras.

> Note: A PTP-capable NIC/PHC is **not required** for this tool’s GM reference — it uses `time.time_ns()` on the host, bracketed around the camera latch, and takes the midpoint.

## Install

```bash
# linuxptp
sudo apt-get install linuxptp

# IC4 Python SDK (per vendor docs)
pip install imagingcontrol4
```

## Usage

```bash
python chktimestat.py \
  --serials 05520125,05520126,05520128,05520129 \
  --threshold-ns 3000000 \
  --samples 1 \
  --interval-ms 0 \
  --timeout-s 60
```

### Arguments

* `--serials`
  Comma-separated camera serials to check (default: `05520125,05520126,05520128,05520129`).
* `--threshold-ns`
  Absolute pass/fail threshold **vs host reference** in **nanoseconds** (default: `3_000_000` = 3 ms).
* `--samples`
  Number of measurement iterations (default: `1`). If `>1`, stats are printed.
* `--interval-ms`
  Interval between samples (default: `0`).
* `--timeout-s`
  Overall timeout for the run (default: `60`).
* `--assume-realtime-ptp`
  Also prints a raw delta vs `time.time_ns()` (debug aid). Does not affect verdicts.
* `--iface`
  Network interface name (for logging only).

## Example output

```
[Sample 1]
Ubuntu(host) PTP: role=Grandmaster, gmClockID=bcfce7.fffe.244daf
serial=05520125, camera_time_ns=1759801914897358848, delta_to_gm_ms=-1.631232, verdict=OK
serial=05520126, camera_time_ns=1759801914898351872, delta_to_gm_ms=-0.638208, verdict=OK
serial=05520128, camera_time_ns=1759801914899628288, delta_to_gm_ms=0.638208, verdict=OK
serial=05520129, camera_time_ns=1759801914900591616, delta_to_gm_ms=1.601536, verdict=OK
```

If `--samples > 1`, a statistics section (in ns) follows:

```
=== Statistics ===
serial=05520125, mean_delta_ns=..., stddev_ns=..., max_abs_delta_ns=..., verdict=OK
...
Max_abs_delta_ns=...
```

## Exit codes

* `0` — All cameras within threshold across all samples.
* `2` — One or more cameras exceeded the threshold.
* `1` — Fatal error (e.g., `pmc` not found, host not GM, device open/latch/read failure).

## How it works (brief)

1. Confirms host is GM using `pmc GET CURRENT_DATA_SET` (`stepsRemoved == 0`).
2. For each sample:

   * Take `host_ref_before = time.time_ns()`.
   * Trigger `TIMESTAMP_LATCH` on **all cameras first**.
   * Take `host_ref_after = time.time_ns()`.
   * Reference `host_ref = (before + after) // 2` to approximate the GM time at latch.
   * Read each camera’s `TIMESTAMP_LATCH_VALUE` (ns), compute `delta = cam - host_ref`.
   * Display `delta_to_gm_ms` and verdict (±threshold).

This midpoint approach reduces bracketing delay error while avoiding a PHC dependency.

## Troubleshooting

* `ERROR: pmc CURRENT_DATA_SET failed` / `Unable to determine stepsRemoved`
  Ensure `pmc` exists, `ptp4l` is running, and the host is actually GM on the PTP domain in use.
* `Camera with serial ... not found`
  Check cabling and that the camera is visible in `ic4.DeviceEnum.devices()`.
* `TIMESTAMP_LATCH`/`TIMESTAMP_LATCH_VALUE` errors
  Confirm the camera supports GenICam timestamp latch and that PTP is enabled on the device.

## Notes & limits

* Displayed deltas are in **ms**, internal thresholds and stats use **ns**.
* The GM reference is the host’s realtime clock midpoint around the latch. If your host clock is not disciplined to PTP or is unstable, measured deltas may reflect that.


---
# `s04_rec4cams.py` — Record 4 network cameras in sync (IC4 + FFmpeg/NVENC)

Multi-camera recorder that opens four The Imaging Source cameras via **IC Imaging Control 4 (IC4)**, schedules a common start time on each device, and writes each stream to an **H.265/HEVC** MP4 using **FFmpeg** (NVENC). Designed for PTP-synchronized cameras so capture start aligns closely across devices.

## What it does

* Finds cameras by **serial** (`SERIAL_NUMBERS` list).
* Configures each camera for:

  * `1920x1080`, `BayerGR8`, frame rate from `FRAME_RATE` (default **50.0 fps**).
  * Hardware action trigger:

    * Latches the camera’s device time (`TIMESTAMP_LATCH` / `TIMESTAMP_LATCH_VALUE`).
    * Schedules `ACTION_SCHEDULER_TIME = device_time_ns + 10s`.
    * Sets `ACTION_SCHEDULER_INTERVAL = 20_000 µs` (20 ms → **50 fps**) and commits.
    * Sets `TRIGGER_SELECTOR=FrameStart`, `TRIGGER_SOURCE=Action0`, `TRIGGER_MODE=On`.
* Streams frames through an IC4 **QueueSink** and pipes raw Bayer bytes to **FFmpeg**.
* Encodes each camera to its own MP4 (HEVC/NVENC), file name like:

  ```
  cam05520125_YYYYMMDD_HHMMSSmmm.mp4
  ```
* Runs each camera capture on its own thread for `CAPTURE_DURATION` (default **600 s**).
* Cleans up robustly (flush/close pipes, stop acquisition/stream, close devices).

> Start-time alignment comes from scheduling the same absolute device time on each camera. With PTP enabled on the cameras and network, the recorded videos begin within a very small temporal skew.

## Requirements

* **Ubuntu** (or Linux) with:

  * The Imaging Source **IC4** Python SDK: `imagingcontrol4`
  * **FFmpeg** with **NVENC**: `ffmpeg` built with `--enable-nvenc` and a supported NVIDIA GPU/driver
* Cameras that support GenICam action triggering and timestamp latch.

Install hints:

```bash
pip install imagingcontrol4
ffmpeg -encoders | grep nvenc   # verify NVENC is available
```

## Usage

```bash
python s04_rec4cams.py
```

Edit the top of the script to match your setup:

* `SERIAL_NUMBERS`: camera serials to record.
* `WIDTH, HEIGHT, FRAME_RATE, CAPTURE_DURATION` in `main()`.
* The FFmpeg settings in `build_ffmpeg_command()` (codec, bitrate, preset).

### Output

One MP4 per camera in the current directory, e.g.:

```
cam05520125_20250107_142355123.mp4
cam05520126_20250107_142355123.mp4
cam05520128_20250107_142355123.mp4
cam05520129_20250107_142355123.mp4
```

## FFmpeg pipeline (per camera)

* Input: rawvideo from stdin, `bayer_grbg8`, `1920x1080 @ 50 fps`
* Filter: `format=yuv420p` (for broad player compatibility)
* Encoder: `hevc_nvenc` with ~2.2 Mbps target (tweak as needed)

If you don’t have NVENC, change in `build_ffmpeg_command()`:

* `hevc_nvenc` → `libx265` (CPU) or `libx264`
* Adjust bitrate/preset accordingly.

## Notes & tips

* **PTP**: For best sync, enable PTP on all cameras and ensure they share the same domain. This script doesn’t verify PTP state; it assumes the action schedules refer to aligned device clocks.
* **Lead time**: Start time is set to **now + 10 seconds (device time)** to give all cameras time to commit the schedule.
* **Throughput**: Bayer → HEVC is compute-light with NVENC, but disk I/O can still bottleneck. Monitor dropped frames in logs.
* **Changing FPS**: If you change `FRAME_RATE`, also update `interval_us` in `configure_camera_for_bayer_gr8()`:

  ```
  interval_us = int(1_000_000 / FRAME_RATE)
  ```
* **Pixel format**: Cameras output BayerGR8; FFmpeg converts to YUV420P. If you need lossless raw capture, replace the encoder with a raw file writer (e.g., `.raw` or `.mkv` with `-c:v rawvideo`) and manage size.

## Troubleshooting

* “device not found”: Check serials and camera enumeration via `ic4.DeviceEnum.devices()`.
* “failed to set …”: Some properties differ by model/firmware. Verify availability in the device’s GenICam nodemap.
* “ffmpeg stdin was not created” / “ffmpeg terminated unexpectedly”: Ensure FFmpeg is installed and NVENC is supported; try a CPU encoder to isolate.
* Misaligned start times: Confirm PTP is enabled and stable, and that your network switch supports PTP/IGMP as required by your cameras.

## File layout (key functions)

* `configure_camera_for_bayer_gr8(...)`: Sets resolution/format/FPS and programs the action scheduler and trigger source.
* `allocate_queue_sink(...)`: Prepares the streaming sink and buffers.
* `record_raw_frames(...)`: Starts acquisition, pulls frames, writes to FFmpeg stdin for the requested duration.
* `build_ffmpeg_command(...)`: Encapsulates the FFmpeg arguments.
* `find_device_by_serial(...)`: Resolves devices by serial.
