"""R-17 Mission 4 physical stage.

Builds the clean physical-stage composite from the repaired Mission 3 scene and
reads back its physics contract. pxr only: nothing here imports ovphysx,
creates a PhysX instance, or steps a simulation. The sources are only read.

    OldAttic_Mission_3_Fixed.usda  (read-only source)
      -> Mission4_AuthoredScene.usda   sanitized scene: Xform root, no dead
                                        sublayer, no stray or stale physics
      -> Mission4_PhysicsLayer.usda    dedicated physics opinions
      -> OldAttic_Mission_4_Physics.usda   root layer composing the two

The outputs are regenerated build artifacts, never backups of a source.

Usage:  python r17_physics_stage.py build [--session-root DIR]
"""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SOURCE_NAME = "OldAttic_Mission_3_Fixed.usda"
AUTHORED_SCENE_NAME = "Mission4_AuthoredScene.usda"
PHYSICS_LAYER_NAME = "Mission4_PhysicsLayer.usda"
STAGE_NAME = "OldAttic_Mission_4_Physics.usda"

ROOT_PATH = "/Root"
SCENE_PATH = "/Root/PhysicsScene"
CUBE_PATH = "/Root/Workshop/Cube"
POD_PATH = "/Root/Workshop/C9_ContainmentPod"
GROUND_PATH = "/Root/PhysicsGround"
MATERIAL_PATH = "/Root/Workshop/Looks/Mission4PhysicsMaterial"

GRAVITY_DIRECTION = (0.0, 0.0, -1.0)
GRAVITY_MAGNITUDE = 981.0  # cm/s^2 at 0.01 m per unit
CUBE_MASS_KG = 1.0
POD_MASS_KG = 2.0
STATIC_FRICTION, DYNAMIC_FRICTION, RESTITUTION = 0.6, 0.5, 0.1

# Open-top pod colliders: octagon of 8 wall proxies plus a floor proxy.
POD_INNER_RADIUS = 34.0  # opening radius; the contract requires >= MIN_OPENING_RADIUS
MIN_OPENING_RADIUS = 32.0
WALL_HALF_THICKNESS = 3.0
WALL_HALF_HEIGHT = 27.0
WALL_CENTER_Z = 31.0
WALL_COUNT = 8
FLOOR_HEIGHT = 4.0

# Static ground collider: top surface at the chest height the pod sits on.
GROUND_TOP_Z = 16.0
GROUND_HALF_EXTENT = 150.0
GROUND_HALF_THICKNESS = 5.0
GROUND_CENTER_XY = (-640.0, -1125.0)

EXPECTED_RIGID_BODIES = 2
EXPECTED_COLLIDERS = 11


def default_paths(session_root: Path) -> dict[str, Path]:
    return {
        "source": session_root / SOURCE_NAME,
        "authored": session_root / AUTHORED_SCENE_NAME,
        "physics": session_root / PHYSICS_LAYER_NAME,
        "stage": session_root / STAGE_NAME,
    }


def _sanitize_scene(source: Path, out: Path) -> None:
    """Export the source and strip what a clean physical stage must not carry."""

    from pxr import Sdf, Usd, UsdPhysics

    layer = Sdf.Layer.FindOrOpen(str(source))
    if layer is None:
        raise FileNotFoundError(f"cannot open {source}")
    if not layer.Export(str(out)):
        raise RuntimeError(f"cannot write {out}")
    stage = Usd.Stage.Open(str(out), Usd.Stage.LoadNone)
    root_layer = stage.GetRootLayer()
    root_layer.subLayerPaths.clear()  # the macOS base path does not exist here
    root_spec = root_layer.GetPrimAtPath(ROOT_PATH)
    if root_spec is None:
        raise ValueError(f"{source} has no {ROOT_PATH}")
    root_spec.typeName = "Xform"
    root_spec.specifier = Sdf.SpecifierDef
    root_layer.defaultPrim = "Root"
    # The Mission 3 scene carried a root-level scene; the physics layer owns one.
    stray = root_layer.GetPrimAtPath("/PhysicsScene")
    if stray is not None:
        del root_layer.rootPrims["PhysicsScene"]
    stage = Usd.Stage.Open(str(out), Usd.Stage.LoadAll)
    # Mission 3 physics on the pod is re-authored in the dedicated layer.
    for path in (POD_PATH, CUBE_PATH):
        prim = stage.GetPrimAtPath(path)
        if not prim:
            continue
        for p in [prim, *[c for c in Usd.PrimRange(prim) if c != prim]]:
            for api in (UsdPhysics.RigidBodyAPI, UsdPhysics.MassAPI, UsdPhysics.CollisionAPI, UsdPhysics.MeshCollisionAPI):
                if p.HasAPI(api):
                    p.RemoveAPI(api)
            for name in list(p.GetPropertyNames()):
                if name.startswith("physics:") or name == "material:binding:physics":
                    p.RemoveProperty(name)
    old_material = stage.GetPrimAtPath(f"{POD_PATH}/Looks/ContainmentPhysicsMaterial")
    if old_material:
        stage.RemovePrim(old_material.GetPath())
    # Authored pod notes still claim the physics is unauthored or a candidate.
    pod = stage.GetPrimAtPath(POD_PATH)
    if pod:
        pod.GetAttribute("mission:status").Set("SIMREADY PHYSICS LAYER: Mission4_PhysicsLayer.usda")
        pod.GetAttribute("mission:collisionRepresentation").Set("Open-top compound proxies; physics authored in Mission4_PhysicsLayer.usda")
    stage.GetRootLayer().Save()


def _wall_geometry(index: int) -> tuple[tuple[float, float, float], float, tuple[float, float, float]]:
    """(translate, rotateZ degrees, scale) of wall proxy `index` for POD_INNER_RADIUS."""

    angle = 360.0 * index / WALL_COUNT
    center = POD_INNER_RADIUS + WALL_HALF_THICKNESS
    half_width = center * math.tan(math.pi / WALL_COUNT)
    rad = math.radians(angle)
    return (center * math.cos(rad), center * math.sin(rad), WALL_CENTER_Z), angle, (WALL_HALF_THICKNESS, half_width, WALL_HALF_HEIGHT)


def _author_physics_layer(out: Path) -> None:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

    stage = Usd.Stage.CreateNew(str(out))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    stage.GetRootLayer().documentation = "Mission 4 physics opinions: scene, dynamic cube, kinematic open-top pod, static ground."

    scene = UsdPhysics.Scene.Define(stage, SCENE_PATH)
    scene.CreateGravityDirectionAttr(Gf.Vec3f(*GRAVITY_DIRECTION))
    scene.CreateGravityMagnitudeAttr(GRAVITY_MAGNITUDE)

    material = UsdShade.Material.Define(stage, MATERIAL_PATH)
    physics_material = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics_material.CreateStaticFrictionAttr(STATIC_FRICTION)
    physics_material.CreateDynamicFrictionAttr(DYNAMIC_FRICTION)
    physics_material.CreateRestitutionAttr(RESTITUTION)

    def bind(prim) -> None:
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, UsdShade.Tokens.weakerThanDescendants, "physics")

    cube = stage.OverridePrim(CUBE_PATH)
    UsdPhysics.RigidBodyAPI.Apply(cube).CreateRigidBodyEnabledAttr(True)
    UsdPhysics.MassAPI.Apply(cube).CreateMassAttr(CUBE_MASS_KG)
    UsdPhysics.CollisionAPI.Apply(cube).CreateCollisionEnabledAttr(True)
    bind(cube)

    pod = stage.OverridePrim(POD_PATH)
    body = UsdPhysics.RigidBodyAPI.Apply(pod)
    body.CreateRigidBodyEnabledAttr(True)
    body.CreateKinematicEnabledAttr(True)  # stationary: never moved by the simulation
    UsdPhysics.MassAPI.Apply(pod).CreateMassAttr(POD_MASS_KG)

    proxies = f"{POD_PATH}/CollisionProxies"
    floor = stage.OverridePrim(f"{proxies}/FloorProxy")
    # The floor must reach the outer wall face so nothing slips between them.
    UsdGeom.Cylinder(floor).CreateRadiusAttr(POD_INNER_RADIUS + 2 * WALL_HALF_THICKNESS)
    for index in range(WALL_COUNT):
        wall = stage.OverridePrim(f"{proxies}/WallProxy_{index:02d}")
        translate, _angle, scale = _wall_geometry(index)
        xform = UsdGeom.Xformable(wall)
        xform.ClearXformOpOrder()
        xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*translate))
        if index:
            xform.AddRotateZOp().Set(float(_angle))
        xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*scale))
    for prim in [floor, *[stage.GetPrimAtPath(f"{proxies}/WallProxy_{i:02d}") for i in range(WALL_COUNT)]]:
        UsdPhysics.CollisionAPI.Apply(prim).CreateCollisionEnabledAttr(True)
        bind(prim)

    ground = UsdGeom.Cube.Define(stage, GROUND_PATH)
    xform = UsdGeom.Xformable(ground)
    xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(GROUND_CENTER_XY[0], GROUND_CENTER_XY[1], GROUND_TOP_Z - GROUND_HALF_THICKNESS))
    xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(GROUND_HALF_EXTENT, GROUND_HALF_EXTENT, GROUND_HALF_THICKNESS))
    ground.CreateVisibilityAttr(UsdGeom.Tokens.invisible)
    UsdPhysics.CollisionAPI.Apply(ground.GetPrim()).CreateCollisionEnabledAttr(True)
    bind(ground.GetPrim())
    stage.GetRootLayer().Save()


def _author_stage_root(out: Path, physics_name: str, authored_name: str) -> None:
    out.write_text(
        f'''#usda 1.0
(
    customLayerData = {{
        string mission = "Operation Attic Containment"
        string note = "Mission 4 physical stage: physics layer over the sanitized Mission 3 scene. Generated; do not edit."
    }}
    defaultPrim = "Root"
    metersPerUnit = 0.01
    subLayers = [
        @./{physics_name}@,
        @./{authored_name}@
    ]
    upAxis = "Z"
)
''',
        encoding="utf-8",
    )


def build_mission4_stage(session_root: Path, outlines_layer: Path | None = None) -> dict[str, Any]:
    """Write the three Mission 4 layers (and the outlines layer when asked).

    Reads OldAttic_Mission_3_Fixed.usda; refuses to overwrite it or any other
    scene it was not generated from. Returns the contract of the result.
    """

    paths = default_paths(Path(session_root))
    if not paths["source"].is_file():
        raise FileNotFoundError(f"Mission 3 fixed scene not found: {paths['source']}")
    _sanitize_scene(paths["source"], paths["authored"])
    _author_physics_layer(paths["physics"])
    _author_stage_root(paths["stage"], PHYSICS_LAYER_NAME, AUTHORED_SCENE_NAME)
    contract = physical_stage_contract(paths["stage"])
    if outlines_layer is not None:
        from r17_physics_outlines import collect_mission4_outline_groups, write_mission4_outlines_layer

        write_mission4_outlines_layer(outlines_layer, collect_mission4_outline_groups(paths["stage"]))
    return {"paths": {k: str(v) for k, v in paths.items()}, "contract": contract}


def physical_stage_contract(stage_path: Path | str) -> dict[str, Any]:
    """Read the physics contract of the composed Mission 4 stage (pxr only)."""

    from pxr import Usd, UsdGeom, UsdPhysics

    from r17_simready import _find_pod, classify_proxies, memory_cube_size, proxy_name_rejected

    stage = Usd.Stage.Open(str(stage_path), Usd.Stage.LoadAll)
    if not stage:
        raise RuntimeError(f"cannot open {stage_path}")
    root = stage.GetPrimAtPath(ROOT_PATH)
    scenes = [p for p in stage.TraverseAll() if p.IsA(UsdPhysics.Scene)]
    bodies = [p for p in stage.TraverseAll() if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    colliders = [p for p in stage.TraverseAll() if p.HasAPI(UsdPhysics.CollisionAPI)]

    def body_flags(path: str) -> tuple[bool, bool]:
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.HasAPI(UsdPhysics.RigidBodyAPI):
            return False, False
        api = UsdPhysics.RigidBodyAPI(prim)
        return bool(api.GetRigidBodyEnabledAttr().Get()), bool(api.GetKinematicEnabledAttr().Get())

    cube_enabled, cube_kinematic = body_flags(CUBE_PATH)
    pod_enabled, pod_kinematic = body_flags(POD_PATH)
    ground = stage.GetPrimAtPath(GROUND_PATH)

    pod = _find_pod(stage)
    open_top, min_radius = False, None
    if pod is not None:
        analysis = classify_proxies(stage, pod, memory_cube_size(stage))
        pod_colliders = [c for c in colliders if str(c.GetPath()).startswith(str(pod.GetPath()) + "/")]
        open_top = (
            bool(analysis["floor"])
            and analysis["wallCount"] >= 3
            and not analysis["rejected"]
            and not any(proxy_name_rejected(c.GetName()) for c in pod_colliders)
        )
        min_radius = analysis["minInnerRadius"]

    scene = scenes[0] if scenes else None
    gravity = UsdPhysics.Scene(scene).GetGravityMagnitudeAttr().Get() if scene else None
    return {
        "rootType": root.GetTypeName() if root else "",
        "upAxis": str(UsdGeom.GetStageUpAxis(stage)),
        "metersPerUnit": round(float(UsdGeom.GetStageMetersPerUnit(stage)), 6),
        "sceneCount": len(scenes),
        "sceneEnabled": bool(len(scenes) == 1 and scene.IsActive() and gravity and gravity > 0.0),
        "rigidBodyCount": len(bodies),
        "colliderCount": len(colliders),
        "cubeDynamic": bool(cube_enabled and not cube_kinematic),
        "podKinematic": bool(pod_enabled and pod_kinematic),
        "podOpenTop": bool(open_top),
        "podMinimumOpeningRadius": min_radius,
        "groundStatic": bool(ground and ground.HasAPI(UsdPhysics.CollisionAPI) and not ground.HasAPI(UsdPhysics.RigidBodyAPI)),
    }


def contract_failures(contract: dict[str, Any]) -> list[str]:
    """Names of contract fields that do not meet the Mission 4 requirement."""

    checks = {
        "rootType": contract.get("rootType") == "Xform",
        "upAxis": contract.get("upAxis") == "Z",
        "metersPerUnit": contract.get("metersPerUnit") == 0.01,
        "sceneCount": contract.get("sceneCount") == 1,
        "sceneEnabled": contract.get("sceneEnabled") is True,
        "rigidBodyCount": contract.get("rigidBodyCount") == EXPECTED_RIGID_BODIES,
        "colliderCount": contract.get("colliderCount") == EXPECTED_COLLIDERS,
        "cubeDynamic": contract.get("cubeDynamic") is True,
        "podKinematic": contract.get("podKinematic") is True,
        "podOpenTop": contract.get("podOpenTop") is True,
        "podMinimumOpeningRadius": (contract.get("podMinimumOpeningRadius") or 0.0) >= MIN_OPENING_RADIUS,
        "groundStatic": contract.get("groundStatic") is True,
    }
    return [name for name, ok in checks.items() if not ok]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mission 4 physical stage builder")
    parser.add_argument("command", choices=["build", "contract"])
    parser.add_argument("--session-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--outlines", default="", help="write the physics outlines layer here")
    args = parser.parse_args()
    root = Path(args.session_root)
    if args.command == "build":
        result = build_mission4_stage(root, Path(args.outlines) if args.outlines else None)
    else:
        result = {"contract": physical_stage_contract(default_paths(root)["stage"])}
    result["failures"] = contract_failures(result["contract"])
    print(json.dumps(result, indent=1))
    sys.exit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
