#!/usr/bin/env python3
"""Independently verify the R-17 LiDAR nonvisual material defaults.

Recomputes the unlabeled Material set from the protected scene layers
(read-only), then proves R17_Lidar.usda authors both supported prefixes on
exactly that set, touches no Mesh prims, adds no physics schemas, and that the
server-published lidarNonvisualMaterialCount matches.

Run with a Python that imports pxr, e.g. ../Attic_Portal_Prework/isaac_python.sh.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdShade

APP_ROOT = Path(__file__).resolve().parents[1]
SESSION_ROOT = APP_ROOT.parent
PROTECTED_LAYERS = [
    SESSION_ROOT / "Attic_NVIDIA" / "OldAttic_Mission.usda",
    SESSION_ROOT / "Attic_NVIDIA" / "Attic_NVIDIA.usd",
]
LIDAR_LAYER = Path(os.environ.get("LIDAR_LAYER", str(APP_ROOT / "usd" / "R17_Lidar.usda")))
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8082/state.json")
EXPECTED_VALUES = {
    "omni:simready:nonvisual:base": "none",
    "omni:simready:nonvisual:coating": "none",
    "omni:simready:nonvisual:attributes": ["none"],
    "inputs:nonvisual:base": "none",
    "inputs:nonvisual:coating": "none",
    "inputs:nonvisual:attributes": "none",
}
NONVISUAL_PREFIXES = ("omni:simready:nonvisual:", "inputs:nonvisual:")


def open_protected_stage() -> Usd.Stage:
    root = Sdf.Layer.CreateAnonymous("r17-lidar-material-check.usda")
    root.subLayerPaths = [str(path.resolve()) for path in PROTECTED_LAYERS]
    return Usd.Stage.Open(root)


def main() -> None:
    protected = open_protected_stage()
    materials = [p for p in protected.Traverse() if p.IsA(UsdShade.Material)]
    source_labeled = sorted(
        str(p.GetPath())
        for p in materials
        if p.GetAttribute("omni:simready:nonvisual:base") or p.GetAttribute("inputs:nonvisual:base")
    )
    expected = sorted(str(p.GetPath()) for p in materials if str(p.GetPath()) not in source_labeled)

    layer = Sdf.Layer.FindOrOpen(str(LIDAR_LAYER))
    if layer is None:
        raise AssertionError({"missingLidarLayer": str(LIDAR_LAYER)})
    authored: dict[str, dict[str, object]] = {}

    def visit(path: Sdf.Path) -> None:
        if not path.IsPropertyPath():
            return
        name = path.name
        if name.startswith(NONVISUAL_PREFIXES):
            spec = layer.GetAttributeAtPath(path)
            value = spec.default if spec is not None else None
            authored.setdefault(str(path.GetPrimPath()), {})[name] = list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else value

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)

    authored_paths = sorted(authored)
    problems: dict[str, object] = {}
    missing = sorted(set(expected) - set(authored_paths))
    extra = sorted(set(authored_paths) - set(expected))
    if missing:
        problems["unlabeledMaterialsNotAuthored"] = missing
    if extra:
        problems["authoredOutsideUnlabeledSet"] = extra
    overridden_source = sorted(set(authored_paths) & set(source_labeled))
    if overridden_source:
        problems["overridesSourceLabels"] = overridden_source

    bad_values = {}
    for path in authored_paths:
        attrs = authored[path]
        diff = {k: attrs.get(k) for k, v in EXPECTED_VALUES.items() if attrs.get(k) != v}
        if diff:
            bad_values[path] = diff
    if bad_values:
        problems["wrongOrMissingPrefixValues"] = bad_values

    non_material_targets = []
    for path in authored_paths:
        prim = protected.GetPrimAtPath(path)
        if not prim or not prim.IsA(UsdShade.Material) or prim.IsA(UsdGeom.Mesh):
            non_material_targets.append(path)
    if non_material_targets:
        problems["labelsOnNonMaterialPrims"] = non_material_targets

    layer_text = LIDAR_LAYER.read_text(encoding="utf-8")
    physics = [token for token in ("PhysicsCollisionAPI", "PhysicsRigidBodyAPI", "PhysicsMassAPI", "PhysxCollisionAPI", "physics:") if token in layer_text]
    if physics:
        problems["physicsSchemasInLidarLayer"] = physics

    state_count = None
    try:
        with urllib.request.urlopen(STATE_URL, timeout=3) as response:
            state = json.load(response)
        state_count = (state.get("r17") or {}).get("lidarNonvisualMaterialCount")
        if state_count is None:
            state_count = (state.get("lidar") or {}).get("nonvisualMaterialCount")
    except Exception as exc:  # noqa: BLE001 - report, don't mask
        problems["stateUnavailable"] = str(exc)
    if state_count is not None and state_count != len(expected):
        problems["publishedCountMismatch"] = {"published": state_count, "expected": len(expected)}
    if not expected:
        problems["noUnlabeledMaterials"] = True

    result = {
        "lidarLayer": str(LIDAR_LAYER),
        "protectedMaterialCount": len(materials),
        "sourceLabeledMaterialCount": len(source_labeled),
        "unlabeledMaterialCount": len(expected),
        "authoredMaterialCount": len(authored_paths),
        "publishedLidarNonvisualMaterialCount": state_count,
        "prefixes": list(NONVISUAL_PREFIXES),
        "pass": not problems,
        "problems": problems,
    }
    print(json.dumps(result, indent=2))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
