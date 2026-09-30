"""R-17 SimReady Validate.

Read-only validation of the Mission 2 stage and the C-9 containment-pod target
against a SimReady physics requirement list. The validator opens each layer
with pxr, inspects it, and returns findings. It never authors USD, never saves
a layer, never calls renderer.step(), and never runs until the user clicks
"run targets" (the server also requires an explicit userInitiated flag).
"""

import os
from pathlib import Path
from typing import Any

SIMREADY_IDLE = "IDLE"
SIMREADY_RUNNING = "RUNNING"
SIMREADY_NOT_READY = "NOT_SIMREADY"
SIMREADY_PASS = "PASS"
SIMREADY_ERROR = "ERROR"

SIMREADY_TARGET_STAGE = "mission_2_stage"
SIMREADY_TARGET_POD = "containment_pod"
POD_ROLE = "Memory Cube Containment Pod"
MAX_REPORTED_MISSING = 40


def default_stage_path(session_root: Path) -> Path:
    return Path(os.environ.get("ATTIC_PORTAL_SIMREADY_STAGE") or session_root / "OldAttic_Mission_2.usda")


def default_pod_path(session_root: Path) -> Path:
    return Path(os.environ.get("ATTIC_PORTAL_SIMREADY_POD") or session_root / "C9_ContainmentPod.usda")


def initial_simready_state(stage_path: Path | str, pod_path: Path | str = "") -> dict[str, Any]:
    return {
        "status": SIMREADY_IDLE,
        "stagePath": str(stage_path),
        "podPath": str(pod_path),
        "runCount": 0,
        "missingCount": 0,
        "missing": [],
        "targets": [],
        "message": "Not run. Click run targets.",
        "error": "",
    }


def _missing(target: str, rule: str, prim: str, detail: str) -> dict[str, str]:
    return {"target": target, "rule": rule, "prim": prim, "detail": detail}


def _open(path: Path):
    from pxr import Usd

    if not path.is_file():
        raise FileNotFoundError(f"validation target not found: {path}")
    stage = Usd.Stage.Open(str(path), Usd.Stage.LoadAll)
    if not stage:
        raise RuntimeError(f"could not open validation target: {path}")
    return stage


def validate_stage(path: Path) -> dict[str, Any]:
    from pxr import UsdGeom, UsdPhysics

    stage = _open(path)
    missing: list[dict[str, str]] = []
    if UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z:
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.upAxis", "/", "upAxis must be Z"))
    if not stage.HasAuthoredMetadata("metersPerUnit"):
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.metersPerUnit", "/", "metersPerUnit is not authored"))
    if not stage.GetDefaultPrim():
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.defaultPrim", "/", "defaultPrim is not set"))
    if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.TraverseAll()):
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.physicsScene", "/", "no UsdPhysics.Scene prim"))
    pod = _find_pod(stage)
    if pod is None:
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.containmentPod", "/", "containment pod is not present"))
    return _report(SIMREADY_TARGET_STAGE, path, missing)


def _find_pod(stage):
    # TraverseAll: Mission 2 authors the pod under `over "Root"`, which a
    # default Traverse() skips.
    for prim in stage.TraverseAll():
        if prim.GetAttribute("mission:role").Get() == POD_ROLE:
            return prim
    return None


def validate_pod(path: Path) -> dict[str, Any]:
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

    stage = _open(path)
    pod = _find_pod(stage)
    if pod is None:
        return _report(SIMREADY_TARGET_POD, path, [_missing(SIMREADY_TARGET_POD, "pod.role", "/", f"no prim with mission:role == {POD_ROLE!r}")])
    root = str(pod.GetPath())
    missing: list[dict[str, str]] = []
    if not pod.HasAPI(UsdPhysics.RigidBodyAPI):
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.rigidBody", root, "RigidBodyAPI is not applied"))
    mass_api = UsdPhysics.MassAPI(pod) if pod.HasAPI(UsdPhysics.MassAPI) else None
    mass = mass_api.GetMassAttr().Get() if mass_api else None
    if not mass or mass <= 0.0:
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.mass", root, "MassAPI with mass > 0 is not authored"))
    meshes = [p for p in Usd.PrimRange(pod, Usd.PrimAllPrimsPredicate) if p.IsA(UsdGeom.Mesh) or p.IsA(UsdGeom.Gprim)]
    colliders = [p for p in meshes if p.HasAPI(UsdPhysics.CollisionAPI)]
    if not colliders:
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.collision", root, "no geometry has CollisionAPI"))
    for prim in colliders:
        if prim.IsA(UsdGeom.Mesh) and not prim.HasAPI(UsdPhysics.MeshCollisionAPI):
            missing.append(_missing(SIMREADY_TARGET_POD, "pod.collisionApproximation", str(prim.GetPath()), "MeshCollisionAPI approximation is not authored"))
        bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics")[0]
        if not bound or not bound.GetPrim().HasAPI(UsdPhysics.MaterialAPI):
            missing.append(_missing(SIMREADY_TARGET_POD, "pod.physicsMaterial", str(prim.GetPath()), "no physics material bound"))
    return _report(SIMREADY_TARGET_POD, path, missing)


def _report(target: str, path: Path, missing: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "target": target,
        "path": str(path),
        "status": SIMREADY_NOT_READY if missing else SIMREADY_PASS,
        "missingCount": len(missing),
        "missing": missing,
    }


def run_simready_validation(stage_path: Path | str, pod_path: Path | str) -> dict[str, Any]:
    """Validate both targets. Raises on open failure; authors nothing."""

    targets = [validate_stage(Path(stage_path)), validate_pod(Path(pod_path))]
    missing = [item for target in targets for item in target["missing"]]
    return {
        "targets": [{k: v for k, v in t.items() if k != "missing"} for t in targets],
        "missingCount": len(missing),
        "missing": missing[:MAX_REPORTED_MISSING],
    }
