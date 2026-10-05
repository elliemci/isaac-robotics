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


def _curves_usda(name: str, polylines, color, indent: str) -> str:
    counts = ", ".join(str(len(line)) for line in polylines)
    points = ", ".join(f"({p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f})" for line in polylines for p in line)
    return f'''{indent}def BasisCurves "{name}"
{indent}{{
{indent}    uniform token type = "linear"
{indent}    int[] curveVertexCounts = [{counts}]
{indent}    point3f[] points = [{points}]
{indent}    float[] widths = [{LINE_WIDTH}] (interpolation = "constant")
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
