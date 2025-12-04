# Calib Board Geometry Viewer

This standalone tool reads `Calib_board.toml`, reconstructs camera poses, and exports:

- `cameras.csv`: camera centers and optical axis vectors.
- `pairs.csv`: pairwise baselines and optical-axis angles.
- `plot3d.png`: Matplotlib 3D visualization with isotropic axes.
- `calib_view.blend`: Blender scene (optional) with cameras placed at the recovered poses.

## Usage

```
./bin/calib_geom_viewer \
  --toml /path/to/Calib_board.toml \
  --out-dir /path/to/new/output_dir \
  --matplotlib on \
  --blender on \
  --blender-exec /path/to/blender
```

Notes:

- The output directory must **not exist** beforehand to avoid overwriting prior results.
- Set `--matplotlib off` or `--blender off` if those artifacts are not needed.
- Blender export requires a working `blender` executable accessible via `--blender-exec`. The CLI runs Blender in background mode with `--factory-startup`, so it does not mutate existing user scenes or configuration.
- If `python3 -m calib_geom_viewer ...` is more convenient than the wrapper script, both invocation styles are equivalent.

## Logging & Validation

- Invalid camera sections (missing keys, non-finite values, etc.) are skipped with clear error messages.
- When fewer than two valid cameras are available, `pairs.csv` is omitted (a warning is logged) while the remaining artifacts continue to build.
- Axis length (default `0.3 m`) can be adjusted via `--axis-length` to suit the calibration scale.

## Dependencies

- Python 3.12+
- `numpy`
- `matplotlib` (only needed when `--matplotlib on`)
- Blender 3.x (only needed when `--blender on`)
