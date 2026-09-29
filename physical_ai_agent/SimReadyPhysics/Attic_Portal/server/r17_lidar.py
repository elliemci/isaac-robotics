"""Starter helpers for the R-17 LiDAR Link.

Use this with the installed ovrtx configuring-lidar-sensors,
reading-sensor-pointclouds, interpreting-lidar-pointclouds, stepping-and-rendering,
and reading-render-output skills. The runtime-tested output is a PointCloud
RenderVar with Coordinates, Intensity, ObjectId, Flags, and Counts channels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from pxr import Sdf, Usd, UsdShade

R17_LIDAR_LAYER = Path("usd/R17_Lidar.usda")
R17_LIDAR_SENSOR_PATH = "/Session/Sensors/R17Lidar"
R17_LIDAR_RENDER_PRODUCT = "/Session/Render/Products/R17LidarProduct"
R17_LIDAR_POINTCLOUD_OUTPUT = "PointCloud"
R17_LIDAR_CHANNELS = ("Coordinates", "Intensity", "ObjectId", "Flags", "Counts")
VALID_LIDAR_FLAG = np.uint8(0x40)
STAGE_UNITS_PER_LIDAR_METER = 100.0
R17_LIDAR_PREVIEW_HORIZONTAL_SCALE = 1.35
R17_LIDAR_VISIBLE_POINT_LIMIT = 120000
R17_LIDAR_DENSE_POINT_THRESHOLD = 20000
R17_LIDAR_DENSE_SPACING_MODULUS = 2
R17_LIDAR_COLOR_STOPS = np.array([0.0, 0.12, 0.25, 0.38, 0.52, 0.65, 0.78, 0.90, 1.0], dtype=np.float64)
R17_LIDAR_COLOR_BGR = np.array(
    [
        [255, 40, 20],
        [255, 100, 25],
        [255, 220, 25],
        [160, 240, 30],
        [60, 245, 120],
        [40, 240, 240],
        [25, 90, 255],
        [25, 45, 255],
        [30, 30, 255],
    ],
    dtype=np.float64,
)


def matrix_from_lidar_eye_target(eye: np.ndarray, target: np.ndarray, world_up: np.ndarray | None = None) -> np.ndarray:
    """Return a row-vector USD transform that aims the OmniLidar at target.

    The OmniLidar prim follows the USD camera convention: it looks down its
    local -Z with local +Y up (the ovrtx lidar example authors
    rotateXYZ = (90, 0, -90) to face world +X). Its SENSOR-frame output is
    +X forward, +Y left, +Z up. A calibration scene confirmed both: aiming
    local +X at the target instead points the sensor at the floor.
    """

    up_ref = np.asarray(world_up if world_up is not None else [0.0, 0.0, 1.0], dtype=np.float64)
    eye = np.asarray(eye, dtype=np.float64).reshape(3)
    target = np.asarray(target, dtype=np.float64).reshape(3)
    forward = target - eye
    forward_norm = float(np.linalg.norm(forward))
    if forward_norm <= 1.0e-8 or not np.isfinite(forward_norm):
        raise RuntimeError("invalid lidar eye/target")
    forward = forward / forward_norm
    right = np.cross(forward, up_ref)
    right_norm = float(np.linalg.norm(right))
    if right_norm <= 1.0e-8 or not np.isfinite(right_norm):
        right = np.cross(forward, np.array([0.0, 1.0, 0.0], dtype=np.float64))
        right_norm = float(np.linalg.norm(right))
    right = right / right_norm
    up = np.cross(right, forward)
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0:3] = right
    matrix[1, 0:3] = up
    matrix[2, 0:3] = -forward
    matrix[3, 0:3] = eye
    return matrix


def query_unlabeled_lidar_material_paths(stage_path: Path | list[Path] | tuple[Path, ...]) -> list[str]:
    """Return material prims that need viewer-owned nonvisual defaults."""

    if isinstance(stage_path, (list, tuple)):
        discovery_layer = Sdf.Layer.CreateAnonymous("r17-lidar-material-discovery.usda")
        discovery_layer.subLayerPaths = [str(Path(path).resolve()) for path in stage_path]
        stage = Usd.Stage.Open(discovery_layer)
    else:
        stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise RuntimeError(f"could not open USD stage for LiDAR materials: {stage_path}")
    paths: list[str] = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        if prim.GetAttribute("omni:simready:nonvisual:base") or prim.GetAttribute("inputs:nonvisual:base"):
            continue
        paths.append(str(prim.GetPath()))
    return sorted(paths)


def _author_nonvisual_material_defaults(path: Path, material_paths: list[str]) -> None:
    """Author default sensor-return metadata on material prims in the app layer."""

    if not material_paths:
        return
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        raise RuntimeError(f"could not reopen LiDAR layer: {path}")
    for material_path in material_paths:
        prim = stage.OverridePrim(material_path)
        prim.CreateAttribute("omni:simready:nonvisual:base", Sdf.ValueTypeNames.Token, custom=True).Set("none")
        prim.CreateAttribute("omni:simready:nonvisual:coating", Sdf.ValueTypeNames.Token, custom=True).Set("none")
        prim.CreateAttribute("omni:simready:nonvisual:attributes", Sdf.ValueTypeNames.TokenArray, custom=True).Set(["none"])
        prim.CreateAttribute("inputs:nonvisual:base", Sdf.ValueTypeNames.String, custom=True).Set("none")
        prim.CreateAttribute("inputs:nonvisual:coating", Sdf.ValueTypeNames.String, custom=True).Set("none")
        prim.CreateAttribute("inputs:nonvisual:attributes", Sdf.ValueTypeNames.String, custom=True).Set("none")
    stage.GetRootLayer().Save()


def write_r17_lidar_layer(
    path: Path,
    lidar_matrix: np.ndarray,
    *,
    active: bool = False,
    material_paths: list[str] | None = None,
) -> None:
    """Author the app-owned LiDAR sensor/product layer without touching source USD."""

    path.parent.mkdir(parents=True, exist_ok=True)
    m = np.asarray(lidar_matrix, dtype=np.float64).reshape(4, 4)
    rows = ",\n                    ".join("(" + ", ".join(f"{float(v):.12g}" for v in row) + ")" for row in m)
    active_metadata = "" if active else "\n            active = false"
    channels = ",\n                    ".join(f'"{channel}"' for channel in R17_LIDAR_CHANNELS)
    text = f"""#usda 1.0
(
    defaultPrim = "Session"
)

def Xform "Session"
{{
    def Xform "Sensors"
    {{
        def OmniLidar "R17Lidar" ({active_metadata}
            prepend apiSchemas = ["OmniSensorGenericLidarCoreAPI"]
        )
        {{
            token omni:sensor:Core:elementsCoordsType = "CARTESIAN"
            double2 omni:sensor:frameRate = (10, 1)
            bool omni:sensor:Core:includeInvalidPoints = false
            bool omni:sensor:Core:instantLidar = true
            token omni:sensor:Core:outputFrameOfReference = "SENSOR"
            token omni:sensor:Core:outputMotionCompensationState = "NONCOMPENSATED"
            bool omni:sensor:Core:partialOutputs = false
            matrix4d xformOp:transform = (
                    {rows}
            )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}
    }}

    def "Render"
    {{
        def "Products"
        {{
            def RenderProduct "R17LidarProduct" ({active_metadata}
            )
            {{
                rel camera = <{R17_LIDAR_SENSOR_PATH}>
                rel orderedVars = [<../../Vars/PointCloud>]
            }}
        }}

        def "Vars"
        {{
            def RenderVar "PointCloud"
            {{
                uniform string sourceName = "PointCloud"
                # ovrtx 0.3.0.312915 requires string[] here; token[] parses as
                # USD but produces a composite PointCloud with no tensors.
                string[] channels = [
                    {channels}
                ]
            }}
        }}
    }}
}}
"""
    path.write_text(text, encoding="utf-8")
    _author_nonvisual_material_defaults(path, material_paths or [])


def parse_lidar_pointcloud(pointcloud: Any) -> dict[str, Any]:
    """Copy and validate mapped PointCloud channels.

    Call this while the PointCloud is mapped, then unmap immediately. The return
    value only contains CPU numpy arrays and scalar telemetry.
    """

    coordinates = np.from_dlpack(pointcloud["Coordinates"]).copy()
    counts = np.from_dlpack(pointcloud["Counts"]).copy()
    flags = np.from_dlpack(pointcloud["Flags"]).copy()
    intensity = np.from_dlpack(pointcloud["Intensity"]).copy()
    object_ids = np.from_dlpack(pointcloud["ObjectId"]).copy() if "ObjectId" in pointcloud else None

    count = int(np.asarray(counts).reshape(-1)[0]) if np.asarray(counts).size else 0
    if coordinates.ndim != 2:
        raise RuntimeError(f"Unexpected Coordinates shape: {coordinates.shape}")
    if coordinates.shape[0] == 3:
        point_capacity = int(coordinates.shape[1])
        points_source = np.asarray(coordinates[:, :point_capacity], dtype=np.float64).T
    elif coordinates.shape[1] == 3:
        point_capacity = int(coordinates.shape[0])
        points_source = np.asarray(coordinates[:point_capacity, :], dtype=np.float64)
    else:
        raise RuntimeError(f"Unexpected Coordinates shape: {coordinates.shape}")

    max_points = min(count, point_capacity, int(np.asarray(flags).reshape(-1).shape[0]))
    if max_points <= 0:
        return {"points": np.zeros((0, 3), dtype=np.float64), "intensity": np.zeros((0,), dtype=np.float32), "objectColors": None, "validPointCount": 0, "nearestRange": None}

    points = points_source[:max_points]
    point_flags = np.asarray(flags).reshape(-1)[:max_points]
    valid_mask = (point_flags.astype(np.uint8) & VALID_LIDAR_FLAG) != 0
    valid_points = points[valid_mask]
    point_intensity = np.asarray(intensity).reshape(-1)[:max_points][valid_mask]
    object_colors_all = colors_from_object_id(object_ids, max_points)
    object_colors = object_colors_all[valid_mask] if object_colors_all is not None else None
    nearest = None
    if valid_points.shape[0] > 0:
        ranges = np.linalg.norm(valid_points, axis=1)
        nearest = float(np.min(ranges))
        if not np.isfinite(nearest):
            nearest = None
    return {
        "points": valid_points.copy(),
        "intensity": point_intensity.copy(),
        "objectColors": object_colors.copy() if object_colors is not None else None,
        "validPointCount": int(valid_points.shape[0]),
        "nearestRange": nearest,
    }


def colors_from_object_id(object_ids: np.ndarray | None, count: int) -> np.ndarray | None:
    """Return stable BGRA-ish colors for packed 128-bit ObjectId values.

    PointCloud ObjectId is shaped ``[Nmax, 4]`` with four uint32 words per
    point. The Old Attic output can expose ObjectId while every valid ID is
    zero; in that case return None and use depth/intensity coloring instead.
    """

    if object_ids is None:
        return None
    ids = np.asarray(object_ids, dtype=np.uint32)
    if ids.ndim != 2 or ids.shape[1] != 4:
        raise RuntimeError(f"Unexpected ObjectId shape: {ids.shape}; expected (N, 4)")
    if count < 0 or count > ids.shape[0]:
        raise RuntimeError(f"ObjectId count {count} exceeds point capacity {ids.shape[0]}")
    ids = ids[:count, :]
    if ids.size == 0 or np.count_nonzero(ids) == 0:
        return None

    # Fold all four words so IDs that differ outside the first word do not
    # collapse to the same color, then apply the existing uint32 avalanche.
    h = ids[:, 0].copy()
    for lane in range(1, 4):
        h ^= ids[:, lane] + np.uint32(0x9E3779B9) + (h << np.uint32(6)) + (h >> np.uint32(2))
    h = (h ^ np.uint32(61)) ^ (h >> np.uint32(16))
    h = h + (h << np.uint32(3))
    h = h ^ (h >> np.uint32(4))
    h = h * np.uint32(0x27D4EB2D)
    h = h ^ (h >> np.uint32(15))
    colors = np.empty((int(count), 3), dtype=np.uint8)
    colors[:, 0] = (80 + ((h >> np.uint32(16)) & np.uint32(127))).astype(np.uint8)
    colors[:, 1] = (80 + ((h >> np.uint32(8)) & np.uint32(127))).astype(np.uint8)
    colors[:, 2] = (80 + (h & np.uint32(127))).astype(np.uint8)
    return colors


def lidar_points_to_world(points_sensor: np.ndarray | None, sensor_matrix: np.ndarray | None) -> np.ndarray | None:
    if points_sensor is None or sensor_matrix is None:
        return None
    pts = np.asarray(points_sensor, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or pts.shape[0] == 0:
        return None
    m = np.asarray(sensor_matrix, dtype=np.float64).reshape(4, 4)
    # SENSOR output axes (+X forward, +Y left, +Z up) in world, from the
    # camera-convention prim rows (right, up, back).
    output_axes = np.stack([-m[2, 0:3], -m[0, 0:3], m[1, 0:3]])
    world = (pts * STAGE_UNITS_PER_LIDAR_METER) @ output_axes + m[3, 0:3]
    return world[np.isfinite(world).all(axis=1)]


def lidar_sensor_points_to_camera(points_sensor: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return camera depth/right/up from SENSOR-frame lidar points.

    SENSOR output is +X forward, +Y left, +Z up. The sensor is posed
    coincident with the camera, so screen-right is the negative sensor-left
    axis.
    """

    points = np.asarray(points_sensor, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise RuntimeError(f"Unexpected sensor point shape: {points.shape}")
    return points[:, 0], -points[:, 1], points[:, 2]


def fallback_lidar_density_preview(points: np.ndarray, intensity: np.ndarray, *, height: int, width: int, object_colors: np.ndarray | None = None) -> np.ndarray:
    """Return a stable sensor-frame top/side density preview for the inset."""

    if height <= 0 or width <= 0:
        raise RuntimeError(f"Unexpected video dimensions: {width}x{height}")
    preview_scale = min(0.5, 460.0 / width, 280.0 / height)
    preview_h = max(1, int(round(height * preview_scale)))
    preview_w = max(1, int(round(width * preview_scale)))
    preview = np.zeros((preview_h, preview_w, 4), dtype=np.uint8)
    preview[:, :, :] = np.array([14, 18, 24, 242], dtype=np.uint8)
    border = np.array([150, 220, 255, 255], dtype=np.uint8)
    preview[0:2, :, :] = border
    preview[-2:, :, :] = border
    preview[:, 0:2, :] = border
    preview[:, -2:, :] = border

    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or pts.shape[0] == 0:
        return preview
    pts = pts[np.isfinite(pts).all(axis=1)]
    if pts.shape[0] == 0:
        return preview
    if pts.shape[0] > 180000:
        pts = pts[::max(1, pts.shape[0] // 180000)]

    top_h = int(preview_h * 0.66)
    side_y0 = top_h + 4
    mid_x = preview_w // 2
    preview[top_h:top_h + 2, 4:-4, :] = np.array([70, 95, 105, 255], dtype=np.uint8)
    preview[4:top_h - 4, mid_x:mid_x + 1, :] = np.array([45, 62, 70, 255], dtype=np.uint8)
    preview[side_y0:-4, mid_x:mid_x + 1, :] = np.array([45, 62, 70, 255], dtype=np.uint8)

    _draw_density(preview, 6, top_h - 6, 8, preview_w - 8, pts[:, 1], pts[:, 0], object_colors)
    _draw_density(preview, side_y0 + 4, preview_h - 8, 8, preview_w - 8, pts[:, 1], pts[:, 2], object_colors)
    return preview


def camera_projected_lidar_preview(
    points_sensor: np.ndarray | None,
    sensor_matrix: np.ndarray | None,
    *,
    camera_basis: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    focal_length: float,
    horizontal_aperture: float,
    video_height: int,
    video_width: int,
    preview_height: int,
    preview_width: int,
    world_points: np.ndarray | None = None,
) -> np.ndarray | None:
    """Project LiDAR returns into the active camera view for the inset."""

    if points_sensor is not None:
        sensor_points = np.asarray(points_sensor, dtype=np.float64)
        sensor_points = sensor_points[np.isfinite(sensor_points).all(axis=1)]
        if sensor_points.shape[0] == 0:
            return None
        depth, cam_x, cam_y = lidar_sensor_points_to_camera(sensor_points)
    else:
        if world_points is None:
            world = lidar_points_to_world(points_sensor, sensor_matrix)
        else:
            world = np.asarray(world_points, dtype=np.float64)
            if world.ndim != 2 or world.shape[1] != 3:
                return None
            world = world[np.isfinite(world).all(axis=1)]
        if world is None or world.shape[0] == 0:
            return None
        eye, forward, right, up = camera_basis
        rel = world - np.asarray(eye, dtype=np.float64).reshape(1, 3)
        depth = rel @ np.asarray(forward, dtype=np.float64).reshape(3)
        cam_x = rel @ np.asarray(right, dtype=np.float64).reshape(3)
        cam_y = rel @ np.asarray(up, dtype=np.float64).reshape(3)
    visible = np.isfinite(depth) & (depth > 1.0)
    if not np.any(visible):
        return None

    depth = depth[visible]
    cam_x = cam_x[visible]
    cam_y = cam_y[visible]
    vaperture = horizontal_aperture * float(video_height) / float(video_width)
    tan_x = max(1.0e-6, horizontal_aperture / (2.0 * focal_length))
    tan_y = max(1.0e-6, vaperture / (2.0 * focal_length))
    ndc_x = cam_x / (depth * tan_x)
    ndc_y = cam_y / (depth * tan_y)
    ndc_x = ndc_x * R17_LIDAR_PREVIEW_HORIZONTAL_SCALE
    on_screen = (np.abs(ndc_x) <= 1.0) & (np.abs(ndc_y) <= 1.0)
    if not np.any(on_screen):
        return None
    ndc_x = ndc_x[on_screen]
    ndc_y = ndc_y[on_screen]
    depth = depth[on_screen]
    visible_point_limit = R17_LIDAR_VISIBLE_POINT_LIMIT
    if depth.shape[0] > visible_point_limit:
        stride = max(1, (depth.shape[0] + visible_point_limit - 1) // visible_point_limit)
        ndc_x = ndc_x[::stride]
        ndc_y = ndc_y[::stride]
        depth = depth[::stride]

    d0 = float(np.percentile(depth, 0.5))
    d1 = float(np.percentile(depth, 99.5))
    if d1 - d0 < 1.0:
        d1 = d0 + 1.0

    preview = np.zeros((preview_height, preview_width, 4), dtype=np.uint8)
    preview[:, :, :] = np.array([12, 16, 22, 242], dtype=np.uint8)
    border = np.array([150, 220, 255, 255], dtype=np.uint8)
    preview[0:2, :, :] = border
    preview[-2:, :, :] = border
    preview[:, 0:2, :] = border
    preview[:, -2:, :] = border

    px = np.clip(((ndc_x * 0.5 + 0.5) * (preview_width - 1)).astype(np.int32), 2, preview_width - 3)
    py = np.clip(((0.5 - ndc_y * 0.5) * (preview_height - 1)).astype(np.int32), 2, preview_height - 3)
    if depth.shape[0] >= R17_LIDAR_DENSE_POINT_THRESHOLD:
        spaced = (px + py) % R17_LIDAR_DENSE_SPACING_MODULUS == 0
        px = px[spaced]
        py = py[spaced]
        depth = depth[spaced]
    t = np.clip((depth - d0) / max(d1 - d0, 1.0e-6), 0.0, 1.0)
    colors = np.empty((depth.shape[0], 4), dtype=np.uint8)
    # Continuous BGRA ramp: deep blue -> blue -> cyan -> green -> lime -> yellow -> orange -> red.
    colors[:, 0] = np.interp(t, R17_LIDAR_COLOR_STOPS, R17_LIDAR_COLOR_BGR[:, 0]).astype(np.uint8)
    colors[:, 1] = np.interp(t, R17_LIDAR_COLOR_STOPS, R17_LIDAR_COLOR_BGR[:, 1]).astype(np.uint8)
    colors[:, 2] = np.interp(t, R17_LIDAR_COLOR_STOPS, R17_LIDAR_COLOR_BGR[:, 2]).astype(np.uint8)
    colors[:, 3] = 255
    zbuffer = np.full((preview_height * preview_width,), np.inf, dtype=np.float64)
    flat_preview = preview.reshape(-1, 4)
    point_offsets = (
        ((0, 0), (0, 1), (1, 0), (1, 1))
        if depth.shape[0] < R17_LIDAR_DENSE_POINT_THRESHOLD
        else ((0, 0),)
    )
    for dy, dx in point_offsets:
        yy = np.clip(py + dy, 2, preview_height - 3)
        xx = np.clip(px + dx, 2, preview_width - 3)
        np.minimum.at(zbuffer, yy * preview_width + xx, depth)
    for dy, dx in point_offsets:
        yy = np.clip(py + dy, 2, preview_height - 3)
        xx = np.clip(px + dx, 2, preview_width - 3)
        pixel_ids = yy * preview_width + xx
        wins = depth <= zbuffer[pixel_ids] + 1.0e-9
        flat_preview[pixel_ids[wins]] = colors[wins]
    preview[preview_height // 2:preview_height // 2 + 1, 6:-6, :] = np.maximum(preview[preview_height // 2:preview_height // 2 + 1, 6:-6, :], np.array([40, 55, 65, 255], dtype=np.uint8))
    preview[6:-6, preview_width // 2:preview_width // 2 + 1, :] = np.maximum(preview[6:-6, preview_width // 2:preview_width // 2 + 1, :], np.array([40, 55, 65, 255], dtype=np.uint8))
    return preview


def overlay_lidar_preview(video_bgra: np.ndarray, preview_bgra: np.ndarray | None) -> np.ndarray:
    """Composite the LiDAR inset in the lower-left of the existing BGRA stream."""

    if preview_bgra is None:
        return video_bgra
    ph, pw = preview_bgra.shape[:2]
    height, width = video_bgra.shape[:2]
    if ph <= 0 or pw <= 0 or ph + 18 > height or pw + 18 > width:
        return video_bgra
    out = video_bgra.copy()
    y0 = height - ph - 16
    x0 = 16
    roi = out[y0:y0 + ph, x0:x0 + pw, :].astype(np.float32)
    alpha = preview_bgra[:, :, 3:4].astype(np.float32) / 255.0
    roi[:, :, 0:3] = roi[:, :, 0:3] * (1.0 - alpha) + preview_bgra[:, :, 0:3].astype(np.float32) * alpha
    roi[:, :, 3] = 255
    out[y0:y0 + ph, x0:x0 + pw, :] = np.clip(roi, 0, 255).astype(np.uint8)
    return out


def _draw_density(preview: np.ndarray, y0: int, y1: int, x0: int, x1: int, horiz: np.ndarray, depth: np.ndarray, object_colors: np.ndarray | None) -> None:
    h = max(1, y1 - y0)
    w = max(1, x1 - x0)
    finite = np.isfinite(horiz) & np.isfinite(depth)
    if not np.any(finite):
        return
    horiz_v = horiz[finite]
    depth_v = depth[finite]
    h_extent = max(float(np.percentile(np.abs(horiz_v), 99)), 0.25)
    d_min = float(np.percentile(depth_v, 1))
    d_max = float(np.percentile(depth_v, 99))
    if d_max - d_min < 1.0e-6:
        d_max = d_min + 1.0
    px = np.clip(((horiz_v / h_extent) * 0.47 + 0.5) * (w - 1), 0, w - 1).astype(np.int32)
    py = np.clip((1.0 - (depth_v - d_min) / (d_max - d_min)) * (h - 1), 0, h - 1).astype(np.int32)
    density = np.zeros((h, w), dtype=np.uint16)
    np.add.at(density, (py, px), 1)
    density[:, 1:] += density[:, :-1] // 2
    density[:, :-1] += density[:, 1:] // 2
    density[1:, :] += density[:-1, :] // 2
    density[:-1, :] += density[1:, :] // 2
    mask = density > 0
    if not np.any(mask):
        return
    d_norm = np.clip(np.log1p(density.astype(np.float32)) / np.log1p(max(float(np.max(density)), 1.0)), 0.0, 1.0)
    pane = preview[y0:y1, x0:x1, :]
    pane[mask, 0] = np.clip(80 + 175 * d_norm[mask], 0, 255).astype(np.uint8)
    pane[mask, 1] = np.clip(115 + 120 * d_norm[mask], 0, 255).astype(np.uint8)
    pane[mask, 2] = np.clip(235 - 80 * d_norm[mask], 0, 255).astype(np.uint8)
    pane[mask, 3] = 255
    if object_colors is None or len(object_colors) != len(horiz):
        return
    colors_v = np.asarray(object_colors, dtype=np.uint8)[finite]
    color_accum = np.zeros((h, w, 3), dtype=np.uint32)
    color_count = np.zeros((h, w), dtype=np.uint16)
    np.add.at(color_accum, (py, px, 0), colors_v[:, 0].astype(np.uint32))
    np.add.at(color_accum, (py, px, 1), colors_v[:, 1].astype(np.uint32))
    np.add.at(color_accum, (py, px, 2), colors_v[:, 2].astype(np.uint32))
    np.add.at(color_count, (py, px), 1)
    cmask = color_count > 0
    avg = np.zeros((h, w, 3), dtype=np.uint8)
    avg[cmask] = np.clip(color_accum[cmask] / color_count[cmask, None], 0, 255).astype(np.uint8)
    pane[cmask, 0:3] = np.clip(avg[cmask].astype(np.float32) * (0.55 + 0.45 * d_norm[cmask, None]), 0, 255).astype(np.uint8)
    pane[cmask, 3] = 255
