#!/usr/bin/env python3
"""GPU-free contract check for the Mission 4 physical stage.

Builds into a temp directory from a temp copy of OldAttic_Mission_3_Fixed.usda
and reads the contract with pxr. No ovphysx, no renderer, no real outputs, no
simulation. Run with the portal Python (needs pxr).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "server"))

from pxr import Gf, Usd, UsdGeom, UsdPhysics  # noqa: E402

import r17_physics as phys  # noqa: E402
import r17_physics_stage as stage_mod  # noqa: E402
import r17_simready as sr  # noqa: E402

SESSION = APP_ROOT.parent
SOURCES = [SESSION / "OldAttic_Mission_3_Fixed.usda", SESSION / "OldAttic_Mission_2.usda", SESSION / "C9_ContainmentPod.usda", SESSION / "C9_ContainmentPod_Mission_3_Fixed.usda"]


def check(condition: bool, label: str, detail=None) -> None:
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f" -> {detail}"))
    if not condition:
        raise SystemExit(1)


def build(work: Path, name: str) -> tuple[Path, dict]:
    folder = work / name
    folder.mkdir(parents=True)
    shutil.copy(SOURCES[0], folder / SOURCES[0].name)
    result = stage_mod.build_mission4_stage(folder, outlines_layer=folder / "outlines_check.usda")
    return folder, result


def main() -> None:
    before = {p.name: sr.sha256_file(p) for p in SOURCES if p.exists()}
    work = Path(tempfile.mkdtemp(prefix="mission4_contract_"))
    try:
        folder, result = build(work, "base")
        c = result["contract"]
        expected = {
            "rootType": "Xform", "upAxis": "Z", "metersPerUnit": 0.01, "sceneCount": 1, "sceneEnabled": True,
            "rigidBodyCount": 2, "colliderCount": 11, "cubeDynamic": True, "podKinematic": True, "podOpenTop": True, "groundStatic": True,
        }
        for key, value in expected.items():
            check(c[key] == value, f"contract {key} == {value!r}", c[key])
        check((c["podMinimumOpeningRadius"] or 0) >= 32, "podMinimumOpeningRadius >= 32", c["podMinimumOpeningRadius"])
        check(stage_mod.contract_failures(c) == [], "no contract failures")

        # State at startup is read-only and READY_TO_RUN; nothing is playing.
        state = phys.initial_physics_state(folder / stage_mod.STAGE_NAME)
        want = {"status": "READY_TO_RUN" if state["runtimeInstalled"] else "NOT_READY", "playing": False, "stepCount": 0, "elapsedTime": 0.0,
                "sceneEnabled": True, "sceneCount": 1, "rigidBodyCount": 2, "colliderCount": 11, "bridgeReady": False}
        for key, value in want.items():
            check(state[key] == value, f"startup state {key} == {value!r}", state[key])

        # Authored layout: eleven CollisionAPI, no top/lid/ceiling/cap collider.
        stage = Usd.Stage.Open(str(folder / stage_mod.STAGE_NAME))
        names = [p.GetName() for p in stage.TraverseAll() if p.HasAPI(UsdPhysics.CollisionAPI)]
        check(len(names) == 11 and not any(sr.proxy_name_rejected(n) for n in names), "11 colliders, none named top/lid/ceiling/cap", names)
        check(stage.GetPrimAtPath(stage_mod.GROUND_PATH).GetAttribute("visibility").Get() == "invisible", "ground collider is not rendered")
        authored = Usd.Stage.Open(str(folder / stage_mod.AUTHORED_SCENE_NAME), Usd.Stage.LoadNone)
        check(not authored.GetRootLayer().subLayerPaths, "sanitized scene has no dead sublayer")

        # Outlines: three distinct groups, 11 + 2 + 1 curves.
        outline = Usd.Stage.Open(str(folder / "outlines_check.usda"))
        kinds = [p.GetName().split("_")[0] for p in outline.TraverseAll() if p.GetTypeName() == "BasisCurves"]
        check(sorted({k for k in kinds}) == ["CollisionAPI", "PhysicsScene", "RigidBodyAPI"] and kinds.count("CollisionAPI") == 11, "outlines: CollisionAPI x11, RigidBodyAPI, PhysicsScene", kinds)

        # A lid-style collider must fail podOpenTop.
        lid_folder, _ = build(work, "lid")
        ps = Usd.Stage.Open(str(lid_folder / stage_mod.PHYSICS_LAYER_NAME))
        lid = UsdGeom.Cube.Define(ps, f"{stage_mod.POD_PATH}/CollisionProxies/LidProxy")
        lid.AddTranslateOp().Set(Gf.Vec3d(0, 0, 60))
        lid.AddScaleOp().Set(Gf.Vec3d(30, 30, 1))
        UsdPhysics.CollisionAPI.Apply(lid.GetPrim())
        ps.GetRootLayer().Save()
        lc = stage_mod.physical_stage_contract(lid_folder / stage_mod.STAGE_NAME)
        check(lc["podOpenTop"] is False and "podOpenTop" in stage_mod.contract_failures(lc), "lid collider fails podOpenTop")

        # An opening below 32 fails the radius requirement.
        narrow_folder, _ = build(work, "narrow")
        ps = Usd.Stage.Open(str(narrow_folder / stage_mod.PHYSICS_LAYER_NAME))
        for i in range(8):
            wall = ps.GetPrimAtPath(f"{stage_mod.POD_PATH}/CollisionProxies/WallProxy_{i:02d}")
            op = wall.GetAttribute("xformOp:translate")
            v = op.Get()
            op.Set(Gf.Vec3d(v[0] * 0.8, v[1] * 0.8, v[2]))
        ps.GetRootLayer().Save()
        nc = stage_mod.physical_stage_contract(narrow_folder / stage_mod.STAGE_NAME)
        check((nc["podMinimumOpeningRadius"] or 0) < 32 and "podMinimumOpeningRadius" in stage_mod.contract_failures(nc), "opening < 32 fails", nc["podMinimumOpeningRadius"])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    check({p.name: sr.sha256_file(p) for p in SOURCES if p.exists()} == before, "source scenes unchanged")
    print("ALL PASS")


if __name__ == "__main__":
    main()
