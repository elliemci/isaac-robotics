"""Headless orbit capture of h1_ros_locomotion_wearhouse.usd (sub-project C).

Run with Isaac Lab's python:
  isaaclab.sh -p docs/capture/capture_h1_scene.py --out <frames_dir> --still <png>

The scene is only opened, never saved. The orbit camera and a ground plane are
authored on the session layer for the capture and are discarded on exit.
Note: /World/warehouse references a path that does not exist, so the warehouse
is absent from the render (left as is on purpose).
"""
import argparse
import math
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--usd", default=str(Path(__file__).resolve().parents[2] / "assets/robots/mobile_robot/h1_ros_locomotion_wearhouse.usd"))
p.add_argument("--out", required=True)
p.add_argument("--still", default=None)
p.add_argument("--frames", type=int, default=180)
p.add_argument("--fps", type=float, default=15.0)
args = p.parse_args()

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "width": 1280, "height": 720})

import numpy as np
import omni.replicator.core as rep
import omni.usd
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

ctx = omni.usd.get_context()
ctx.open_stage(args.usd)
for _ in range(20):
    app.update()
stage = ctx.get_stage()
stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))

cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
box = cache.ComputeWorldBound(stage.GetPrimAtPath("/World/h1_ROS")).ComputeAlignedRange()
c = (box.GetMin() + box.GetMax()) / 2
size = box.GetSize()
print(f"[capture] h1 bbox min={box.GetMin()} max={box.GetMax()}")

ground = UsdGeom.Cube.Define(stage, "/Capture/Ground")
ground.GetSizeAttr().Set(1.0)
UsdGeom.Xformable(ground).AddTranslateOp().Set(Gf.Vec3d(c[0], c[1], box.GetMin()[2] - 0.01))
UsdGeom.Xformable(ground).AddScaleOp().Set(Gf.Vec3f(12, 12, 0.02))
ground.CreateDisplayColorAttr([Gf.Vec3f(0.35, 0.37, 0.4)])
dome = UsdLux.DomeLight.Define(stage, "/Capture/Dome")
dome.CreateIntensityAttr(900)

cam = UsdGeom.Camera.Define(stage, "/Capture/Camera")
cam.GetFocalLengthAttr().Set(24)
xf = UsdGeom.Xformable(cam).AddTransformOp()
rp = rep.create.render_product("/Capture/Camera", (1280, 720))
rgb = rep.AnnotatorRegistry.get_annotator("rgb")
rgb.attach([rp])

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for f in out.glob("*.png"):
    f.unlink()
radius = max(size[0], size[1], size[2]) * 2.5
center = Gf.Vec3d(c[0], c[1], c[2])
for i in range(args.frames):
    a = 2 * math.pi * i / args.frames + math.radians(35)
    eye = Gf.Vec3d(c[0] + radius * math.cos(a), c[1] + radius * math.sin(a), c[2] + size[2] * 0.25)
    xf.Set(Gf.Matrix4d().SetLookAt(eye, center, Gf.Vec3d(0, 0, 1)).GetInverse())
    rep.orchestrator.step(rt_subframes=4, delta_time=0.0, pause_timeline=True)
    img = np.asarray(rgb.get_data())[..., :3]
    Image.fromarray(img).save(out / f"{i:04d}.png")
(out / "fps.txt").write_text(f"{args.fps:.2f}\n")
if args.still:
    import shutil
    shutil.copy(out / "0000.png", args.still)
print(f"[capture] {args.frames} frames")
app.close()
