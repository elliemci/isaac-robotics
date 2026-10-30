"""Headless stills of Isaac Sim scenes (sub-projects A and B).

Opens a USD without saving it, authors a capture camera and optional light on the
session layer, and writes one PNG per --shot. Run with Isaac Lab's python:
  isaaclab.sh -p docs/capture/capture_scene_stills.py --usd <file> --out <dir> \
      --shot name=cam:/World/Camera1 --shot name=look:ex,ey,ez:lx,ly,lz \
      --shot name=prim:/World/robot:2.5:35:20     (frame a prim: distance factor, azimuth, elevation)
  --list prints prim bounds instead of rendering. Remote NVIDIA assets (S3) are
  loaded by the scene itself, so an internet connection is needed for those scenes.
"""
import argparse
import math
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--usd", required=True)
p.add_argument("--out", required=True)
p.add_argument("--shot", action="append", default=[])
p.add_argument("--list", action="store_true")
p.add_argument("--light", type=float, default=0.0, help="dome light intensity to add (0 = none)")
p.add_argument("--wait", type=int, default=400, help="app updates to wait for streaming/loading")
p.add_argument("--play", type=int, default=0, help="play the timeline for this many updates before shooting")
args = p.parse_args()

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "width": 1280, "height": 720})

import numpy as np
import omni.replicator.core as rep
import omni.timeline
import omni.usd
from PIL import Image
from pxr import Gf, Usd, UsdGeom, UsdLux

ctx = omni.usd.get_context()
ctx.open_stage(args.usd)
for i in range(args.wait):
    app.update()
    if i > 20 and i % 20 == 0 and ctx.get_stage_loading_status()[2] == 0 and i > args.wait // 2:
        break
stage = ctx.get_stage()
stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])


def bounds(path):
    prim = stage.GetPrimAtPath(path)
    return cache.ComputeWorldBound(prim).ComputeAlignedRange()


LOG = Path(args.out); LOG.mkdir(parents=True, exist_ok=True)


def log(msg):
    with open(LOG / "log.txt", "a") as f:  # Kit swallows stdout
        f.write(msg + "\n")


if args.list:
    for pr in stage.GetPseudoRoot().GetChildren():
        for c in [pr] + list(pr.GetChildren()):
            b = bounds(c.GetPath())
            if not b.IsEmpty():
                log(f"[list] {c.GetPath()} {c.GetTypeName()} min={tuple(round(v, 2) for v in b.GetMin())} max={tuple(round(v, 2) for v in b.GetMax())}")
    app.close()
    raise SystemExit

if args.light:
    UsdLux.DomeLight.Define(stage, "/Capture/Dome").CreateIntensityAttr(args.light)
cam = UsdGeom.Camera.Define(stage, "/Capture/Camera")
cam.GetFocalLengthAttr().Set(24)
xf = UsdGeom.Xformable(cam).AddTransformOp()
if args.play:
    omni.timeline.get_timeline_interface().play()
    for _ in range(args.play):
        app.update()

out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
rp_cache = {}
ann_cache = {}


def shoot(name, cam_path):
    if cam_path not in rp_cache:
        rp_cache[cam_path] = rep.create.render_product(cam_path, (1280, 720))
        a = rep.AnnotatorRegistry.get_annotator("rgb"); a.attach([rp_cache[cam_path]]); ann_cache[cam_path] = a
    for _ in range(3):
        rep.orchestrator.step(rt_subframes=24, delta_time=0.0, pause_timeline=False)
    img = np.asarray(ann_cache[cam_path].get_data())[..., :3]
    Image.fromarray(img).save(out / f"{name}.png")
    log(f"[capture] {name}")


for spec in args.shot:
    name, kind, rest = (spec.split("=", 1)[0],) + tuple(spec.split("=", 1)[1].split(":", 1))
    if kind == "cam":
        shoot(name, rest)
    elif kind == "look":
        e, l = rest.split(":")
        eye = Gf.Vec3d(*map(float, e.split(","))); look = Gf.Vec3d(*map(float, l.split(",")))
        xf.Set(Gf.Matrix4d().SetLookAt(eye, look, Gf.Vec3d(0, 0, 1)).GetInverse())
        shoot(name, "/Capture/Camera")
    elif kind == "prim":
        path, fac, az, el = rest.rsplit(":", 3)
        b = bounds(path); c = (b.GetMin() + b.GetMax()) / 2; r = max(b.GetSize()) * float(fac)
        a, e = math.radians(float(az)), math.radians(float(el))
        eye = Gf.Vec3d(c[0] + r * math.cos(e) * math.cos(a), c[1] + r * math.cos(e) * math.sin(a), c[2] + r * math.sin(e))
        xf.Set(Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(*c), Gf.Vec3d(0, 0, 1)).GetInverse())
        shoot(name, "/Capture/Camera")
app.close()
