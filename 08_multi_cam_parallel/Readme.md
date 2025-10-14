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
# s06_rec4cams — Multi-camera BayerGR8 Recorder (PTP-synchronized)

Record synchronized raw BayerGR8 frames from multiple industrial cameras using The Imaging Source **imagingcontrol4** (IC4).
Two output modes:

* **HEVC (default):** stream raw frames into `ffmpeg` (NVENC) and save `.mp4`.
* **RAW mode (`--raw-output`):** write a concatenated raw byte stream (`.raw`) per camera (no compression, no loss).

The program latches device timestamps, verifies PTP offsets, schedules a common start, and records for a fixed duration per run.

---

## Requirements

* **OS & Python**

  * Linux recommended (tested with `pmc`/`ptp4l` tools available).
  * Python 3.9+.
* **IC4 SDK**

  * `imagingcontrol4` Python package installed and licensed.
* **Cameras**

  * Cameras that support GenICam/GenTL and BayerGR8, with action/trigger support.
* **FFmpeg (HEVC mode only)**

  * `ffmpeg` with **NVENC** (`hevc_nvenc`) available on the system.
* **PTP requirement (Grand Master)**

  * A **PTP Grand Master** must be present on the capture network.

    * EITHER this PC acts as GM (e.g., run `ptp4l` in GM mode on the capture NIC)
    * OR an external GM (PTP-capable switch/clock) is present.
  * Ensure all cameras report **`Slave`** before capture. Quick sanity check:

    ```bash
    pmc -u -b 0 -d 0 'GET CURRENT_DATA_SET'
    # Expect stepsRemoved close to 0 and each camera’s status = Slave
    ```

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install imagingcontrol4
# ffmpeg must be installed system-wide if you use HEVC mode
```

---

## Usage

```bash
python s06_rec4cams.py [--start-delay-s SECONDS] [--offset-threshold-ms MS] [--raw-output]
```

**Common options**

* `--start-delay-s` (default: `10.0`)
  Delay from scheduling to the first frame trigger.
* `--offset-threshold-ms` (default: `3.0`)
  Allowed PTP master–camera offset at scheduling time.
* `--raw-output`
  If set, writes raw BayerGR8 stream (`.raw`) per camera and **does not** start `ffmpeg`.

### Examples

**HEVC (default):**

```bash
python s06_rec4cams.py --start-delay-s 8 --offset-threshold-ms 2
# Outputs: cam<serial>_YYYYMMDD_HHMMSSmmm.mp4 per camera
```

**RAW mode:**

```bash
python s06_rec4cams.py --raw-output --start-delay-s 8
# Outputs: cam<serial>_YYYYMMDD_HHMMSSmmm.raw per camera
```

At startup the tool:

1. Runs a PTP pre-check (`pmc … GET CURRENT_DATA_SET`).
2. Waits until all cameras report **Slave**.
3. Latches timestamps on the cameras, calculates offsets vs host, enforces threshold.
4. Schedules a common start time across cameras.
5. Streams frames to either `ffmpeg` (HEVC) **or** a `.raw` file (RAW mode).

---

## Output formats

### `.mp4` (HEVC/NVENC)

* YUV420p, target ~2.2 Mbps per stream (configurable in code).
* One file per camera per run.

### `.raw` (BayerGR8)

* **Concatenated frames**: width × height bytes per frame; no headers.
* Order: sequential frames for the full duration.
* Example size estimate (warning is printed when `--raw-output` is used):

  ```
  1920×1080×1 byte × 50 fps × 10 s ≈ 0.99 GiB per camera
  ```

---

## Working with RAW files

### Encode a `.raw` file to MP4 (same pipeline as live HEVC mode)

```bash
WIDTH=1920
HEIGHT=1080
FPS=50
INPUT=cam05520129_YYYYMMDD_HHMMSSmmm.raw
OUTPUT=cam05520129_YYYYMMDD_HHMMSSmmm.mp4

ffmpeg -hide_banner -nostats -loglevel error \
  -f rawvideo -pix_fmt bayer_grbg8 -s ${WIDTH}x${HEIGHT} -framerate ${FPS} \
  -i "${INPUT}" \
  -vf format=yuv420p \
  -c:v hevc_nvenc -b:v 2200k -maxrate 2200k -bufsize 4400k -preset p4 \
  "${OUTPUT}"
```

> This reproduces the same options used when streaming to ffmpeg during live capture.

### View RAW without loss (no “codec” to detect)

Bayer `.raw` is not directly playable; it needs **demosaicing** and a pixel format.
Two convenient options:

1. **Quick preview using ffplay with software demosaic** (no compression):

   ```bash
   ffplay -hide_banner -loglevel error \
     -f rawvideo -pix_fmt bayer_grbg8 -s ${WIDTH}x${HEIGHT} -framerate ${FPS} \
     -i "${INPUT}" \
     -vf "format=rgb24,demosaic=mode=bilinear"
   ```

   * Replace `bilinear` with `malvar`/`vng` if your ffmpeg build supports those.

2. **Convert losslessly to a playable RGB AVI:**

   ```bash
   ffmpeg -hide_banner -loglevel error \
     -f rawvideo -pix_fmt bayer_grbg8 -s ${WIDTH}x${HEIGHT} -framerate ${FPS} \
     -i "${INPUT}" \
     -vf "format=rgb24,demosaic=mode=bilinear" \
     -c:v ffv1 -level 3 -g 1 "${INPUT%.raw}_rgb_ffv1.avi"
   ```

   * `ffv1` is mathematically lossless; file size will be large but VLC will play it.

> VLC cannot “identify a codec” for raw Bayer because it’s not a containerized, self-describing format. Use `ffplay` or convert first.

---

## Logs & behavior

* PTP pre-check logs `stepsRemoved` and warns if parsing fails.
* Blocks until all cameras report `Slave`, otherwise exits with code `2`.
* During scheduling, logs each camera’s offset vs host and enforces `--offset-threshold-ms`.
* In RAW mode, prints a **storage estimate** before recording.
* Cleanup ensures writer handles are flushed/closed even on early termination.

---

## Configuration points in code

* **Camera list:** `SERIAL_NUMBERS` array.
* **Frame size/rate/duration:** in `main()` (`WIDTH/HEIGHT/FRAME_RATE/CAPTURE_DURATION`).
* **FFmpeg encoding parameters:** `build_ffmpeg_command()`.

---

## Troubleshooting

* **Cameras won’t reach Slave:**

  * Verify GM is active; check NIC, PTP profile, and that `ptp4l`/switch allow two-step/one-step as needed.
  * `pmc -u -b 0 -d 0 'GET CURRENT_DATA_SET'` and inspect `stepsRemoved` and port states.
* **NVENC not available:**

  * Switch to software HEVC (`-c:v libx265`) or H.264 (`-c:v libx264`) in `build_ffmpeg_command`.
* **RAW playback shows “codec not identified”:**

  * Use `ffplay` with `-f rawvideo -pix_fmt bayer_grbg8 -s WxH` and add a `demosaic` filter, or convert as shown above.

---

## License

Project licensing follows the terms you apply to this repository. IC4 and camera SDKs follow their respective licenses.

---
# linuxptp (ptp4l / phc2sys / pmc) — Quick README

> Your app talks to `pmc` at **`/var/run/ptp4l`**. Make sure `ptp4l` creates its Unix socket there (use `-s /var/run/ptp4l` or the systemd unit below).

## Goal & Prereqs

* Make the PC a **PTP Grand Master (GM)** (or a Slave to an external GM) so cameras converge to **Slave**.
* NIC must support **hardware timestamping** (`ethtool -T <iface>`).
* Install `linuxptp` (`ptp4l`, `phc2sys`, `pmc`) and `ethtool`.

## Install

```bash
sudo apt-get update
sudo apt-get install -y linuxptp ethtool
ip link                     # find NIC (e.g., enp3s0)
ethtool -T enp3s0           # confirm HW timestamping
```

## Quick test (PC as GM)

Terminal 1 — `ptp4l` (GM), UDPv4/E2E/2step, socket at `/var/run/ptp4l`:

```bash
sudo ptp4l -i enp3s0 -f /dev/stdin -2 -m -s /var/run/ptp4l <<'EOF'
[global]
time_stamping=hardware
network_transport=UDPv4
delay_mechanism=E2E
twoStepFlag=1
defaultDS.domainNumber=0
gmCapable=1
priority1=10
slaveOnly=0
[enp3s0]
logAnnounceInterval=1
logSyncInterval=-3
logMinDelayReqInterval=0
EOF
```

Terminal 2 — **sync PHC → system clock** (recommended; keep system time aligned with NIC PHC):

```bash
sudo phc2sys -s enp3s0 -c CLOCK_REALTIME -O 0 -w
```

Terminal 3 — check state with `pmc` (same socket path as your app):

```bash
pmc -u -s /var/run/ptp4l 'GET CURRENT_DATA_SET'
pmc -u -s /var/run/ptp4l 'GET PORT_DATA_SET'
# Expect GM PC: stepsRemoved = 0
```

## Permissions (first time setup)

Create a `ptp` group and udev rule for `/dev/ptp*`:

```bash
sudo groupadd -f ptp
echo 'KERNEL=="ptp*", GROUP="ptp", MODE="0660"' | sudo tee /etc/udev/rules.d/90-ptp.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG ptp $USER   # re-login afterwards
```

## systemd (recommended for production)

`/etc/systemd/system/ptp4l.service`:

```ini
[Unit]
Description=linuxptp ptp4l
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=ptp
RuntimeDirectory=ptp4l
RuntimeDirectoryMode=0775
ExecStart=/usr/sbin/ptp4l -f /etc/linuxptp/ptp4l-gm.conf -i enp3s0 -2 -m -s /var/run/ptp4l
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/linuxptp/ptp4l-gm.conf` (GM):

```ini
[global]
time_stamping=hardware
network_transport=UDPv4
delay_mechanism=E2E
twoStepFlag=1
defaultDS.domainNumber=0
gmCapable=1
priority1=10
slaveOnly=0
[enp3s0]
logAnnounceInterval=1
logSyncInterval=-3
logMinDelayReqInterval=0
```

`/etc/systemd/system/phc2sys.service`:

```ini
[Unit]
Description=linuxptp phc2sys
After=ptp4l.service
Requires=ptp4l.service

[Service]
Type=simple
User=root
Group=ptp
ExecStart=/usr/sbin/phc2sys -s enp3s0 -c CLOCK_REALTIME -O 0 -w
CapabilityBoundingSet=CAP_SYS_TIME
AmbientCapabilities=CAP_SYS_TIME
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ptp4l phc2sys
```

Optional capabilities (if you run without full root):

```bash
sudo setcap cap_net_raw,cap_net_admin+ep /usr/sbin/ptp4l
sudo setcap cap_sys_time+ep              /usr/sbin/phc2sys
```

## pmc cheatsheet (use the same socket path)

```bash
pmc -u -s /var/run/ptp4l 'GET CURRENT_DATA_SET'       # GM/Slave, stepsRemoved, etc.
pmc -u -s /var/run/ptp4l 'GET PORT_DATA_SET'          # per-port state
pmc -u -s /var/run/ptp4l 'GET TIME_PROPERTIES_DATA_SET'
pmc -u -s /var/run/ptp4l 'GET DEFAULT_DATA_SET'
```

## Troubleshooting (quick)

* **`pmc: connect: Permission denied`** → Ensure `ptp4l` runs with `Group=ptp`, `RuntimeDirectoryMode=0775`, user in `ptp` group.
* **No `/dev/ptp*` or HW TS unsupported** → Check `ethtool -T`, apply udev rule, re-login.
* **Cameras don’t go Slave** → Check `domainNumber`, remove extra GMs, test minimal topology.
* **PC GM but `stepsRemoved != 0`** → Wrong config (not GM); use the GM conf above.
* **System vs PHC drift** → Ensure **one direction** with `phc2sys` (PHC→System as shown), don’t run both directions.
---
了解しました ✅
以下は、内容を簡潔にまとめた **英語版 README.md** です。
Ubuntu 24.04 + RTX 5060 Ti + CUDA 13 環境向けで、誰が読んでもすぐ再現できる形です。

---

````markdown
# Build FFmpeg with NVIDIA GPU (NVENC/NVDEC) Support on Ubuntu 24.04

## Overview
This guide explains how to compile **FFmpeg** with **CUDA / NVENC / NVDEC** support  
for NVIDIA GPUs (tested on RTX 5060 Ti, driver 580.65.06, CUDA 13.0).

---

## 1. Install Dependencies
```bash
sudo apt update
sudo apt install -y build-essential yasm cmake libtool \
  libc6-dev unzip wget libnuma-dev nasm pkg-config \
  libx264-dev libx265-dev libvpx-dev libfdk-aac-dev \
  libmp3lame-dev libopus-dev libsdl2-dev
````

---

## 2. Install NVENC Headers

```bash
cd ~/git
git clone https://git.videolan.org/git/ffmpeg/nv-codec-headers.git
cd nv-codec-headers
make
sudo make install
cd ..
```

---

## 3. Get FFmpeg Source

```bash
cd ~/git
git clone https://git.ffmpeg.org/ffmpeg.git ffmpeg
cd ffmpeg
```

---

## 4. Configure

```bash
./configure \
  --enable-nonfree \
  --enable-cuda-nvcc \
  --enable-libnpp \
  --extra-cflags=-I/usr/local/cuda/include \
  --extra-ldflags=-L/usr/local/cuda/lib64 \
  --disable-static \
  --enable-shared \
  --enable-ffplay
```

---

## 5. Build and Install

```bash
make -j$(nproc)
sudo make install
sudo ldconfig
```

---

## 6. Verify NVENC Support

```bash
ffmpeg -encoders | grep nvenc
```

You should see:

```
h264_nvenc
hevc_nvenc
av1_nvenc
```

---

## 7. GPU Encoding Example

```bash
ffmpeg -hwaccel cuda -i input.mp4 \
  -c:v h264_nvenc -preset fast -b:v 5M output.mp4
```

---

## 8. Play with GPU Acceleration (optional)

```bash
ffplay -hwaccel cuda output.mp4
```

---

### Notes

* `--enable-nonfree` is required due to NVIDIA SDK license.
* `--enable-libnpp` enables CUDA image processing.
* `libsdl2-dev` is required to build **ffplay**.
* Redistribution of this build is **not allowed**.

---

✅ **Done!**
FFmpeg with full NVIDIA GPU acceleration is now ready.
---

