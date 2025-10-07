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

