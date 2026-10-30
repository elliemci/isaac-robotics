"""In-simulator frame recorder, run via `isaac-sim.sh --no-window --exec`.

Records an RGB camera while an external ROS 2 script (the NVIDIA lesson's
workshop_learning_script_final.py) loads worlds and drives the robots through
the simulation-interfaces services. The camera is authored on the session layer
and re-created whenever the stage is replaced (load_world/unload_world), so
nothing is saved to any scene file.

Env: CAP_OUT (frame dir), CAP_EYE "x y z", CAP_LOOKAT "x y z", CAP_FPS (default 10),
CAP_FLAG (file path; frames are only written while this file exists).
Frames are taken every 1/CAP_FPS of *simulation* time (the headless sim runs well below
real time while rendering, so wall-clock sampling would give a sped-up, sparse video).
"""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import time
import traceback

import carb
import omni.kit.app
import omni.replicator.core as rep
import omni.timeline
import omni.usd
from PIL import Image
from pxr import Gf, Usd, UsdGeom

OUT = Path(os.environ["CAP_OUT"]); OUT.mkdir(parents=True, exist_ok=True)
EYE = Gf.Vec3d(*map(float, os.environ.get("CAP_EYE", "8 -8 6").split()))
LOOK = Gf.Vec3d(*map(float, os.environ.get("CAP_LOOKAT", "0 0 0.5").split()))
PERIOD = 1.0 / float(os.environ.get("CAP_FPS", "10"))
FLAG = Path(os.environ.get("CAP_FLAG", "/tmp/cap.flag"))
CAM = "/CaptureCamera"

POOL = ThreadPoolExecutor(2)
TL = omni.timeline.get_timeline_interface()
state = {"stage_id": None, "ann": None, "last": -1e9, "n": len(list(OUT.glob("*.png"))), "t0": None}


def _setup(stage):
    stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
    cam = UsdGeom.Camera.Define(stage, CAM)
    cam.GetFocalLengthAttr().Set(20)
    xf = UsdGeom.Xformable(cam)
    ops = xf.GetOrderedXformOps()
    op = ops[0] if ops else xf.AddTransformOp()
    op.Set(Gf.Matrix4d().SetLookAt(EYE, LOOK, Gf.Vec3d(0, 0, 1)).GetInverse())
    if state.get("rp_stage") != id(stage):
        state["rp"] = rep.create.render_product(CAM, (1280, 720))
        state["rp_stage"] = id(stage)
        state["ann"] = None
    if state["ann"] is None:
        ann = rep.AnnotatorRegistry.get_annotator("rgb")
        ann.attach([state["rp"]])
        state["ann"] = ann
    carb.log_warn(f"[recorder] camera set up on stage {id(stage)}")


def _on_update(_e):
    ctx = omni.usd.get_context()
    stage = ctx.get_stage()
    if stage is None:
        return
    if time.time() < state.get("retry", 0):
        return
    if state["stage_id"] != id(stage) or not stage.GetPrimAtPath(CAM):
        if state["stage_id"] != id(stage):
            state["retry"] = time.time() + 4.0  # let a freshly loaded stage settle
            state["stage_id"] = id(stage)
            return
        try:
            _setup(stage)
        except Exception:  # stage still loading
            carb.log_warn(f"[recorder] setup deferred: {traceback.format_exc()}")
            state["stage_id"] = None
            state["retry"] = time.time() + 2.0
        return
    if not FLAG.exists() or not TL.is_playing():
        return
    now = TL.get_current_time()
    if now < state["last"]:  # timeline was reset
        state["last"] = -1e9
    if now - state["last"] < PERIOD:
        return
    data = state["ann"].get_data()
    if data is None or getattr(data, "size", 0) == 0:
        return
    state["last"] = now
    path = OUT / f"{state['n']:05d}.png"
    POOL.submit(lambda a=data[..., :3].copy(): Image.fromarray(a).save(path, compress_level=1))
    state["n"] += 1


_sub = omni.kit.app.get_app().get_post_update_event_stream().create_subscription_to_pop(_on_update, name="h1-recorder")
carb.log_warn("[recorder] ready")
