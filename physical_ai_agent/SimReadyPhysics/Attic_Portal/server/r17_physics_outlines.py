"""R-17 physics outlines (Mission 3, Part 2).

Writes the viewer-owned R17_PhysicsOutlines.usda layer: green wireframes over
every CollisionAPI proxy and an orange wireframe over the RigidBodyAPI pod
bounds. The layer composes above the fixed scene and is rendered by ovrtx, so
the outlines stream like any other geometry. Nothing here touches user USD.

It must only be written after a successful fix; callers pass the pod's prim
path inside the composed stage so the outlines inherit the pod's transform.
"""

import math
from pathlib import Path
from typing import Any

OUTLINE_LAYER_NAME = "R17_PhysicsOutlines.usda"
COLLISION_COLOR = (0.1, 1.0, 0.25)
RIGID_BODY_COLOR = (1.0, 0.55, 0.05)
LINE_WIDTH = 0.6  # stage units (cm in this scene)
CIRCLE_SEGMENTS = 32

_BOX_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def _box_polylines(center, axes, halves) -> list[list[tuple[float, float, float]]]:
    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corners.append(tuple(float(center[k] + sx * halves[0] * axes[0][k] + sy * halves[1] * axes[1][k] + sz * halves[2] * axes[2][k]) for k in range(3)))
    return [[corners[a], corners[b]] for a, b in _BOX_EDGES]


def _cylinder_polylines(center, radius, height) -> list[list[tuple[float, float, float]]]:
    lines = []
    for z in (-height / 2.0, height / 2.0):
        ring = [
            (center[0] + radius * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS), center[1] + radius * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS), center[2] + z)
            for i in range(CIRCLE_SEGMENTS + 1)
        ]
        lines.append(ring)
    for k in range(4):
        a = 2 * math.pi * k / 4
        x, y = center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)
        lines.append([(x, y, center[2] - height / 2.0), (x, y, center[2] + height / 2.0)])
    return lines


def collect_outline_geometry(pod_stage_path: Path | str) -> dict[str, Any]:
    """Wireframe polylines (pod frame) for each CollisionAPI proxy and the pod bounds."""

    import numpy as np
    from pxr import Usd, UsdGeom, UsdPhysics

    from r17_simready import _box_axes, _find_pod

    stage = Usd.Stage.Open(str(pod_stage_path), Usd.Stage.LoadAll)
    pod = _find_pod(stage)
    xcache = UsdGeom.XformCache()
    bcache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render])
    collision: dict[str, list] = {}
    lows, highs = [], []
    for prim in Usd.PrimRange(pod, Usd.PrimAllPrimsPredicate):
        if not (prim.IsA(UsdGeom.Gprim) and prim.HasAPI(UsdPhysics.CollisionAPI)):
            continue
        matrix = xcache.ComputeRelativeTransform(prim, pod)[0]
        rng = bcache.ComputeRelativeBound(prim, pod).ComputeAlignedRange()
        lows.append(list(rng.GetMin()))
        highs.append(list(rng.GetMax()))
        if prim.IsA(UsdGeom.Cube):
            size = prim.GetAttribute("size").Get()
            center, axes, halves = _box_axes(matrix, float(size if size is not None else 2.0))
            collision[prim.GetName()] = _box_polylines(center, axes, halves)
        elif prim.IsA(UsdGeom.Cylinder):
            radius, height = float(prim.GetAttribute("radius").Get()), float(prim.GetAttribute("height").Get())
            c = matrix.ExtractTranslation()
            collision[prim.GetName()] = _cylinder_polylines((c[0], c[1], c[2]), radius, height)
        else:
            low, high = rng.GetMin(), rng.GetMax()
            center = [(low[k] + high[k]) / 2.0 for k in range(3)]
            collision[prim.GetName()] = _box_polylines(center, np.eye(3), [(high[k] - low[k]) / 2.0 for k in range(3)])
    if not collision:
        raise ValueError("no CollisionAPI geometry to outline")
    low, high = np.min(lows, axis=0), np.max(highs, axis=0)
    body = _box_polylines((low + high) / 2.0, np.eye(3), (high - low) / 2.0)
    return {"podPath": str(pod.GetPath()), "collision": collision, "rigidBody": body}


def _curves_usda(name: str, polylines, color, indent: str, width: float = LINE_WIDTH, material: str = "") -> str:
    api = f'{indent}def BasisCurves "{name}" (\n{indent}    prepend apiSchemas = ["MaterialBindingAPI"]\n{indent})' if material else f'{indent}def BasisCurves "{name}"'
    binding = f"{indent}    rel material:binding = <{material}>\n" if material else ""
    counts = ", ".join(str(len(line)) for line in polylines)
    points = ", ".join(f"({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})" for line in polylines for p in line)
    return f'''{api}
{indent}{{
{binding}{indent}    uniform token type = "linear"
{indent}    int[] curveVertexCounts = [{counts}]
{indent}    point3f[] points = [{points}]
{indent}    float[] widths = [{width}] (interpolation = "constant")
{indent}    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})] (interpolation = "constant")
{indent}    token visibility = "inherited"
{indent}}}
'''


def outlines_layer_usda(geometry: dict[str, Any]) -> str:
    """USDA text for the outlines layer, authored as overs on the pod prim."""

    parts = Path_parts(geometry["podPath"])
    opening, closing = "", ""
    for depth, part in enumerate(parts[:-1]):
        opening += f'{"    " * depth}over "{part}"\n{"    " * depth}{{\n'
        closing = f'{"    " * depth}}}\n' + closing
    depth = len(parts) - 1
    pad = "    " * depth
    body = f'{pad}over "{parts[-1]}"\n{pad}{{\n{pad}    def Scope "R17PhysicsOutlines"\n{pad}    {{\n'
    inner = "    " * (depth + 2)
    for name, polylines in sorted(geometry["collision"].items()):
        body += _curves_usda(f"CollisionAPI_{name}", polylines, COLLISION_COLOR, inner)
    body += _curves_usda("RigidBodyAPI_Pod", geometry["rigidBody"], RIGID_BODY_COLOR, inner)
    body += f"{pad}    }}\n{pad}}}\n"
    return f'#usda 1.0\n(\n    doc = "Viewer-owned physics outlines: CollisionAPI proxies (green), RigidBodyAPI pod bounds (orange)."\n)\n\n{opening}{body}{closing}'


def Path_parts(prim_path: str) -> list[str]:
    return [part for part in prim_path.split("/") if part]


def write_outlines_layer(layer_path: Path | str, geometry: dict[str, Any]) -> Path:
    layer_path = Path(layer_path)
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    layer_path.write_text(outlines_layer_usda(geometry), encoding="utf-8")
    return layer_path


# ---------------------------------------------------------------------------
# Mission 4: three distinct groups, composed from startup (before Play).
# ---------------------------------------------------------------------------

SCENE_COLOR = (0.25, 0.55, 1.0)
RIGID_BODY_PAD = 2.0  # rigid-body box sits just outside its collider so both read
MISSION4_GROUP_COLORS = {"RigidBodyAPI": RIGID_BODY_COLOR, "CollisionAPI": COLLISION_COLOR, "PhysicsScene": SCENE_COLOR}
# Distinct, readable widths; scene and rigid-body lines are thicker so they
# stand out against the green collider wireframes.
MISSION4_GROUP_WIDTHS = {"RigidBodyAPI": 1.4, "CollisionAPI": 0.7, "PhysicsScene": 1.6}
EMISSIVE_GAIN = 0.9
SCENE_FRAME_MARGIN = 18.0
LOOKS_PATH = "/R17OutlineLooks"


def _arrow_polylines(base_xy, top_z, bottom_z, head=12.0) -> list[list[tuple[float, float, float]]]:
    x, y = base_xy
    return [
        [(x, y, top_z), (x, y, bottom_z)],
        [(x - head / 2, y, bottom_z + head), (x, y, bottom_z), (x + head / 2, y, bottom_z + head)],
        [(x, y - head / 2, bottom_z + head), (x, y, bottom_z), (x, y + head / 2, bottom_z + head)],
    ]


def collect_mission4_outline_groups(stage_path: Path | str) -> list[dict[str, Any]]:
    """Wireframe groups for the Mission 4 stage, each in the frame of its owner prim.

    A collider is outlined under its nearest RigidBodyAPI ancestor (or itself),
    so the cube's outlines follow the cube once physics moves it. RigidBodyAPI
    boxes are orange, CollisionAPI green, and the PhysicsScene gizmo (ground
    frame plus a gravity arrow) blue.
    """

    import numpy as np
    from pxr import Usd, UsdGeom, UsdPhysics

    from r17_simready import _box_axes

    stage = Usd.Stage.Open(str(stage_path), Usd.Stage.LoadAll)
    xcache = UsdGeom.XformCache()
    bcache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render])
    root = stage.GetPrimAtPath("/Root")

    def owner_of(prim):
        node = prim
        while node and node.GetPath() != root.GetPath():
            if node.HasAPI(UsdPhysics.RigidBodyAPI):
                return node
            node = node.GetParent()
        return root

    def polylines_for(prim, owner):
        matrix = xcache.ComputeRelativeTransform(prim, owner)[0]
        if prim.IsA(UsdGeom.Cube):
            size = prim.GetAttribute("size").Get()
            center, axes, halves = _box_axes(matrix, float(size if size is not None else 2.0))
            return _box_polylines(center, axes, halves)
        if prim.IsA(UsdGeom.Cylinder):
            c = matrix.ExtractTranslation()
            return _cylinder_polylines((c[0], c[1], c[2]), float(prim.GetAttribute("radius").Get()), float(prim.GetAttribute("height").Get()))
        rng = bcache.ComputeRelativeBound(prim, owner).ComputeAlignedRange()
        low, high = rng.GetMin(), rng.GetMax()
        return _box_polylines([(low[k] + high[k]) / 2.0 for k in range(3)], np.eye(3), [(high[k] - low[k]) / 2.0 for k in range(3)])

    groups: list[dict[str, Any]] = []
    body_bounds: dict[str, tuple[list, list]] = {}
    for prim in stage.TraverseAll():
        if prim.HasAPI(UsdPhysics.CollisionAPI) and prim.IsA(UsdGeom.Gprim):
            owner = owner_of(prim)
            lines = polylines_for(prim, owner)
            groups.append({"owner": str(owner.GetPath()), "name": f"CollisionAPI_{prim.GetName()}", "kind": "CollisionAPI", "polylines": lines})
            pts = np.array([p for line in lines for p in line])
            lo, hi = body_bounds.setdefault(str(owner.GetPath()), ([*pts.min(axis=0)], [*pts.max(axis=0)]))
            body_bounds[str(owner.GetPath())] = ([min(a, b) for a, b in zip(lo, pts.min(axis=0))], [max(a, b) for a, b in zip(hi, pts.max(axis=0))])
    for body in stage.TraverseAll():
        if body.HasAPI(UsdPhysics.RigidBodyAPI) and str(body.GetPath()) in body_bounds:
            lo, hi = (np.array(v) for v in body_bounds[str(body.GetPath())])
            pad = RIGID_BODY_PAD
            groups.append({
                "owner": str(body.GetPath()),
                "name": "RigidBodyAPI_" + body.GetName(),
                "kind": "RigidBodyAPI",
                "polylines": _box_polylines((lo + hi) / 2.0, np.eye(3), (hi - lo) / 2.0 + pad),
            })

    scene = next((p for p in stage.TraverseAll() if p.IsA(UsdPhysics.Scene)), None)
    ground = stage.GetPrimAtPath("/Root/PhysicsGround")
    if scene is not None and ground:
        rng = bcache.ComputeRelativeBound(ground, root).ComputeAlignedRange()
        low, high = rng.GetMin(), rng.GetMax()
        top = high[2] + 3.0
        m = SCENE_FRAME_MARGIN  # outside the ground collider's own outline so both read
        frame = [[(low[0] - m, low[1] - m, top), (high[0] + m, low[1] - m, top), (high[0] + m, high[1] + m, top), (low[0] - m, high[1] + m, top), (low[0] - m, low[1] - m, top)]]
        cx, cy = (low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0
        groups.append({"owner": "/Root", "name": "PhysicsScene_" + scene.GetName(), "kind": "PhysicsScene", "polylines": frame + _arrow_polylines((cx - 60.0, cy), top + 110.0, top + 30.0, head=18.0)})
    if not any(g["kind"] == "PhysicsScene" for g in groups):
        raise ValueError("stage has no PhysicsScene or ground to outline")
    return groups


def mission4_outlines_layer_usda(groups: list[dict[str, Any]]) -> str:
    """USDA for the outlines layer: curves authored as overs under each owner prim."""

    tree: dict[str, Any] = {}
    for group in groups:
        node = tree
        for part in Path_parts(group["owner"]):
            node = node.setdefault(part, {})
        node.setdefault("__groups__", []).append(group)

    def emit(node: dict[str, Any], depth: int) -> str:
        text = ""
        pad = "    " * depth
        groups_here = node.get("__groups__", [])
        for name, child in sorted((k, v) for k, v in node.items() if k != "__groups__"):
            text += f'{pad}over "{name}"\n{pad}{{\n{emit(child, depth + 1)}{pad}}}\n'
        if groups_here:
            text += f'{pad}def Scope "R17PhysicsOutlines"\n{pad}{{\n'
            for group in groups_here:
                kind = group["kind"]
                text += _curves_usda(group["name"], group["polylines"], MISSION4_GROUP_COLORS[kind], pad + "    ", MISSION4_GROUP_WIDTHS[kind], f"{LOOKS_PATH}/{kind}")
            text += f"{pad}}}\n"
        return text

    looks = f'def Scope "{LOOKS_PATH.lstrip("/")}"\n{{\n'
    for kind, color in MISSION4_GROUP_COLORS.items():
        emissive = ", ".join(f"{c * EMISSIVE_GAIN:.3f}" for c in color)
        looks += (
            f'    def Material "{kind}"\n    {{\n'
            f'        token outputs:surface.connect = <{LOOKS_PATH}/{kind}/Surface.outputs:surface>\n'
            f'        def Shader "Surface"\n        {{\n'
            f'            uniform token info:id = "UsdPreviewSurface"\n'
            f'            color3f inputs:diffuseColor = (0.0, 0.0, 0.0)\n'
            f'            color3f inputs:emissiveColor = ({emissive})\n'
            f'            token outputs:surface\n        }}\n    }}\n'
        )
    looks += "}\n\n"
    return (
        '#usda 1.0\n(\n    doc = "Viewer-owned physics outlines: RigidBodyAPI orange, CollisionAPI green, PhysicsScene blue."\n)\n\n'
        + looks
        + emit(tree, 0)
    )


def write_mission4_outlines_layer(layer_path: Path | str, groups: list[dict[str, Any]]) -> Path:
    layer_path = Path(layer_path)
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    layer_path.write_text(mission4_outlines_layer_usda(groups), encoding="utf-8")
    return layer_path
