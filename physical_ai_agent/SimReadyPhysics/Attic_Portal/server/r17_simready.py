"""R-17 SimReady Validate.

Read-only validation of the Mission 2 stage and the C-9 containment-pod target
against a SimReady physics requirement list. The validator opens each layer
with pxr, inspects it, and returns findings. It never authors USD, never saves
a layer, never calls renderer.step(), and never runs until the user clicks
"run targets" (the server also requires an explicit userInitiated flag).

RB.MB.001 ("moving body is not simulation-ready") is this project's own rule,
not an NVIDIA one: the pod has no RigidBodyAPI, no MassAPI mass > 0, or no
CollisionAPI geometry. It is `repairable` only when the pod's existing,
already-authored collision proxies can carry an open-top compound collision
that still leaves the Memory Cube an opening (see classify_proxies).
"""

import hashlib
import math
import os
import re
import uuid
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
CUBE_ROLE = "Memory Cube"
MAX_REPORTED_MISSING = 40

RULE_RB_MB_001 = "RB.MB.001"

FIXES_IDLE = "IDLE"
FIXES_APPLYING = "APPLYING"
FIXES_IMPLEMENTED = "IMPLEMENTED"
FIXES_ERROR = "ERROR"

# Proxies whose name says they close the pod are never collision geometry.
REJECTED_PROXY_WORDS = frozenset({"top", "lid", "ceiling", "cap"})
# The Memory Cube must fit through the opening with at least this much room
# (stage units, i.e. cm in this scene) at its best yaw.
MIN_OPENING_SLACK = 1.0


def default_stage_path(session_root: Path) -> Path:
    return Path(os.environ.get("ATTIC_PORTAL_SIMREADY_STAGE") or session_root / "OldAttic_Mission_2.usda")


def default_pod_path(session_root: Path) -> Path:
    return Path(os.environ.get("ATTIC_PORTAL_SIMREADY_POD") or session_root / "C9_ContainmentPod.usda")


def initial_fixes_state() -> dict[str, Any]:
    return {
        "status": FIXES_IDLE,
        "runCount": 0,
        "appliedCount": 0,
        "outlineVisible": False,
        "outputs": [],
        "message": "Fixes not run.",
        "reason": "",
    }


def initial_simready_state(stage_path: Path | str, pod_path: Path | str = "") -> dict[str, Any]:
    return {
        "status": SIMREADY_IDLE,
        "stagePath": str(stage_path),
        "podPath": str(pod_path),
        "runCount": 0,
        "missingCount": 0,
        "missing": [],
        "targets": [],
        "report": None,
        "fixes": initial_fixes_state(),
        "message": "Not run. Click run targets.",
        "error": "",
    }


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _missing(target: str, rule: str, prim: str, detail: str, rule_id: str = "") -> dict[str, str]:
    return {"target": target, "rule": rule, "ruleId": rule_id, "prim": prim, "detail": detail}


def _open(path: Path):
    from pxr import Usd

    if not path.is_file():
        raise FileNotFoundError(f"validation target not found: {path}")
    stage = Usd.Stage.Open(str(path), Usd.Stage.LoadAll)
    if not stage:
        raise RuntimeError(f"could not open validation target: {path}")
    return stage


def _find_by_role(stage, role: str):
    # TraverseAll: Mission 2 authors the pod under `over "Root"`, which a
    # default Traverse() skips.
    for prim in stage.TraverseAll():
        if prim.GetAttribute("mission:role").Get() == role:
            return prim
    return None


def _find_pod(stage):
    return _find_by_role(stage, POD_ROLE)


def memory_cube_size(stage) -> float | None:
    """Edge length of the Memory Cube in stage units, or None when absent."""

    from pxr import Gf, UsdGeom

    cube = _find_by_role(stage, CUBE_ROLE)
    if cube is None:
        return None
    size = cube.GetAttribute("size").Get()
    if size is None:
        return None
    matrix = UsdGeom.XformCache().GetLocalToWorldTransform(cube)
    scale = max(Gf.Vec3d(matrix.GetRow3(i)).GetLength() for i in range(3))
    return float(size) * float(scale or 1.0)


def _split_words(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    return {word for word in re.split(r"[^a-z]+", spaced) if word}


def proxy_name_rejected(name: str) -> bool:
    return bool(_split_words(name) & REJECTED_PROXY_WORDS)


def _box_axes(matrix, size: float):
    """Center, unit axes, and half extents of a Cube prim in the pod's frame."""

    import numpy as np

    rows = np.array([[matrix[r][c] for c in range(3)] for r in range(3)], dtype=float)
    center = np.array([matrix[3][0], matrix[3][1], matrix[3][2]], dtype=float)
    lengths = np.linalg.norm(rows, axis=1)
    return center, rows / lengths[:, None], lengths * (size / 2.0)


def classify_proxies(stage, pod, cube_size: float | None) -> dict[str, Any]:
    """Sort the pod's authored collision proxies into usable and rejected.

    Rejected: named top/lid/ceiling/cap, or non-floor geometry that covers the
    pod's opening. Also measures how much room the Memory Cube has in the
    opening formed by the usable wall proxies, at its best yaw.
    """

    import numpy as np
    from pxr import Usd, UsdGeom

    xcache = UsdGeom.XformCache()
    bcache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render])
    candidates = [
        prim
        for prim in Usd.PrimRange(pod, Usd.PrimAllPrimsPredicate)
        if prim.IsA(UsdGeom.Gprim) and re.search(r"prox(y|ies)", str(prim.GetPath()).lower())
    ]
    rejected: list[dict[str, str]] = []
    bounds: dict[str, Any] = {}
    survivors = []
    for prim in candidates:
        path = str(prim.GetPath())
        if proxy_name_rejected(prim.GetName()):
            rejected.append({"prim": path, "reason": "closes the pod (top/lid/ceiling/cap)"})
            continue
        bounds[path] = bcache.ComputeRelativeBound(prim, pod).ComputeAlignedRange()
        survivors.append(prim)

    # Opening center: middle of the pod's own proxy footprint, in the pod frame.
    if survivors:
        lows = np.array([[*bounds[str(p.GetPath())].GetMin()] for p in survivors])
        highs = np.array([[*bounds[str(p.GetPath())].GetMax()] for p in survivors])
        center_xy = (lows.min(axis=0)[:2] + highs.max(axis=0)[:2]) / 2.0
    else:
        center_xy = np.zeros(2)

    def contains_center(path: str) -> bool:
        low, high = bounds[path].GetMin(), bounds[path].GetMax()
        return low[0] <= center_xy[0] <= high[0] and low[1] <= center_xy[1] <= high[1]

    covering = [p for p in survivors if contains_center(str(p.GetPath()))]
    floor = min(covering, key=lambda p: bounds[str(p.GetPath())].GetMax()[2]) if covering else None
    usable = []
    for prim in survivors:
        path = str(prim.GetPath())
        if contains_center(path) and prim != floor:
            rejected.append({"prim": path, "reason": "covers the pod opening"})
        else:
            usable.append(prim)

    walls = []
    for prim in usable:
        if prim == floor or not prim.IsA(UsdGeom.Cube):
            continue
        matrix = xcache.ComputeRelativeTransform(prim, pod)[0]
        size = prim.GetAttribute("size").Get()
        center, axes, halves = _box_axes(matrix, float(size if size is not None else 2.0))
        horizontal = [i for i in range(3) if abs(axes[i][2]) < 0.1]
        if not horizontal:
            continue
        thick = min(horizontal, key=lambda i: halves[i])
        toward = np.array([*center_xy, 0.0]) - center
        sign = 1.0 if float(np.dot(toward, axes[thick])) >= 0.0 else -1.0
        walls.append((sign * axes[thick], center + sign * halves[thick] * axes[thick]))

    slack, yaw = None, None
    if cube_size is not None and len(walls) >= 3:
        half = cube_size / 2.0
        best = -math.inf
        for degrees in range(0, 90):
            theta = math.radians(degrees)
            c, s = math.cos(theta), math.sin(theta)
            corners = [
                (center_xy[0] + sx * half * c - sy * half * s, center_xy[1] + sx * half * s + sy * half * c)
                for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1))
            ]
            worst = min(
                float(np.dot(np.array([cx, cy, face[2]]) - face, normal))
                for cx, cy in corners
                for normal, face in walls
            )
            if worst > best:
                best, yaw = worst, degrees
        slack = best

    ok = floor is not None and len(walls) >= 3 and slack is not None and slack >= MIN_OPENING_SLACK
    return {
        "floor": str(floor.GetPath()) if floor is not None else "",
        "usable": [str(p.GetPath()) for p in usable],
        "rejected": rejected,
        "wallCount": len(walls),
        "openingSlack": None if slack is None else round(float(slack), 3),
        "openingBestYawDeg": yaw,
        "cubeSize": cube_size,
        "ok": bool(ok),
    }


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
    if _find_pod(stage) is None:
        missing.append(_missing(SIMREADY_TARGET_STAGE, "stage.containmentPod", "/", "containment pod is not present"))
    return _report(SIMREADY_TARGET_STAGE, path, missing)


def validate_pod(path: Path) -> dict[str, Any]:
    from pxr import Usd, UsdGeom, UsdPhysics, UsdShade

    stage = _open(path)
    pod = _find_pod(stage)
    if pod is None:
        return _report(SIMREADY_TARGET_POD, path, [_missing(SIMREADY_TARGET_POD, "pod.role", "/", f"no prim with mission:role == {POD_ROLE!r}")])
    root = str(pod.GetPath())
    missing: list[dict[str, str]] = []
    if not pod.HasAPI(UsdPhysics.RigidBodyAPI):
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.rigidBody", root, "RigidBodyAPI is not applied", RULE_RB_MB_001))
    mass_api = UsdPhysics.MassAPI(pod) if pod.HasAPI(UsdPhysics.MassAPI) else None
    mass = mass_api.GetMassAttr().Get() if mass_api else None
    if not mass or mass <= 0.0:
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.mass", root, "MassAPI with mass > 0 is not authored", RULE_RB_MB_001))
    gprims = [p for p in Usd.PrimRange(pod, Usd.PrimAllPrimsPredicate) if p.IsA(UsdGeom.Gprim)]
    colliders = [p for p in gprims if p.HasAPI(UsdPhysics.CollisionAPI)]
    if not colliders:
        missing.append(_missing(SIMREADY_TARGET_POD, "pod.collision", root, "no geometry has CollisionAPI", RULE_RB_MB_001))
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
    """Validate both targets. Raises on open failure; authors nothing.

    The returned `report` stamps the exact sources (paths and SHA-256) the
    findings describe, so a later fix can prove the report is still current.
    """

    stage_path, pod_path = Path(stage_path), Path(pod_path)
    targets = [validate_stage(stage_path), validate_pod(pod_path)]
    missing = [item for target in targets for item in target["missing"]]
    rule_ids = sorted({item["ruleId"] for item in missing if item["ruleId"]})

    proxies: dict[str, Any] | None = None
    if RULE_RB_MB_001 in rule_ids:
        pod_stage = _open(pod_path)
        proxies = classify_proxies(pod_stage, _find_pod(pod_stage), memory_cube_size(_open(stage_path)))
    report = {
        "reportId": uuid.uuid4().hex,
        "stagePath": str(stage_path),
        "podPath": str(pod_path),
        "sha256": {"stage": sha256_file(stage_path), "pod": sha256_file(pod_path)},
        "ruleIds": rule_ids,
        "repairable": bool(proxies and proxies["ok"]),
        "proxies": proxies,
    }
    return {
        "targets": [{k: v for k, v in t.items() if k != "missing"} for t in targets],
        "missingCount": len(missing),
        "missing": missing[:MAX_REPORTED_MISSING],
        "report": report,
    }
