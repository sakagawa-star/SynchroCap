from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Sequence

from .geometry import CameraPose

BLENDER_SCRIPT = textwrap.dedent(
    """
    import bpy
    import json
    import mathutils
    import sys
    from pathlib import Path


    def load_payload(json_path):
        with Path(json_path).open("r", encoding="utf-8") as handle:
            return json.load(handle)


    def clear_scene():
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False, confirm=False)


    def add_camera(entry, axis_len):
        cam_data = bpy.data.cameras.new(entry["name"])
        cam_obj = bpy.data.objects.new(entry["name"], cam_data)
        bpy.context.scene.collection.objects.link(cam_obj)
        cv_to_blender = mathutils.Matrix(((1, 0, 0), (0, -1, 0), (0, 0, -1)))
        rot_c2w = mathutils.Matrix(entry["rotation_c2w"])
        rot_blender = rot_c2w @ cv_to_blender
        matrix_world = rot_blender.to_4x4()
        matrix_world.translation = mathutils.Vector(entry["center"])
        cam_obj.matrix_world = matrix_world

        axis_vec = mathutils.Vector(entry["axis"]) * axis_len
        start = mathutils.Vector(entry["center"])
        line_mesh = bpy.data.meshes.new(f"{entry['name']}_axis_mesh")
        line_mesh.from_pydata([start, start + axis_vec], [(0, 1)], [])
        line_mesh.update()
        line_obj = bpy.data.objects.new(f"{entry['name']}_axis", line_mesh)
        line_obj.display_type = "WIRE"
        bpy.context.scene.collection.objects.link(line_obj)


    def main():
        args = sys.argv[sys.argv.index("--") + 1 :]
        json_path, out_path, axis_len = args
        data = load_payload(json_path)
        clear_scene()
        for entry in data["cameras"]:
            add_camera(entry, float(axis_len))
        bpy.context.scene.world.color = (0.05, 0.05, 0.05)
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(out_path)))


    if __name__ == "__main__":
        main()
    """
)


def build_blender_scene(
    cameras: Sequence[CameraPose],
    axis_length: float,
    blend_path: Path,
    blender_exec: str,
    logger: logging.Logger,
) -> None:
    """Invoke Blender in background mode to create a .blend file."""

    if not cameras:
        raise ValueError("At least one camera is required for Blender export.")

    resolved_exec = shutil.which(blender_exec)
    if resolved_exec is None:
        raise FileNotFoundError(f"Blender executable not found: {blender_exec}")

    if blend_path.exists():
        raise FileExistsError(f"Blend file already exists: {blend_path}")

    payload = {
        "cameras": [
            {
                "name": cam.name,
                "center": [float(x) for x in cam.center],
                "rotation_c2w": [[float(v) for v in row] for row in cam.rotation_c2w],
                "axis": [float(x) for x in cam.axis],
            }
            for cam in cameras
        ]
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        json_path = tmp_dir_path / "cameras.json"
        script_path = tmp_dir_path / "build_scene.py"
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        script_path.write_text(BLENDER_SCRIPT, encoding="utf-8")

        cmd = [
            resolved_exec,
            "--background",
            "--factory-startup",
            "--python",
            str(script_path),
            "--",
            str(json_path),
            str(blend_path),
            str(axis_length),
        ]
        logger.debug("Running Blender command: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as exc:  # pragma: no cover - requires Blender
            raise RuntimeError("Blender export failed; see Blender output for details.") from exc
