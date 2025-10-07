##################################
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


##################################
# chktimestat.py

A utility to evaluate timestamp alignment across multiple industrial cameras synchronized via PTP on Ubuntu.
It verifies the host is PTP Grandmaster via `pmc`, triggers a simultaneous timestamp latch on all cameras, reads latched device times, and reports per-camera deltas (displayed in milliseconds; internal math in nanoseconds).

## Requirements

* Ubuntu with `linuxptp` (`pmc` available and connected to `/var/run/ptp4l` via UDS)
* The Imaging Source `imagingcontrol4` (IC4) Python package
* Cameras that expose `TIMESTAMP_LATCH` and `TIMESTAMP_LATCH_VALUE` via IC4
* No sudo required; `pmc` is used via UDS only

## How it works

1. Verify Grandmaster status using `pmc GET CURRENT_DATA_SET` (expects `stepsRemoved == 0`).
2. Open target cameras by serial.
3. For each sample:

   * Trigger `TIMESTAMP_LATCH` on all cameras first.
   * Read `TIMESTAMP_LATCH_VALUE` from each camera.
   * Compute the median of camera times.
   * Print each camera’s delta to the median in milliseconds and verdict against a ns threshold.
4. If multiple samples, print simple statistics.

## Usage

```bash
python chktimestat.py
python chktimestat.py --serials 05520125,05520126,05520128,05520129
python chktimestat.py --samples 10 --interval-ms 200
python chktimestat.py --threshold-ns 100000000
python chktimestat.py --assume-realtime-ptp
```

## Options

* `--serials`  Comma-separated camera serials (default: `05520125,05520126,05520128,05520129`)
* `--iface`  Network interface name for logging only (default: `enp3s0`)
* `--samples`  Number of iterations (default: `1`)
* `--interval-ms`  Interval between samples in ms (default: `0`)
* `--threshold-ns`  Absolute delta threshold in ns vs. median (default: `100000000` = 100 ms)
* `--timeout-s`  Overall timeout in seconds (default: `60`)
* `--assume-realtime-ptp`  Also print camera delta vs. `time.time_ns()` as a reference

## Example output

```
[Sample 1]
Ubuntu(host) PTP: role=Grandmaster, gmClockID=bcfce7.fffe.244daf
serial=05520125, camera_time_ns=1759801914897358848, delta_to_median_ms=-1.631232, verdict=OK
serial=05520126, camera_time_ns=...,                  delta_to_median_ms=-0.638208, verdict=OK
serial=05520128, camera_time_ns=...,                  delta_to_median_ms= 0.638208, verdict=OK
serial=05520129, camera_time_ns=...,                  delta_to_median_ms= 1.601536, verdict=OK
```

With multiple samples, a stats section is appended:

```
=== Statistics ===
serial=05520125, mean_delta_ns=-1200000, stddev_ns=300000, max_abs_delta_ns=1800000, verdict=OK
...
Max_abs_delta_ns=1900000
```

## Exit codes

* `0` all cameras within threshold
* `2` one or more cameras exceed threshold
* `1` fatal error (e.g., `pmc`/IC4 failure)

## Troubleshooting

* `pmc command not found`
  Install `linuxptp` and ensure `/usr/sbin/pmc` or `pmc` in `PATH`.
* `Unable to determine stepsRemoved`
  `ptp4l` not running or `pmc` not connected to `/var/run/ptp4l`.
* `TIMESTAMP_LATCH_VALUE unavailable`
  Camera property unsupported or access failed; verify IC4 support and connection.
* Large deltas
  Check PTP domain, network path, switch PTP transparency, and that host is truly GM.

## Notes

* Displayed deltas are in milliseconds; internal calculations remain in nanoseconds.
* Latching is done “all cameras first, then read” to minimize skew.

