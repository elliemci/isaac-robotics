#!/usr/bin/env python3
import argparse
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

import numpy as np
import ovrtx
import ovstream
import warp as wp
from PIL import Image

KIT_USD_PYTHON = Path("/home/nvidia/.cache/packman/chk/usd.py312.manylinux_2_35_x86_64.stock.release/0.25.11.kit.2-gl.19811/lib/python")
if KIT_USD_PYTHON.exists() and str(KIT_USD_PYTHON) not in sys.path:
    sys.path.insert(0, str(KIT_USD_PYTHON))

from pxr import Usd, UsdGeom

from camera_controller import OrbitCamera
from r17_camera_presets import (
    ACTIVE_VIEWER_CAMERA_PATH,
    R17_FOCUS_CAMERA_PATH,
    CameraPreset,
    cube_pose_envelope,
    default_view_preset,
    focus_preset_from_bounds,
    orbit_eye,
    write_camera_layer,
    write_camera_lens,
)
from r17_robot_vision import (
    BEAUTY_OUTPUT,
    R17_RENDER_MODES,
    R17_SEMANTICS_LAYER as R17_SEMANTICS_LAYER_RELATIVE,
    SEMANTIC_ID_MAP_OUTPUT,
    SEMANTIC_OUTPUT,
    candy_colorize_semantic_ids,
    copy_numpy_bgra_to_stream,
    query_attic_environment_roots,
    semantic_ids_from_frame,
    update_semantic_id_map,
    write_r17_semantics_layer,
)
from r17_lidar import (
    R17_LIDAR_CHANNELS,
    R17_LIDAR_LAYER as R17_LIDAR_LAYER_RELATIVE,
    R17_LIDAR_POINTCLOUD_OUTPUT,
    R17_LIDAR_RENDER_PRODUCT,
    R17_LIDAR_SENSOR_PATH,
    camera_projected_lidar_preview,
    fallback_lidar_density_preview,
    lidar_points_to_world,
    matrix_from_lidar_eye_target,
    overlay_lidar_preview,
    parse_lidar_pointcloud,
    query_unlabeled_lidar_material_paths,
    write_r17_lidar_layer,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION_ROOT = ROOT.parent
ARTIFACT_DIR = ROOT / "artifacts"
CAMERA_LAYER = ROOT / "usd" / "R17_Camera.usda"
SEMANTICS_LAYER = ROOT / R17_SEMANTICS_LAYER_RELATIVE
LIDAR_LAYER = ROOT / R17_LIDAR_LAYER_RELATIVE
BASE_STAGE = SESSION_ROOT / "Attic_NVIDIA" / "Attic_NVIDIA.usd"
DEFAULT_STAGE = SESSION_ROOT / "Attic_NVIDIA" / "OldAttic_Mission.usda"
CAMERA_PATH = "/OVCamera"
RENDER_PRODUCT = "/Render/OVServer/ViewportTexture0"
H_APERTURE = 20.955

MEMORY_CUBE_PATH = "/Root/Workshop/Cube"
MEMORY_CUBE_GLOW_PATH = "/Root/Workshop/MemoryCubeGlow"
EXPECTED_MEMORY_ROLE = "Memory Cube"
POSE_OFFSETS = {"LEFT": -15.0, "HOME": 0.0, "RIGHT": 15.0}
R17_COMMAND_EVENT = "r17-command-v1"
R17_STATE_EVENT = "r17-state-v1"
R17_STATUSES = {"WAITING", "APPLYING", "READY", "ERROR"}
R17_POSE_COMMAND = "cube.setPose"
R17_VIEW_COMMAND = "camera.setView"
R17_STATE_COMMAND = "r17.getState"
R17_RENDER_COMMAND = "render.setMode"
R17_LIDAR_COMMAND = "lidar.setEnabled"
R17_VALID_OFFSETS = {-15, 0, 15}
R17_PRESET_VIEWS = ("DEFAULT", "CUBE_FOCUS")
R17_VIEWS = R17_PRESET_VIEWS + ("CUSTOM",)
CUBE_DEFAULT_HALF_EXTENT = (20.0, 20.0, 20.0)
R17_TRANSITION_SECONDS = 0.45
R17_DEFAULT_RENDER_MODE = "BEAUTY"
CUBE_SEMANTIC_CLASS = "retrieval_target"
CUBE_SEMANTIC_LABEL = "memory_cube"
ENVIRONMENT_SEMANTIC_CLASS = "attic_environment"
R17_SEEN_REQUEST_LIMIT = 512
R17_LIDAR_DEFAULT_STATUS = "DISABLED"


@wp.kernel
def rgba_to_bgra(src: wp.array3d(dtype=wp.uint8), dst: wp.array3d(dtype=wp.uint8)):
    y, x, c = wp.tid()
    if c == 0:
        dst[y, x, c] = src[y, x, 2]
    elif c == 1:
        dst[y, x, c] = src[y, x, 1]
    elif c == 2:
        dst[y, x, c] = src[y, x, 0]
    else:
        dst[y, x, c] = src[y, x, 3]


def resolve_stage_path(path: str | Path) -> Path:
    p = Path(path).expanduser().resolve()
    if p.is_dir():
        usd = p / "Attic_NVIDIA.usd"
        if usd.exists():
            return usd
    return p


def make_composite_stage(
    scene_path: Path,
    width: int,
    height: int,
    camera_layer: Path = CAMERA_LAYER,
    semantics_layer: Path = SEMANTICS_LAYER,
    lidar_layer: Path = LIDAR_LAYER,
) -> str:
    base_ref = str(BASE_STAGE.expanduser().resolve()).replace("\\", "/")
    scene_ref = str(scene_path.expanduser().resolve()).replace("\\", "/")
    # The viewer-owned camera, semantics, and LiDAR layers compose above the
    # protected scene layers, so R17CubeFocus, the SemanticsAPI overs, the
    # R17Lidar sensor, and the nonvisual material defaults are always the
    # strongest opinions and the user USD stays untouched on disk.
    camera_ref = str(Path(camera_layer).expanduser().resolve()).replace("\\", "/")
    semantics_ref = str(Path(semantics_layer).expanduser().resolve()).replace("\\", "/")
    lidar_ref = str(Path(lidar_layer).expanduser().resolve()).replace("\\", "/")
    v_aperture = H_APERTURE * float(height) / float(width)
    return f'''#usda 1.0
(
    customLayerData = {{
        bool populateAllAuthoredAttributes = true
    }}
    subLayers = [
        @{camera_ref}@,
        @{semantics_ref}@,
        @{lidar_ref}@,
        @{base_ref}@,
        @{scene_ref}@
    ]
    defaultPrim = "Session"
)

def Camera "OVCamera"
{{
    float2 clippingRange = (1, 10000000)
    float focalLength = 24
    float horizontalAperture = {H_APERTURE:.3f}
    float verticalAperture = {v_aperture:.4f}
    token projection = "perspective"
    double3 xformOp:translate = (-620, -1580, 280)
    uniform token[] xformOpOrder = ["xformOp:translate"]
}}

def "Render"
{{
    def "OVServer"
    {{
        def RenderProduct "ViewportTexture0" (
            prepend apiSchemas = ["OmniRtxSettingsCommonAdvancedAPI_1", "OmniRtxSettingsPtAdvancedAPI_1", "OmniRtxSettingsRtAdvancedAPI_1"]
        )
        {{
            string omni:rtx:rendermode = "RealTimePathTracing"
            int omni:rtx:rtpt:maxBounces = 3
            int omni:rtx:rtpt:maxSpecularAndTransmissionBounces = 3
            bool omni:rtx:rtpt:fireflyFilter:enabled = true
            rel camera = <{CAMERA_PATH}>
            rel orderedVars = [
                </Render/Vars/LdrColor>,
                </Render/Vars/SemanticSegmentation>,
                </Render/Vars/SemanticIdMap>
            ]
            uniform int2 resolution = ({int(width)}, {int(height)})
        }}
    }}

    def "Vars"
    {{
        def RenderVar "LdrColor"
        {{
            uniform string sourceName = "LdrColor"
        }}

        def RenderVar "SemanticSegmentation"
        {{
            string sourceName = "SemanticSegmentation"
        }}

        def RenderVar "SemanticIdMap"
        {{
            string sourceName = "SemanticIdMap"
        }}
    }}

    def RenderSettings "OVRenderSettings"
    {{
        rel products = [<{RENDER_PRODUCT}>]
    }}
}}
'''


def decode_app_message(raw: Any) -> dict[str, Any] | None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        msg = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None

    if not isinstance(msg, dict):
        return None

    if "messageType" in msg and "data" in msg:
        try:
            data = msg["data"]
            msg = json.loads(data) if isinstance(data, str) else data
        except Exception:
            return None
        if not isinstance(msg, dict):
            return None

    if not isinstance(msg.get("event_type"), str):
        return None

    payload = msg.get("payload")
    msg["payload"] = payload if isinstance(payload, dict) else {}
    return msg


def send_json(server: ovstream.Server | None, event_type: str, payload: dict[str, Any]) -> None:
    if server is None or not getattr(server, "is_client_connected", False):
        return
    event = {"event_type": event_type, "payload": payload}
    wrapped = {
        "messageRecipient": "app",
        "messageType": "json",
        "data": json.dumps(event, default=str),
    }
    try:
        server.send_message(json.dumps(wrapped, default=str))
    except Exception:
        logging.debug("Dropped event during disconnect: %s", event_type, exc_info=True)


def matrix_to_rows(matrix: np.ndarray | None) -> list[list[float]]:
    if matrix is None:
        return []
    return [[float(value) for value in row] for row in np.asarray(matrix, dtype=np.float64).reshape(4, 4)]


def transform_from_translate(values: np.ndarray) -> np.ndarray:
    matrix = np.eye(4, dtype=np.float64)
    matrix[3, 0:3] = np.asarray(values, dtype=np.float64).reshape(-1)[0:3]
    return matrix


def query_exact_memory_cube(renderer: ovrtx.Renderer) -> tuple[str, str]:
    prims = renderer.query_prims(
        attribute_filter_mode=ovrtx.AttributeFilterMode.SPECIFIC,
        attribute_names=["mission:role"],
    )
    role_paths = [path for path, attrs in prims.items() if "mission:role" in attrs]
    role_tensors = renderer.read_array_attribute("mission:role", role_paths)
    matches: list[tuple[str, str]] = []
    for path in role_paths:
        role_bytes = np.array(np.from_dlpack(role_tensors[path]))
        role = bytes(role_bytes.tolist()).decode("utf-8")
        if role == EXPECTED_MEMORY_ROLE:
            matches.append((path, role))
    if matches != [(MEMORY_CUBE_PATH, EXPECTED_MEMORY_ROLE)]:
        raise RuntimeError(f"expected exactly one Memory Cube at {MEMORY_CUBE_PATH}, found {matches}")
    return matches[0]


def read_first_matrix_attribute(renderer: ovrtx.Renderer, prim_path: str) -> np.ndarray:
    prims = renderer.query_prims(attribute_filter_mode=ovrtx.AttributeFilterMode.NONE)
    if prim_path not in prims:
        raise RuntimeError(f"prim not found: {prim_path}")

    for attribute_name in ("omni:xform", "omni:fabric:localMatrix", "omni:fabric:worldMatrix"):
        try:
            values = np.asarray(np.from_dlpack(renderer.read_attribute(attribute_name, [prim_path])), dtype=np.float64)
        except Exception:
            continue
        if values.size == 16:
            matrix = values.reshape(1, 4, 4)[0]
            if np.isfinite(matrix).all():
                return matrix.copy()

    try:
        values = np.asarray(np.from_dlpack(renderer.read_attribute("xformOp:translate", [prim_path])), dtype=np.float64)
        if values.size >= 3 and np.isfinite(values).all():
            return transform_from_translate(values)
    except Exception:
        pass

    raise RuntimeError(f"no finite transform attribute found for {prim_path}")


def bind_xform(renderer: ovrtx.Renderer, prim_path: str) -> Any:
    return renderer.bind_attribute(
        prim_paths=[prim_path],
        attribute_name="omni:xform",
        dtype="float64",
        semantic=ovrtx.Semantic.XFORM_MAT4x4,
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )


def pose_target_from_home(home: np.ndarray, pose: str) -> tuple[np.ndarray, int]:
    normalized_pose = pose.upper()
    if normalized_pose not in POSE_OFFSETS:
        raise ValueError(f"unsupported pose: {pose}")
    offset = POSE_OFFSETS[normalized_pose]
    target = np.asarray(home, dtype=np.float64).copy().reshape(4, 4)
    target[3, 0] = float(home[3, 0]) + offset
    return target, int(offset)


def interpolate_translation_only(start: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    """Linear translation blend that copies rotation and scale from the target."""

    alpha = max(0.0, min(1.0, float(alpha)))
    result = np.asarray(target, dtype=np.float64).copy().reshape(4, 4)
    start_translate = np.asarray(start, dtype=np.float64).reshape(4, 4)[3, 0:3]
    target_translate = result[3, 0:3].copy()
    result[3, 0:3] = start_translate + (target_translate - start_translate) * alpha
    return result


def translate_by_delta(base: np.ndarray, delta_xyz: np.ndarray) -> np.ndarray:
    matrix = np.asarray(base, dtype=np.float64).copy().reshape(4, 4)
    matrix[3, 0:3] = matrix[3, 0:3] + np.asarray(delta_xyz, dtype=np.float64).reshape(3)
    return matrix


def usd_world_transform(stage: Usd.Stage, prim_path: str) -> np.ndarray:
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid() or not prim.IsA(UsdGeom.Xformable):
        raise RuntimeError(f"USD prim is not xformable: {prim_path}")
    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    xform = np.array(matrix, dtype=np.float64).reshape(4, 4)
    if not np.isfinite(xform).all():
        raise RuntimeError(f"USD transform contains non-finite values: {prim_path}")
    return xform


def usd_world_half_extent(stage: Usd.Stage, prim_path: str) -> np.ndarray:
    """World-space half size of a prim, used for the cube focus envelope."""

    prim = stage.GetPrimAtPath(prim_path)
    if prim and prim.IsValid():
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
        aligned = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not aligned.IsEmpty():
            size = np.array(aligned.GetSize(), dtype=np.float64).reshape(3) * 0.5
            if np.isfinite(size).all() and (size > 0.0).all():
                return size
    return np.asarray(CUBE_DEFAULT_HALF_EXTENT, dtype=np.float64)


def query_cube_focus_inputs(stage_path: Path, cube_path: str) -> tuple[np.ndarray, np.ndarray]:
    """Return the cube's home world transform and world half extent."""

    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise RuntimeError(f"could not open USD stage: {stage_path}")
    return usd_world_transform(stage, cube_path), usd_world_half_extent(stage, cube_path)


def query_root_prim_from_usd(stage_path: Path) -> str:
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        return "/Root"
    default_prim = stage.GetDefaultPrim()
    if default_prim and default_prim.IsValid():
        return str(default_prim.GetPath())
    for child in stage.GetPseudoRoot().GetChildren():
        return str(child.GetPath())
    return "/"


def query_memory_cube_from_usd(stage_path: Path) -> tuple[str, str, np.ndarray, np.ndarray | None]:
    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise RuntimeError(f"could not open USD stage: {stage_path}")

    matches: list[tuple[str, str]] = []
    for prim in stage.Traverse():
        attr = prim.GetAttribute("mission:role")
        if not attr:
            continue
        role = attr.Get()
        if role == EXPECTED_MEMORY_ROLE:
            matches.append((str(prim.GetPath()), role))

    if len(matches) == 1:
        cube_path, role = matches[0]
    elif len(matches) > 1:
        raise RuntimeError(f"expected one Memory Cube, found {matches}")
    else:
        prim = stage.GetPrimAtPath(MEMORY_CUBE_PATH)
        if not prim or not prim.IsValid():
            raise RuntimeError(f"Memory Cube prim not found: {MEMORY_CUBE_PATH}")
        cube_path, role = MEMORY_CUBE_PATH, EXPECTED_MEMORY_ROLE

    glow_transform = None
    glow = stage.GetPrimAtPath(MEMORY_CUBE_GLOW_PATH)
    if glow and glow.IsValid() and glow.IsA(UsdGeom.Xformable):
        glow_transform = usd_world_transform(stage, MEMORY_CUBE_GLOW_PATH)

    return cube_path, role, usd_world_transform(stage, cube_path), glow_transform


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            if self.server.ready_event.is_set():
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"not ready")
            return
        if self.path == "/state.json":
            payload = json.dumps(self.server.state_fn(), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        logging.debug("health: " + fmt, *args)


class AtticPortalServer:
    def __init__(self, stage_path: Path, width: int, height: int, fps: int, signaling_port: int, health_port: int, public_ip: str):
        self.stage_path = resolve_stage_path(stage_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.signaling_port = int(signaling_port)
        self.health_port = int(health_port)
        self.public_ip = public_ip
        self.ready_event = threading.Event()
        self.stop_event = threading.Event()
        self.commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.camera = OrbitCamera(self.width, self.height)
        self.viewport_input_active = True
        self.renderer: ovrtx.Renderer | None = None
        self.stream: ovstream.Server | None = None
        self.bgra = None
        self.first_frame_logged = False
        self.frame_index = 0
        self.current_stage_root_path = "/Root"
        self.mission_cube_matches: list[tuple[str, str]] = []
        self.r17_runtime_query = "pending"
        self.last_error = ""
        self.r17_cube_path = ""
        self.r17_requested_pose = "HOME"
        self.r17_offset_x = 0
        self.r17_status = "WAITING"
        self.r17_message = "Waiting for Memory Cube Link"
        self.r17_error = ""
        self.r17_transition_active = False
        self.r17_home_transform: np.ndarray | None = None
        self.r17_current_transform: np.ndarray | None = None
        self.r17_xform_binding: Any | None = None
        self.r17_glow_home_transform: np.ndarray | None = None
        self.r17_glow_current_transform: np.ndarray | None = None
        self.r17_glow_xform_binding: Any | None = None
        self.r17_seen_request_ids: set[str] = set()
        self.r17_active_request_id: str | None = None
        self.r17_transition_duration = R17_TRANSITION_SECONDS
        self.r17_transition_started_at = 0.0
        self.r17_transition_start: np.ndarray | None = None
        self.r17_transition_target: np.ndarray | None = None
        self.r17_glow_transition_start: np.ndarray | None = None
        self.r17_glow_transition_target: np.ndarray | None = None
        self.r17_pending_ready_request_id: str | None = None
        self.r17_active_view = "DEFAULT"
        self.r17_view_presets: dict[str, CameraPreset] = {}
        self.r17_active_camera_preset: CameraPreset | None = None
        self.r17_focus_bounds_min: np.ndarray | None = None
        self.r17_focus_bounds_max: np.ndarray | None = None
        self.r17_focus_camera_path = R17_FOCUS_CAMERA_PATH
        self.r17_camera_layer = CAMERA_LAYER
        self.r17_active_view_request_id: str | None = None
        self.r17_pending_view_request_id: str | None = None
        self.r17_pending_custom_broadcast = False
        # Robot Vision. One renderer, one RenderProduct, one stream buffer: the
        # mode only selects which ovrtx output is converted into self.bgra.
        self.r17_semantics_layer = SEMANTICS_LAYER
        self.r17_render_mode = R17_DEFAULT_RENDER_MODE
        self.r17_available_outputs = [BEAUTY_OUTPUT, SEMANTIC_OUTPUT, SEMANTIC_ID_MAP_OUTPUT]
        self.r17_output_keys: list[str] = []
        self.r17_semantic_id_map: dict[int, str] = {}
        self.r17_semantic_unique_ids: list[int] = []
        self.r17_semantic_nonzero_pixels = 0
        self.r17_semantic_label_count = 0
        self.r17_cube_semantic_class = CUBE_SEMANTIC_CLASS
        self.r17_cube_semantic_label = CUBE_SEMANTIC_LABEL
        self.r17_active_render_request_id: str | None = None
        self.r17_pending_render_request_id: str | None = None
        self.r17_render_frame_error = ""
        # R-17 LiDAR Link. The OmniLidar sensor and its PointCloud RenderProduct
        # live in the viewer-owned LiDAR layer. Enabling LiDAR only adds that
        # RenderProduct to the existing renderer's step set; the renderer, the
        # camera RenderProduct, the BGRA stream buffer, and the WebRTC
        # connection are all reused unchanged.
        self.r17_lidar_layer = LIDAR_LAYER
        self.r17_lidar_enabled = False
        self.r17_lidar_status = R17_LIDAR_DEFAULT_STATUS
        self.r17_lidar_valid_point_count: int | None = None
        self.r17_lidar_nearest_range: float | None = None
        self.r17_lidar_error = ""
        self.r17_lidar_output_keys: list[str] = []
        self.r17_lidar_nonvisual_material_paths: list[str] = []
        self.r17_lidar_points_sensor: np.ndarray | None = None
        self.r17_lidar_intensity: np.ndarray | None = None
        self.r17_lidar_object_colors: np.ndarray | None = None
        self.r17_lidar_preview_bgra: np.ndarray | None = None
        self.r17_lidar_camera_preview_bgra: np.ndarray | None = None
        self.r17_lidar_sensor_matrix: np.ndarray | None = None
        self.r17_lidar_history_sensor: list[np.ndarray] = []
        self.r17_lidar_history_world: list[np.ndarray] = []
        self.r17_lidar_history_colors: list[np.ndarray] = []
        self.r17_lidar_preview_frame = -1
        self.r17_lidar_preview_interval_frames = max(2, self.fps // 10)
        self.r17_lidar_miss_count = 0
        self.r17_active_lidar_request_id: str | None = None
        self.r17_pending_lidar_request_id: str | None = None
        self.r17_pending_lidar_request_frame = -1
        self.artifact_frame = ARTIFACT_DIR / "attic-portal-first-frame.png"
        self.composite_stage = ARTIFACT_DIR / "attic-portal-composite.usda"
        self.renderer_create_count = 0
        self.stage_open_count = 0
        self.stream_start_count = 0

    def state(self) -> dict[str, Any]:
        return {
            "ready": self.ready_event.is_set(),
            "stage": str(self.stage_path),
            "root_prim_path": self.current_stage_root_path,
            # Counted at construction, not asserted: LIDAR ON/OFF must leave
            # all three at 1 and never reopen the composite stage.
            "renderer_owner_count": self.renderer_create_count,
            "stage_open_count": self.stage_open_count,
            "stream_start_count": self.stream_start_count,
            "mission_cube_matches": self.mission_cube_matches,
            "runtime_mission_role_query": self.r17_runtime_query,
            "camera": CAMERA_PATH,
            "camera_state": {"azimuth": self.camera.azimuth, "elevation": self.camera.elevation, "distance": self.camera.distance, "target": [float(v) for v in self.camera.target]},
            "render_product": RENDER_PRODUCT,
            "resolution": {"width": self.width, "height": self.height},
            "frame_index": self.frame_index,
            "first_frame": str(self.artifact_frame),
            "last_error": self.last_error,
            "camera_presets": self.camera_presets_payload(),
            "robot_vision": self.robot_vision_payload(),
            "lidar": self.lidar_payload(),
            "r17": self.r17_state_payload(request_id="state.json"),
        }

    def camera_presets_payload(self) -> dict[str, Any]:
        def orbit(preset: CameraPreset | None) -> dict[str, Any] | None:
            if preset is None:
                return None
            return {
                "target": [float(v) for v in preset.target],
                "distance": float(preset.distance),
                "azimuth": float(preset.azimuth),
                "elevation": float(preset.elevation),
                "focalLength": float(preset.focal_length),
                "horizontalAperture": float(preset.horizontal_aperture),
                "verticalAperture": float(preset.vertical_aperture),
                "clippingRange": [float(v) for v in preset.clipping_range],
            }

        return {
            "activeView": self.r17_active_view,
            "focusCameraPath": self.r17_focus_camera_path,
            "cameraLayer": str(self.r17_camera_layer),
            "activeViewerCamera": ACTIVE_VIEWER_CAMERA_PATH,
            "focusBoundsMin": [] if self.r17_focus_bounds_min is None else [float(v) for v in self.r17_focus_bounds_min],
            "focusBoundsMax": [] if self.r17_focus_bounds_max is None else [float(v) for v in self.r17_focus_bounds_max],
            "poseOffsets": sorted(int(v) for v in POSE_OFFSETS.values()),
            "DEFAULT": orbit(self.r17_view_presets.get("DEFAULT")),
            "CUBE_FOCUS": orbit(self.r17_view_presets.get("CUBE_FOCUS")),
        }

    def robot_vision_payload(self) -> dict[str, Any]:
        """Server-authoritative Robot Vision readout.

        outputKeys are the render var keys ovrtx actually produced on the last
        extracted frame, not the keys the composite stage requested.
        """

        return {
            "renderMode": self.r17_render_mode,
            "availableOutputs": list(self.r17_available_outputs),
            "outputKeys": list(self.r17_output_keys),
            "semanticsLayer": str(self.r17_semantics_layer),
            "semanticIdMap": {str(key): value for key, value in self.r17_semantic_id_map.items()},
            "semanticUniqueIds": list(self.r17_semantic_unique_ids),
            "semanticNonzeroPixels": int(self.r17_semantic_nonzero_pixels),
            "semanticLabelCount": int(self.r17_semantic_label_count),
            "cubeSemanticClass": self.r17_cube_semantic_class,
            "cubeSemanticLabel": self.r17_cube_semantic_label,
        }

    def lidar_payload(self) -> dict[str, Any]:
        """Server-authoritative R-17 LiDAR Link readout.

        outputKeys are the render var keys the LiDAR RenderProduct actually
        produced on the last step, not the keys the layer requested.
        nonvisualMaterialCount is the number of protected-scene Material prims
        this viewer authored default nonvisual sensor-return labels for.
        """

        return {
            "enabled": self.r17_lidar_enabled,
            "status": self.r17_lidar_status,
            "sensorPath": R17_LIDAR_SENSOR_PATH,
            "renderProduct": R17_LIDAR_RENDER_PRODUCT,
            "pointCloudOutput": R17_LIDAR_POINTCLOUD_OUTPUT,
            "layer": str(self.r17_lidar_layer),
            "requestedChannels": list(R17_LIDAR_CHANNELS),
            "nonvisualMaterialCount": len(self.r17_lidar_nonvisual_material_paths),
            "validPointCount": self.r17_lidar_valid_point_count,
            "nearestRange": self.r17_lidar_nearest_range,
            "outputKeys": list(self.r17_lidar_output_keys),
            "error": self.r17_lidar_error,
        }

    def active_output_name(self) -> str:
        return SEMANTIC_OUTPUT if self.r17_render_mode == "SEMANTIC" else BEAUTY_OUTPUT

    def start_health(self) -> None:
        httpd = HTTPServer(("0.0.0.0", self.health_port), HealthHandler)
        httpd.ready_event = self.ready_event
        httpd.state_fn = self.state
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        logging.info("Health endpoint: http://127.0.0.1:%d/healthz", self.health_port)

    def prepare_camera_presets(self) -> None:
        """Derive both presets and author the viewer-owned camera layer.

        Runs before the composite stage is opened so /Session/Cameras/R17CubeFocus
        is present in the very first composed stage. Reads USD only; the
        protected scene is never written.
        """

        aspect = float(self.height) / float(self.width)
        fitted = OrbitCamera(self.width, self.height)
        fitted.fit_attic()
        default_preset = default_view_preset(
            aspect=aspect,
            target=[float(v) for v in fitted.target],
            distance=float(fitted.distance),
            azimuth=float(fitted.azimuth),
            elevation=float(fitted.elevation),
        )

        try:
            cube_path, _, _, _ = query_memory_cube_from_usd(self.stage_path)
            home_transform, half_extent = query_cube_focus_inputs(self.stage_path, cube_path)
        except Exception as exc:
            # Keep the stage loadable. verify_memory_cube() still fails loudly
            # when the mission cube is genuinely missing.
            self.last_error = str(exc)
            logging.warning("Cube focus envelope fell back to the fitted target: %s", exc)
            home_transform = transform_from_translate(np.asarray(default_preset.target, dtype=np.float64))
            half_extent = np.asarray(CUBE_DEFAULT_HALF_EXTENT, dtype=np.float64)
        bounds_min, bounds_max = cube_pose_envelope(home_transform, half_extent, POSE_OFFSETS.values())
        focus_preset = focus_preset_from_bounds(bounds_min, bounds_max, aspect=aspect)

        self.r17_focus_bounds_min = bounds_min
        self.r17_focus_bounds_max = bounds_max
        self.r17_view_presets = {"DEFAULT": default_preset, "CUBE_FOCUS": focus_preset}

        write_camera_layer(self.r17_camera_layer, focus_preset, self.r17_focus_camera_path)
        logging.info(
            "Authored viewer-owned camera layer %s: %s target=%s distance=%.3f bounds=%s..%s",
            self.r17_camera_layer,
            self.r17_focus_camera_path,
            [round(float(v), 3) for v in focus_preset.target],
            focus_preset.distance,
            [float(v) for v in bounds_min],
            [float(v) for v in bounds_max],
        )

        self.apply_camera_preset(default_preset)
        self.r17_active_view = "DEFAULT"

    def apply_camera_preset(self, preset: CameraPreset) -> None:
        """writing-transforms drives the pose through the orbit controller so
        native orbit, pan, and zoom keep working from the preset."""

        self.camera.target = np.asarray(preset.target, dtype=np.float64).copy()
        self.camera.distance = float(preset.distance)
        self.camera.azimuth = float(preset.azimuth)
        self.camera.elevation = float(preset.elevation)
        self.camera.cancel_interaction()
        self.camera.sanitize()
        # The LiDAR inset projects through the lens that was last applied to the
        # active viewer camera, so native orbit/pan/zoom keeps the same lens.
        self.r17_active_camera_preset = preset

    def prepare_semantics_layer(self) -> None:
        """Author the viewer-owned SemanticsAPI layer before the stage is opened.

        semantic-labels: label the scene object roots, never the RenderProduct
        or RenderVar prims, and keep the labels in an `over` layer so the
        protected Attic USD is never written.
        """

        environment_paths = query_attic_environment_roots(BASE_STAGE)
        if not environment_paths:
            # Keep the viewer loadable, but make the missing per-object labels
            # loud: SEMANTIC would otherwise render one flat colour.
            self.last_error = f"no /Root/Geometry children to label in {BASE_STAGE}"
            logging.error("R-17 semantics: %s", self.last_error)
        write_r17_semantics_layer(
            self.r17_semantics_layer,
            root_path="/Root",
            cube_path=MEMORY_CUBE_PATH,
            environment_paths=environment_paths,
        )
        self.r17_semantic_label_count = len(environment_paths) + 1
        logging.info(
            "Authored viewer-owned semantics layer %s: %d /Root/Geometry/* %s labels + %s/%s on %s",
            self.r17_semantics_layer,
            len(environment_paths),
            ENVIRONMENT_SEMANTIC_CLASS,
            self.r17_cube_semantic_class,
            self.r17_cube_semantic_label,
            MEMORY_CUBE_PATH,
        )

    def discover_lidar_nonvisual_materials(self) -> None:
        """Read-only scan of the protected scene for unlabeled Material prims.

        nonvisual-materials: RTX LiDAR return metadata belongs on the bound
        `Material` prims, never on `Mesh` prims, and RTX LiDAR visibility comes
        from renderable USD geometry, so no PhysX collision or rigid-body
        schemas are added here. Materials that already carry a source nonvisual
        base label under either supported prefix are skipped, so a scene-
        authored sensor-return label always wins.
        """

        self.r17_lidar_nonvisual_material_paths = query_unlabeled_lidar_material_paths(
            [self.stage_path, BASE_STAGE]
        )
        if not self.r17_lidar_nonvisual_material_paths:
            # Make a silently empty material set loud: every LiDAR return would
            # otherwise fall back to one unlabeled default surface.
            self.last_error = f"no unlabeled Material prims found in {BASE_STAGE}"
            logging.error("R-17 LiDAR: %s", self.last_error)
        logging.info(
            "R-17 LiDAR nonvisual material defaults resolved: %d unlabeled Material prims",
            len(self.r17_lidar_nonvisual_material_paths),
        )

    def prepare_lidar_layer(self, *, active: bool) -> None:
        """Author the viewer-owned LiDAR layer; never write the protected scene.

        configuring-lidar-sensors: the OmniLidar prim starts from the active
        camera preset with sensor +X forward, keeps SENSOR frame NONCOMPENSATED
        instant complete output, and the RenderProduct exposes one PointCloud
        RenderVar. `active = false` keeps the sensor and its RenderProduct out
        of the composed stage while LiDAR is off.
        """

        preset = self.active_camera_preset()
        lidar_matrix = matrix_from_lidar_eye_target(
            orbit_eye(preset), np.asarray(preset.target, dtype=np.float64)
        )
        write_r17_lidar_layer(
            self.r17_lidar_layer,
            lidar_matrix,
            active=active,
            material_paths=self.r17_lidar_nonvisual_material_paths,
        )
        self.r17_lidar_sensor_matrix = lidar_matrix.copy() if active else None
        logging.info(
            "Authored viewer-owned LiDAR layer %s: active=%s sensor=%s product=%s materials=%d",
            self.r17_lidar_layer,
            active,
            R17_LIDAR_SENSOR_PATH,
            R17_LIDAR_RENDER_PRODUCT,
            len(self.r17_lidar_nonvisual_material_paths),
        )

    def active_camera_preset(self) -> CameraPreset:
        """Lens and pose source for the LiDAR sensor and the inset projection."""

        preset = self.r17_active_camera_preset or self.r17_view_presets.get("DEFAULT")
        if preset is None:
            raise RuntimeError("camera presets are not initialized")
        return preset

    def composite_stage_usda(self) -> str:
        return make_composite_stage(
            self.stage_path,
            self.width,
            self.height,
            self.r17_camera_layer,
            self.r17_semantics_layer,
            self.r17_lidar_layer,
        )

    def set_lidar_enabled(self, enabled: bool) -> None:
        """Gate the LiDAR RenderProduct in the step set; never reopen the stage.

        The sensor and its RenderProduct are composed once at startup. An
        OmniLidar that is not in the step set produces no scans, so toggling
        only changes whether render_loop() adds the product. Reopening the
        composite stage would recompile every scene material on each toggle.
        """

        self.r17_lidar_enabled = bool(enabled)
        if enabled:
            self.r17_lidar_miss_count = 0
            self.write_lidar_sensor()

    def clear_lidar_runtime(self) -> None:
        """Drop every cached LiDAR reading so OFF cannot report stale telemetry."""

        self.r17_lidar_valid_point_count = None
        self.r17_lidar_nearest_range = None
        self.r17_lidar_output_keys = []
        self.r17_lidar_preview_bgra = None
        self.r17_lidar_camera_preview_bgra = None
        self.r17_lidar_points_sensor = None
        self.r17_lidar_intensity = None
        self.r17_lidar_object_colors = None
        self.r17_lidar_history_sensor = []
        self.r17_lidar_history_world = []
        self.r17_lidar_history_colors = []
        self.r17_lidar_sensor_matrix = None
        self.r17_lidar_preview_frame = -1
        self.r17_lidar_miss_count = 0
        self.r17_lidar_error = ""

    def load_stage(self) -> None:
        if not self.stage_path.exists():
            raise FileNotFoundError(f"Stage not found: {self.stage_path}")
        self.prepare_camera_presets()
        self.prepare_semantics_layer()
        self.discover_lidar_nonvisual_materials()
        # Composed active once; LIDAR ON/OFF only gates the step set.
        self.prepare_lidar_layer(active=True)
        usda = self.composite_stage_usda()
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        self.composite_stage.write_text(usda, encoding="utf-8")
        logging.info("Opening viewer-owned composite stage: %s", self.composite_stage)
        assert self.renderer is not None
        self.renderer.open_usd_from_string(usda)
        self.stage_open_count += 1
        self.current_stage_root_path = query_root_prim_from_usd(self.stage_path)
        self.write_camera()

    def verify_memory_cube(self) -> None:
        cube_path, role, _, _ = query_memory_cube_from_usd(self.stage_path)
        if (cube_path, role) != (MEMORY_CUBE_PATH, EXPECTED_MEMORY_ROLE):
            raise RuntimeError(
                f"expected exactly one Memory Cube at {MEMORY_CUBE_PATH}, "
                f"found {(cube_path, role)}"
            )
        # Cross-check the loaded runtime stage. The USD query above is the
        # authoritative source for the HOME transform; this asserts the
        # renderer sees the same single mission:role prim.
        assert self.renderer is not None
        try:
            runtime_match = query_exact_memory_cube(self.renderer)
        except Exception as exc:
            self.r17_runtime_query = f"unavailable: {exc}"
            logging.warning("Runtime mission:role query unavailable: %s", exc)
        else:
            if runtime_match != (cube_path, role):
                raise RuntimeError(
                    f"runtime Memory Cube query {runtime_match} does not match USD {(cube_path, role)}"
                )
            self.r17_runtime_query = "ok"
            logging.info("Runtime mission:role query matched: %s", runtime_match)
        self.mission_cube_matches = [(cube_path, role)]
        logging.info("Mission cube verified: path=%s role=%s", cube_path, role)

    def initialize_r17_memory_cube(self) -> None:
        assert self.renderer is not None
        try:
            cube_path, _, home_transform, glow_transform = query_memory_cube_from_usd(self.stage_path)
            self.r17_cube_path = cube_path
            self.r17_home_transform = home_transform
            self.r17_current_transform = self.r17_home_transform.copy()
            self.r17_xform_binding = bind_xform(self.renderer, cube_path)
            self.write_bound_xform(self.r17_xform_binding, self.r17_current_transform)

            if glow_transform is not None:
                try:
                    self.r17_glow_home_transform = glow_transform
                    self.r17_glow_current_transform = self.r17_glow_home_transform.copy()
                    self.r17_glow_xform_binding = bind_xform(self.renderer, MEMORY_CUBE_GLOW_PATH)
                    self.write_bound_xform(self.r17_glow_xform_binding, self.r17_glow_current_transform)
                except Exception:
                    self.r17_glow_home_transform = None
                    self.r17_glow_current_transform = None
                    self.r17_glow_xform_binding = None
                    logging.debug("R-17 glow binding skipped", exc_info=True)

            self.r17_requested_pose = "HOME"
            self.r17_offset_x = 0
            self.r17_status = "READY"
            self.r17_message = "Memory Cube Link ready"
            self.r17_error = ""
            self.r17_transition_active = False
            logging.info("R-17 Memory Cube Link resolved: %s", cube_path)
        except Exception as exc:
            self.r17_status = "ERROR"
            self.r17_message = "Memory Cube Link failed"
            self.r17_error = str(exc)
            self.last_error = str(exc)
            logging.exception("R-17 Memory Cube initialization failed")

    def write_bound_xform(self, binding: Any, matrix: np.ndarray) -> None:
        xform = np.ascontiguousarray(matrix, dtype=np.float64).reshape(1, 4, 4)
        binding.write(xform)

    def r17_state_payload(
        self,
        *,
        request_id: str,
        status: str | None = None,
        command: str = "r17.getState",
        message: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        current_status = status or self.r17_status
        if current_status not in R17_STATUSES:
            current_status = "ERROR"
        offset_x = int(self.r17_offset_x)
        offset_error = ""
        if offset_x not in R17_VALID_OFFSETS:
            current_status = "ERROR"
            offset_error = f"offsetX must be -15, 0, or +15: {offset_x}"
        active_view = self.r17_active_view
        if active_view not in R17_VIEWS:
            current_status = "ERROR"
            offset_error = offset_error or f"activeView must be one of {R17_VIEWS}: {active_view}"
        render_mode = self.r17_render_mode
        if render_mode not in R17_RENDER_MODES:
            current_status = "ERROR"
            offset_error = offset_error or f"renderMode must be BEAUTY or SEMANTIC: {render_mode}"
        payload: dict[str, Any] = {
            "requestId": request_id,
            "status": current_status,
            "moduleInstalled": bool(self.r17_cube_path),
            "command": command,
            "cubePath": self.r17_cube_path,
            "requestedPose": self.r17_requested_pose,
            "offsetX": offset_x,
            "transitionActive": self.r17_transition_active,
            "activeView": active_view,
            "focusCameraPath": self.r17_focus_camera_path,
            "cameraLayer": str(self.r17_camera_layer),
            "renderMode": render_mode,
            "availableOutputs": list(self.r17_available_outputs),
            "outputKeys": list(self.r17_output_keys),
            "semanticsLayer": str(self.r17_semantics_layer),
            "semanticIdMap": {str(key): value for key, value in self.r17_semantic_id_map.items()},
            "semanticUniqueIds": list(self.r17_semantic_unique_ids),
            "semanticNonzeroPixels": int(self.r17_semantic_nonzero_pixels),
            "cubeSemanticClass": self.r17_cube_semantic_class,
            "cubeSemanticLabel": self.r17_cube_semantic_label,
            "lidarEnabled": self.r17_lidar_enabled,
            "lidarStatus": self.r17_lidar_status,
            "lidarSensorPath": R17_LIDAR_SENSOR_PATH,
            "lidarRenderProduct": R17_LIDAR_RENDER_PRODUCT,
            "lidarLayer": str(self.r17_lidar_layer),
            "lidarRequestedChannels": list(R17_LIDAR_CHANNELS),
            "lidarNonvisualMaterialCount": len(self.r17_lidar_nonvisual_material_paths),
            "validPointCount": self.r17_lidar_valid_point_count,
            "nearestRange": self.r17_lidar_nearest_range,
            "homeTransformRowMajor": matrix_to_rows(self.r17_home_transform),
            "currentTransformRowMajor": matrix_to_rows(self.r17_current_transform),
        }
        final_message = self.r17_message if message is None else message
        final_error = self.r17_error if error is None else error
        final_error = offset_error or final_error
        if final_message:
            payload["message"] = final_message
        if final_error:
            payload["error"] = final_error
        return payload

    def send_r17_state(
        self,
        request_id: str,
        *,
        status: str | None = None,
        command: str = "r17.getState",
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        send_json(
            self.stream,
            R17_STATE_EVENT,
            self.r17_state_payload(
                request_id=request_id,
                status=status,
                command=command,
                message=message,
                error=error,
            ),
        )

    def trim_seen_request_ids(self) -> None:
        if len(self.r17_seen_request_ids) <= R17_SEEN_REQUEST_LIMIT:
            return
        self.r17_seen_request_ids = {self.r17_active_request_id} if self.r17_active_request_id else set()

    def handle_r17_command(self, payload: dict[str, Any]) -> None:
        """Validate one r17-command-v1 command on the renderer-owning loop.

        This queues at most one named-pose intent. It never writes omni:xform
        and never calls renderer.step(); advance_r17_transition() owns writes.
        """

        request_id = str(payload.get("requestId") or "").strip()
        command = str(payload.get("command") or "").strip() or "unknown"
        if not request_id:
            request_id = f"r17-server-{int(time.time() * 1000)}"

        if command == R17_STATE_COMMAND:
            self.send_r17_state(request_id, command=command)
            return

        if command == R17_VIEW_COMMAND:
            self.handle_r17_view_command(request_id, payload)
            return

        if command == R17_RENDER_COMMAND:
            self.handle_r17_render_command(request_id, payload)
            return

        if command == R17_LIDAR_COMMAND:
            self.handle_r17_lidar_command(request_id, payload)
            return

        if command != R17_POSE_COMMAND:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Unsupported R-17 command",
                error=f"unsupported command: {command}",
            )
            return

        if not self.r17_cube_path or self.r17_home_transform is None or self.r17_xform_binding is None:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Memory Cube Link unavailable",
                error=self.r17_error or "Memory Cube Link is not initialized",
            )
            return

        inner = payload.get("payload")
        inner = inner if isinstance(inner, dict) else {}
        raw_pose = inner.get("pose")
        pose = str(raw_pose or "").strip().upper()
        if pose not in POSE_OFFSETS:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Unsupported pose",
                error=f"unsupported pose: {raw_pose!r}",
            )
            return

        # A duplicate requestId acknowledges the current result and never
        # restarts movement or re-derives a target.
        if request_id == self.r17_active_request_id or request_id in self.r17_seen_request_ids:
            progress = "in progress" if self.r17_transition_active else "already applied"
            self.send_r17_state(
                request_id,
                command=command,
                message=f"Duplicate request {request_id} acknowledged; {self.r17_requested_pose} {progress}",
            )
            return

        # Only one cube-pose request may be in flight.
        if self.r17_transition_active or self.r17_active_request_id:
            self.r17_seen_request_ids.add(request_id)
            self.trim_seen_request_ids()
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Another cube pose request is in flight",
                error=f"cube pose request {self.r17_active_request_id} is still in flight",
            )
            return

        # The already-active pose acknowledges the current result without
        # restarting movement or rewriting the transform.
        if pose == self.r17_requested_pose:
            self.r17_seen_request_ids.add(request_id)
            self.trim_seen_request_ids()
            self.send_r17_state(
                request_id,
                status="READY",
                command=command,
                message=f"{pose} pose already active; no movement required",
            )
            return

        try:
            target, offset = pose_target_from_home(self.r17_home_transform, pose)
        except ValueError as exc:
            self.send_r17_state(request_id, status="ERROR", command=command, message="Unsupported pose", error=str(exc))
            return
        if offset not in R17_VALID_OFFSETS:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Unsupported pose offset",
                error=f"offsetX must be -15, 0, or +15: {offset}",
            )
            return

        start = self.r17_current_transform if self.r17_current_transform is not None else self.r17_home_transform
        self.r17_transition_start = np.asarray(start, dtype=np.float64).copy().reshape(4, 4)
        self.r17_transition_target = target
        self.r17_glow_transition_start = None
        self.r17_glow_transition_target = None
        if self.r17_glow_xform_binding is not None and self.r17_glow_home_transform is not None:
            glow_start = (
                self.r17_glow_current_transform
                if self.r17_glow_current_transform is not None
                else self.r17_glow_home_transform
            )
            delta = target[3, 0:3] - np.asarray(self.r17_home_transform, dtype=np.float64).reshape(4, 4)[3, 0:3]
            self.r17_glow_transition_start = np.asarray(glow_start, dtype=np.float64).copy().reshape(4, 4)
            self.r17_glow_transition_target = translate_by_delta(self.r17_glow_home_transform, delta)

        self.r17_active_request_id = request_id
        self.r17_seen_request_ids.add(request_id)
        self.trim_seen_request_ids()
        self.r17_requested_pose = pose
        self.r17_offset_x = int(offset)
        self.r17_status = "APPLYING"
        self.r17_message = f"Applying {pose} pose at offsetX {offset:+d}"
        self.r17_error = ""
        self.r17_transition_active = True
        self.r17_pending_ready_request_id = None
        self.r17_transition_started_at = time.monotonic()
        logging.info("R-17 pose queued: request=%s pose=%s offsetX=%+d", request_id, pose, offset)
        self.send_r17_state(request_id, command=command)

    def handle_r17_view_command(self, request_id: str, payload: dict[str, Any]) -> None:
        """Validate one camera.setView command on the renderer-owning loop.

        A validated preset writes the active viewer camera only. It never adds a
        renderer, RenderProduct, or video track, and never repoints the
        RenderProduct at the authored preset camera.
        """

        command = R17_VIEW_COMMAND
        inner = payload.get("payload")
        inner = inner if isinstance(inner, dict) else {}
        raw_view = inner.get("view")
        view = str(raw_view or "").strip().upper()

        if not self.r17_view_presets:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Camera presets unavailable",
                error=self.r17_error or "camera presets are not initialized",
            )
            return

        if view not in R17_PRESET_VIEWS:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Unsupported view",
                error=f"unsupported view: {raw_view!r}",
            )
            return

        # A duplicate requestId acknowledges the current result and never
        # re-applies a preset.
        if request_id == self.r17_active_view_request_id or request_id in self.r17_seen_request_ids:
            self.send_r17_state(
                request_id,
                command=command,
                message=f"Duplicate request {request_id} acknowledged; {self.r17_active_view} view unchanged",
            )
            return

        # Only one camera view request may be in flight.
        if self.r17_active_view_request_id:
            self.r17_seen_request_ids.add(request_id)
            self.trim_seen_request_ids()
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Another camera view request is in flight",
                error=f"camera view request {self.r17_active_view_request_id} is still in flight",
            )
            return

        preset = self.r17_view_presets[view]
        try:
            self.apply_camera_preset(preset)
            assert self.renderer is not None
            write_camera_lens(self.renderer, ACTIVE_VIEWER_CAMERA_PATH, preset)
        except Exception as exc:
            self.last_error = str(exc)
            logging.exception("R-17 camera preset failed")
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Camera preset failed",
                error=str(exc),
            )
            return

        self.r17_seen_request_ids.add(request_id)
        self.trim_seen_request_ids()
        self.r17_active_view = view
        self.r17_active_view_request_id = request_id
        self.r17_pending_view_request_id = request_id
        self.r17_pending_custom_broadcast = False
        self.r17_status = "APPLYING"
        self.r17_message = f"Applying {view} camera view"
        self.r17_error = ""
        logging.info(
            "R-17 view queued: request=%s view=%s focal=%.3f distance=%.3f",
            request_id,
            view,
            preset.focal_length,
            preset.distance,
        )
        self.send_r17_state(request_id, command=command)

    def complete_r17_view_after_render(self) -> None:
        """Publish READY only after the preset pose reached a rendered frame."""

        request_id = self.r17_pending_view_request_id
        if not request_id:
            return
        self.r17_pending_view_request_id = None
        self.r17_active_view_request_id = None
        if not self.r17_transition_active:
            self.r17_status = "READY"
        self.r17_message = f"{self.r17_active_view} camera view applied"
        self.r17_error = ""
        logging.info("R-17 view applied: request=%s view=%s", request_id, self.r17_active_view)
        self.send_r17_state(request_id, status="READY", command=R17_VIEW_COMMAND)

    def handle_r17_render_command(self, request_id: str, payload: dict[str, Any]) -> None:
        """Validate one render.setMode command on the renderer-owning loop.

        A validated mode only changes which ovrtx output this loop converts into
        the single persistent BGRA stream buffer. It never adds a renderer,
        RenderProduct, RenderVar, stream, or WebRTC track, and it never touches
        the camera or the cube.
        """

        command = R17_RENDER_COMMAND
        inner = payload.get("payload")
        inner = inner if isinstance(inner, dict) else {}
        raw_mode = inner.get("mode")
        mode = str(raw_mode or "").strip().upper()

        # A duplicate requestId acknowledges the current result and never
        # re-applies a mode.
        if request_id == self.r17_active_render_request_id or request_id in self.r17_seen_request_ids:
            self.send_r17_state(
                request_id,
                command=command,
                message=f"Duplicate request {request_id} acknowledged; {self.r17_render_mode} render mode unchanged",
            )
            return

        self.r17_seen_request_ids.add(request_id)
        self.trim_seen_request_ids()

        # An invalid output request falls back safely to BEAUTY.
        if mode not in R17_RENDER_MODES:
            self.r17_render_mode = R17_DEFAULT_RENDER_MODE
            self.r17_render_frame_error = ""
            self.r17_status = "ERROR"
            self.r17_message = f"Robot Vision fell back to {R17_DEFAULT_RENDER_MODE}"
            self.r17_error = f"unsupported render mode: {raw_mode!r}"
            logging.warning("R-17 render mode rejected: request=%s mode=%r", request_id, raw_mode)
            self.send_r17_state(request_id, status="ERROR", command=command)
            return

        # Only one render mode request may be in flight.
        if self.r17_active_render_request_id:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Another render mode request is in flight",
                error=f"render mode request {self.r17_active_render_request_id} is still in flight",
            )
            return

        # The already-active mode acknowledges the current result without
        # re-converting a frame.
        if mode == self.r17_render_mode and self.r17_status == "READY":
            self.send_r17_state(
                request_id,
                status="READY",
                command=command,
                message=f"{mode} render mode already active",
            )
            return

        self.r17_render_mode = mode
        self.r17_render_frame_error = ""
        self.r17_active_render_request_id = request_id
        self.r17_pending_render_request_id = request_id
        self.r17_status = "APPLYING"
        self.r17_message = f"Applying {mode} Robot Vision mode"
        self.r17_error = ""
        logging.info("R-17 render mode queued: request=%s mode=%s output=%s", request_id, mode, self.active_output_name())
        self.send_r17_state(request_id, command=command)

    def complete_r17_render_after_render(self) -> None:
        """Publish READY only after the mode reached a streamed frame."""

        request_id = self.r17_pending_render_request_id
        if not request_id:
            return
        self.r17_pending_render_request_id = None
        self.r17_active_render_request_id = None
        if self.r17_render_frame_error:
            error = self.r17_render_frame_error
            self.r17_render_frame_error = ""
            self.r17_render_mode = R17_DEFAULT_RENDER_MODE
            self.r17_status = "ERROR"
            self.r17_message = f"Robot Vision fell back to {R17_DEFAULT_RENDER_MODE}"
            self.r17_error = error
            logging.error("R-17 render mode failed: request=%s error=%s", request_id, error)
            self.send_r17_state(request_id, status="ERROR", command=R17_RENDER_COMMAND)
            return
        if not self.r17_transition_active:
            self.r17_status = "READY"
        self.r17_message = f"{self.r17_render_mode} Robot Vision mode ready"
        self.r17_error = ""
        logging.info(
            "R-17 render mode applied: request=%s mode=%s outputs=%s uniqueIds=%d nonzero=%d",
            request_id,
            self.r17_render_mode,
            self.r17_output_keys,
            len(self.r17_semantic_unique_ids),
            int(self.r17_semantic_nonzero_pixels),
        )
        self.send_r17_state(request_id, status="READY", command=R17_RENDER_COMMAND)

    def handle_r17_lidar_command(self, request_id: str, payload: dict[str, Any]) -> None:
        """Validate one lidar.setEnabled command on the renderer-owning loop.

        A validated request only adds or drops the already-composed LiDAR
        RenderProduct in the existing step set; the stage is never reopened. It never constructs a second
        renderer, RenderProduct owner, stream buffer, or WebRTC connection, and
        it never writes the protected scene.
        """

        command = R17_LIDAR_COMMAND
        inner = payload.get("payload")
        inner = inner if isinstance(inner, dict) else {}
        raw_enabled = inner.get("enabled")

        # A duplicate requestId acknowledges the current result and never
        # re-authors the layer or reloads the stage.
        if request_id == self.r17_active_lidar_request_id or request_id in self.r17_seen_request_ids:
            self.send_r17_state(
                request_id,
                command=command,
                message=f"Duplicate request {request_id} acknowledged; LiDAR {self.r17_lidar_status} unchanged",
            )
            return

        self.r17_seen_request_ids.add(request_id)
        self.trim_seen_request_ids()

        if not isinstance(raw_enabled, bool):
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Unsupported LiDAR request",
                error=f"enabled must be a boolean: {raw_enabled!r}",
            )
            return

        # Only one LiDAR request may be in flight.
        if self.r17_active_lidar_request_id:
            self.send_r17_state(
                request_id,
                status="ERROR",
                command=command,
                message="Another LiDAR request is in flight",
                error=f"LiDAR request {self.r17_active_lidar_request_id} is still in flight",
            )
            return

        if raw_enabled:
            self.enable_r17_lidar(request_id, command)
        else:
            self.disable_r17_lidar(request_id, command)

    def enable_r17_lidar(self, request_id: str, command: str) -> None:
        # The already-enabled sensor acknowledges the current result without
        # reloading the stage.
        if self.r17_lidar_enabled and self.r17_lidar_status == "READY":
            self.send_r17_state(
                request_id,
                status="READY",
                command=command,
                message="LiDAR Link already enabled",
            )
            return
        try:
            self.r17_lidar_status = "WAITING"
            self.r17_lidar_error = ""
            self.r17_status = "WAITING"
            self.r17_message = "Enabling LiDAR Link"
            self.r17_error = ""
            self.set_lidar_enabled(True)
        except Exception as exc:
            self.r17_lidar_enabled = False
            self.r17_lidar_status = "ERROR"
            self.r17_lidar_error = str(exc)
            self.r17_status = "ERROR"
            self.r17_message = "LiDAR Link failed"
            self.r17_error = str(exc)
            self.last_error = str(exc)
            logging.exception("R-17 LiDAR enable failed")
            self.send_r17_state(request_id, status="ERROR", command=command)
            return
        self.r17_lidar_enabled = True
        self.r17_active_lidar_request_id = request_id
        self.r17_pending_lidar_request_id = request_id
        self.r17_pending_lidar_request_frame = self.frame_index
        logging.info(
            "R-17 LiDAR enable queued: request=%s sensor=%s product=%s channels=%s",
            request_id,
            R17_LIDAR_SENSOR_PATH,
            R17_LIDAR_RENDER_PRODUCT,
            list(R17_LIDAR_CHANNELS),
        )
        self.send_r17_state(request_id, status="WAITING", command=command)

    def disable_r17_lidar(self, request_id: str, command: str) -> None:
        reload_error = ""
        try:
            if self.r17_lidar_enabled:
                self.set_lidar_enabled(False)
        except Exception as exc:
            reload_error = str(exc)
            logging.exception("R-17 LiDAR deactivation failed")
        # Stop stepping the LiDAR product first, then drop every cached reading
        # so a DISABLED readout can never carry stale points or ranges.
        self.r17_lidar_enabled = False
        self.r17_active_lidar_request_id = None
        self.r17_pending_lidar_request_id = None
        self.r17_pending_lidar_request_frame = -1
        self.clear_lidar_runtime()
        self.r17_lidar_status = "DISABLED"
        self.r17_lidar_error = reload_error
        self.r17_status = "READY"
        self.r17_message = "LiDAR Link disabled"
        self.r17_error = ""
        logging.info("R-17 LiDAR disabled: request=%s", request_id)
        self.send_r17_state(request_id, status="READY", command=command)

    def complete_r17_lidar_after_render(self) -> None:
        """Publish READY only after validated points reached a streamed frame."""

        request_id = self.r17_pending_lidar_request_id
        if not request_id or self.frame_index <= self.r17_pending_lidar_request_frame:
            return
        if (
            self.r17_lidar_status == "READY"
            and self.r17_lidar_valid_point_count
            and self.r17_lidar_nearest_range is not None
            and np.isfinite(float(self.r17_lidar_nearest_range))
        ):
            self.r17_pending_lidar_request_id = None
            self.r17_active_lidar_request_id = None
            if not self.r17_transition_active:
                self.r17_status = "READY"
            self.r17_message = "LiDAR Link ready"
            self.r17_error = ""
            logging.info(
                "R-17 LiDAR ready: request=%s validPoints=%d nearestRange=%.3f outputs=%s materials=%d",
                request_id,
                int(self.r17_lidar_valid_point_count),
                float(self.r17_lidar_nearest_range),
                self.r17_lidar_output_keys,
                len(self.r17_lidar_nonvisual_material_paths),
            )
            self.send_r17_state(request_id, status="READY", command=R17_LIDAR_COMMAND)
            return
        if self.r17_lidar_error:
            self.r17_pending_lidar_request_id = None
            self.r17_active_lidar_request_id = None
            self.r17_lidar_status = "ERROR"
            self.r17_status = "ERROR"
            self.r17_message = "LiDAR Link failed"
            self.r17_error = self.r17_lidar_error
            logging.error("R-17 LiDAR failed: request=%s error=%s", request_id, self.r17_lidar_error)
            self.send_r17_state(request_id, status="ERROR", command=R17_LIDAR_COMMAND)

    def note_custom_camera_intent(self) -> None:
        """An accepted native orbit/pan/zoom moves the panel readout to CUSTOM."""

        if self.r17_active_view == "CUSTOM":
            return
        self.r17_active_view = "CUSTOM"
        self.r17_pending_custom_broadcast = True
        logging.info("R-17 view changed to CUSTOM by native viewport input")

    def broadcast_custom_view_after_render(self) -> None:
        if not self.r17_pending_custom_broadcast:
            return
        self.r17_pending_custom_broadcast = False
        self.send_r17_state(
            f"r17-native-input-{self.frame_index}",
            command="camera.nativeInput",
            message="CUSTOM view from viewport navigation",
        )

    def advance_r17_transition(self) -> None:
        """Advance the visible linear transition. Renderer-owner loop only."""

        if not self.r17_transition_active or self.r17_xform_binding is None:
            return
        if self.r17_transition_start is None or self.r17_transition_target is None:
            return

        duration = max(1e-6, float(self.r17_transition_duration))
        alpha = (time.monotonic() - self.r17_transition_started_at) / duration
        finished = alpha >= 1.0

        if finished:
            cube_xform = np.asarray(self.r17_transition_target, dtype=np.float64).copy().reshape(4, 4)
        else:
            cube_xform = interpolate_translation_only(self.r17_transition_start, self.r17_transition_target, alpha)
        self.write_bound_xform(self.r17_xform_binding, cube_xform)
        self.r17_current_transform = cube_xform

        if (
            self.r17_glow_xform_binding is not None
            and self.r17_glow_transition_start is not None
            and self.r17_glow_transition_target is not None
        ):
            if finished:
                glow_xform = np.asarray(self.r17_glow_transition_target, dtype=np.float64).copy().reshape(4, 4)
            else:
                glow_xform = interpolate_translation_only(
                    self.r17_glow_transition_start, self.r17_glow_transition_target, alpha
                )
            self.write_bound_xform(self.r17_glow_xform_binding, glow_xform)
            self.r17_glow_current_transform = glow_xform

        if finished:
            self.r17_pending_ready_request_id = self.r17_active_request_id or self.r17_pending_ready_request_id

    def complete_r17_transition_after_render(self) -> None:
        """Publish READY only after the final transform reached a rendered frame."""

        request_id = self.r17_pending_ready_request_id
        if not request_id:
            return
        self.r17_pending_ready_request_id = None
        self.r17_active_request_id = None
        self.r17_transition_active = False
        self.r17_transition_start = None
        self.r17_transition_target = None
        self.r17_glow_transition_start = None
        self.r17_glow_transition_target = None
        self.r17_status = "READY"
        self.r17_message = f"{self.r17_requested_pose} pose applied at offsetX {int(self.r17_offset_x):+d}"
        self.r17_error = ""
        logging.info(
            "R-17 pose applied: request=%s pose=%s offsetX=%+d",
            request_id,
            self.r17_requested_pose,
            int(self.r17_offset_x),
        )
        self.send_r17_state(request_id, command=R17_POSE_COMMAND)

    def write_camera(self) -> None:
        assert self.renderer is not None
        xform = np.ascontiguousarray(self.camera.get_camera_xform(), dtype=np.float64).reshape(1, 4, 4)
        self.renderer.write_attribute(
            prim_paths=[CAMERA_PATH],
            attribute_name="omni:xform",
            tensor=xform,
            semantic=ovrtx.Semantic.XFORM_MAT4x4,
            prim_mode=ovrtx.PrimMode.CREATE_NEW,
        )

    def write_lidar_sensor(self) -> None:
        """Aim the live sensor from the active camera before every step.

        writing-transforms: the OmniLidar prim wants sensor +X along the camera
        forward axis, so the sensor stays coincident with the active viewer
        camera and the preview follows DEFAULT, CUBE_FOCUS, and CUSTOM
        navigation alike.
        """

        if not self.r17_lidar_enabled:
            return
        assert self.renderer is not None
        eye, forward, _, up = self.camera.basis()
        matrix = matrix_from_lidar_eye_target(eye, np.asarray(eye) + np.asarray(forward), world_up=np.asarray(up))
        xform = np.ascontiguousarray(matrix, dtype=np.float64).reshape(1, 4, 4)
        self.renderer.write_attribute(
            prim_paths=[R17_LIDAR_SENSOR_PATH],
            attribute_name="omni:xform",
            tensor=xform,
            semantic=ovrtx.Semantic.XFORM_MAT4x4,
            prim_mode=ovrtx.PrimMode.CREATE_NEW,
        )
        self.r17_lidar_sensor_matrix = matrix

    def record_lidar_preview_miss(self, message: str) -> bool:
        """Tolerate a short warm-up gap, then report the miss and clear state."""

        self.r17_lidar_miss_count += 1
        if self.r17_lidar_miss_count <= max(8, self.fps // 2):
            self.r17_lidar_error = ""
            return False
        self.r17_lidar_valid_point_count = 0
        self.r17_lidar_nearest_range = None
        self.r17_lidar_preview_bgra = None
        self.r17_lidar_camera_preview_bgra = None
        self.r17_lidar_points_sensor = None
        self.r17_lidar_intensity = None
        self.r17_lidar_object_colors = None
        self.r17_lidar_history_sensor = []
        self.r17_lidar_history_world = []
        self.r17_lidar_history_colors = []
        self.r17_lidar_error = message
        return False

    def read_lidar_pointcloud(self, products) -> bool:
        """Map the PointCloud composite render var and copy out the channels.

        reading-sensor-pointclouds: the tensors are mapped on CPU, copied while
        still mapped, then released before any application state is updated.
        interpreting-lidar-pointclouds: `Counts` bounds the delivered entries
        and the `Flags` VALID bit (0x40) selects real returns.
        """

        if R17_LIDAR_RENDER_PRODUCT not in products:
            # The first steps after LIDAR ON may not deliver the product yet.
            return self.record_lidar_preview_miss(f"Missing LiDAR render product: {R17_LIDAR_RENDER_PRODUCT}")
        product = products[R17_LIDAR_RENDER_PRODUCT]
        for frame in product.frames:
            self.r17_lidar_output_keys = sorted(str(key) for key in frame.render_vars.keys())
            if R17_LIDAR_POINTCLOUD_OUTPUT not in frame.render_vars:
                self.r17_lidar_error = f"{R17_LIDAR_POINTCLOUD_OUTPUT} output missing"
                return False
            with frame.render_vars[R17_LIDAR_POINTCLOUD_OUTPUT].map(device=ovrtx.Device.CPU) as pointcloud:
                data = parse_lidar_pointcloud(pointcloud)
            valid_points = np.asarray(data["points"], dtype=np.float64)
            point_intensity = np.asarray(data["intensity"], dtype=np.float32)
            point_colors = data.get("objectColors")
            valid_point_count = int(data["validPointCount"])
            nearest_range = data["nearestRange"]
            if valid_point_count <= 0:
                return self.record_lidar_preview_miss("LiDAR returned no valid flagged points")
            if nearest_range is None or not np.isfinite(float(nearest_range)) or float(nearest_range) <= 0.0:
                return self.record_lidar_preview_miss("LiDAR nearest range is not positive finite")
            self.r17_lidar_valid_point_count = valid_point_count
            self.r17_lidar_nearest_range = float(nearest_range)
            self.r17_lidar_miss_count = 0
            self.r17_lidar_points_sensor = valid_points.copy()
            self.r17_lidar_intensity = point_intensity.copy()
            self.r17_lidar_object_colors = point_colors.copy() if isinstance(point_colors, np.ndarray) else None
            # Only the complete current scan is retained. World-space points use
            # the acquisition pose, so an old scan is never reprojected with a
            # new camera pose and scans are never stacked.
            history_points = valid_points
            history_colors = self.r17_lidar_object_colors
            history_world = lidar_points_to_world(history_points, self.r17_lidar_sensor_matrix)
            self.r17_lidar_history_sensor = [history_points.copy()]
            self.r17_lidar_history_world = (
                [history_world.copy()] if history_world is not None and history_world.shape[0] > 0 else []
            )
            self.r17_lidar_history_colors = [history_colors.copy()] if history_colors is not None else []
            if self.frame_index - self.r17_lidar_preview_frame >= self.r17_lidar_preview_interval_frames:
                self.r17_lidar_preview_bgra = fallback_lidar_density_preview(
                    history_points,
                    point_intensity,
                    height=self.height,
                    width=self.width,
                    object_colors=history_colors,
                )
                self.r17_lidar_preview_frame = self.frame_index
            self.r17_lidar_status = "READY"
            self.r17_lidar_error = ""
            return True
        return self.record_lidar_preview_miss("LiDAR returned no frames")

    def apply_lidar_inset(self, bgra_np: np.ndarray) -> np.ndarray:
        """Composite the camera-framed LiDAR preview into the lower-left inset.

        The main scene pixels are never recolored. The preview projects the
        measured current scan through the active camera lens; the sensor-frame
        density view is only the no-projection fallback, and the last good
        camera preview is latched so the inset cannot flash.
        """

        if not self.r17_lidar_enabled or self.r17_lidar_preview_bgra is None:
            return bgra_np
        fallback = self.r17_lidar_preview_bgra
        preview_height, preview_width = fallback.shape[:2]
        preview_sensor = self.r17_lidar_history_sensor[0] if self.r17_lidar_history_sensor else None
        preset = self.active_camera_preset()
        camera_preview = camera_projected_lidar_preview(
            preview_sensor,
            self.r17_lidar_sensor_matrix,
            camera_basis=self.camera.basis(),
            focal_length=float(preset.focal_length),
            horizontal_aperture=float(preset.horizontal_aperture),
            video_height=self.height,
            video_width=self.width,
            preview_height=preview_height,
            preview_width=preview_width,
        )
        if camera_preview is not None:
            self.r17_lidar_camera_preview_bgra = camera_preview
        preview = self.r17_lidar_camera_preview_bgra if self.r17_lidar_camera_preview_bgra is not None else fallback
        return overlay_lidar_preview(bgra_np, preview)

    def copy_cpu_bgra_to_stream(self, bgra_np: np.ndarray):
        """Composite the LiDAR inset, then reuse the one persistent BGRA buffer."""

        bgra_np = self.apply_lidar_inset(np.ascontiguousarray(bgra_np, dtype=np.uint8))
        if self.bgra is None:
            self.bgra = wp.empty((self.height, self.width, 4), dtype=wp.uint8, device="cuda:0")
        if not copy_numpy_bgra_to_stream(bgra_np, self.bgra, height=self.height, width=self.width):
            raise RuntimeError("could not copy the BGRA frame into the stream buffer")
        return ovstream.VideoFrame.from_cuda_array(self.bgra)

    def extract_frame(self, products, save_first_cpu: bool = False):
        """Convert one ovrtx frame into the single persistent BGRA stream buffer.

        reading-render-output: BEAUTY maps LdrColor on CUDA and swaps channels in
        place; SEMANTIC maps the uint32 SemanticSegmentation IDs, decodes
        SemanticIdMap, and converts IDs only into candy-color BGRA. The same
        buffer and the same video track carry both modes.
        """

        if RENDER_PRODUCT not in products:
            raise RuntimeError(f"Missing render product output: {RENDER_PRODUCT}")
        product = products[RENDER_PRODUCT]
        for frame in product.frames:
            self.r17_output_keys = sorted(str(key) for key in frame.render_vars.keys())
            if BEAUTY_OUTPUT not in frame.render_vars:
                raise RuntimeError(f"{BEAUTY_OUTPUT} render var missing")
            try:
                semantic_id_map = update_semantic_id_map(frame)
                if semantic_id_map:
                    self.r17_semantic_id_map = semantic_id_map
            except Exception:
                logging.debug("SemanticIdMap decode skipped for this frame", exc_info=True)
            if save_first_cpu and not self.artifact_frame.exists():
                with frame.render_vars[BEAUTY_OUTPUT].map(device=ovrtx.Device.CPU) as cpu_var:
                    pixels = np.from_dlpack(cpu_var).copy()
                    Image.fromarray(pixels).save(self.artifact_frame)
            if self.bgra is None:
                self.bgra = wp.empty((self.height, self.width, 4), dtype=wp.uint8, device="cuda:0")
            if self.r17_render_mode == "SEMANTIC":
                try:
                    ids, unique_ids, nonzero_pixels = semantic_ids_from_frame(frame, self.height, self.width)
                    self.r17_semantic_unique_ids = unique_ids
                    self.r17_semantic_nonzero_pixels = nonzero_pixels
                    semantic_bgra = candy_colorize_semantic_ids(ids, self.height, self.width)
                    self.r17_render_frame_error = ""
                    # No beauty/context pixels are blended into SEMANTIC mode;
                    # only the LiDAR inset composites over the streamed frame.
                    return self.copy_cpu_bgra_to_stream(semantic_bgra)
                except Exception as exc:
                    self.r17_render_mode = R17_DEFAULT_RENDER_MODE
                    self.r17_render_frame_error = str(exc)
                    logging.exception("SEMANTIC render mode failed; falling back to BEAUTY")
            if self.r17_lidar_enabled and self.r17_lidar_preview_bgra is not None:
                # The inset is composited on the CPU, so BEAUTY takes the CPU
                # mapping only while LiDAR is on. The same buffer and the same
                # video track still carry the frame.
                with frame.render_vars[BEAUTY_OUTPUT].map(device=ovrtx.Device.CPU) as cpu_var:
                    rgba_cpu = np.from_dlpack(cpu_var).copy()
                bgra_cpu = np.empty_like(rgba_cpu)
                bgra_cpu[:, :, 0] = rgba_cpu[:, :, 2]
                bgra_cpu[:, :, 1] = rgba_cpu[:, :, 1]
                bgra_cpu[:, :, 2] = rgba_cpu[:, :, 0]
                bgra_cpu[:, :, 3] = rgba_cpu[:, :, 3]
                return self.copy_cpu_bgra_to_stream(bgra_cpu)
            with frame.render_vars[BEAUTY_OUTPUT].map(device=ovrtx.Device.CUDA) as cuda_var:
                rgba = wp.from_dlpack(cuda_var)
                wp.launch(rgba_to_bgra, dim=(self.height, self.width, 4), inputs=[rgba, self.bgra], device="cuda:0")
                wp.synchronize_device("cuda:0")
                return ovstream.VideoFrame.from_cuda_array(self.bgra)
        raise RuntimeError("No frames returned")

    def warmup(self, count: int = 8) -> None:
        assert self.renderer is not None
        logging.info("Warming renderer for %d frames before ovstream startup", count)
        for i in range(count):
            self.write_camera()
            products = self.renderer.step(render_products={RENDER_PRODUCT}, delta_time=1.0 / max(1, self.fps))
            self.extract_frame(products, save_first_cpu=(i == count - 1))
            logging.info("Warm-up frame %d/%d outputs=%s", i + 1, count, self.r17_output_keys)
        missing = [name for name in self.r17_available_outputs if name not in self.r17_output_keys]
        if missing:
            self.last_error = f"ovrtx did not produce Robot Vision outputs: {missing}"
            logging.error(
                "R-17 Robot Vision outputs missing after warmup: missing=%s produced=%s. "
                "SEMANTIC will fall back to BEAUTY.",
                missing,
                self.r17_output_keys,
            )
        else:
            logging.info("R-17 Robot Vision outputs ready: %s", self.r17_output_keys)

    def start_stream(self) -> None:
        ovstream.initialize(log_fn=lambda level, channel, msg, ts: logging.debug("ovstream[%s] %s: %s", getattr(level, "name", level), channel, msg), log_min_severity=ovstream.LogLevel.WARNING)
        self.stream = ovstream.Server(ovstream.ServerType.WEBRTC)
        self.stream.on_connection = self.on_connection
        self.stream.on_message = self.on_message
        self.stream.on_input = self.on_input
        config = ovstream.ServerConfig(
            width=self.width,
            height=self.height,
            target_fps=self.fps,
            video_input=ovstream.VideoInput.CUDA,
            webrtc_signal_port=self.signaling_port,
            webrtc_public_ip=self.public_ip,
        )
        self.stream.start(config)
        self.stream_start_count += 1
        logging.info("WebRTC signaling: ws/http on %s:%d", self.public_ip, self.signaling_port)

    def on_connection(self, connected: bool) -> None:
        logging.info("WebRTC connected=%s", connected)
        if connected:
            # The minimal browser viewport has no UI chrome and sends no
            # setViewportInputActive messages. Re-arm native input on every
            # connection so stale false state from a previous UI session cannot
            # suppress ovstream InputEvent camera control.
            self.commands.put(("viewport_active", True))
            self.commands.put(("cancel_camera", None))
            threading.Thread(target=self.push_initial_state, daemon=True).start()

    def push_initial_state(self) -> None:
        time.sleep(0.3)
        send_json(self.stream, "openStageResult", {"url": str(self.stage_path), "result": "success", "root_prim_path": self.current_stage_root_path})
        send_json(
            self.stream,
            "activeAOVState",
            {"active": self.active_output_name(), "available": list(self.r17_available_outputs), "result": "success"},
        )
        send_json(
            self.stream,
            "availableAOVsResult",
            {"aovs": list(self.r17_available_outputs), "available": list(self.r17_available_outputs)},
        )
        self.send_r17_state("server-connect", command="r17.getState", message=self.r17_message or "Memory Cube Link ready")

    def on_message(self, raw) -> None:
        msg = decode_app_message(raw)
        if msg is None:
            logging.debug("Ignoring non-json app message: %r", raw)
            return
        event_type = msg.get("event_type")
        payload = msg.get("payload") or {}
        logging.info("Stream message: %s payload=%s", event_type, payload)
        if event_type == "setViewportInputActive":
            self.commands.put(("viewport_active", bool(payload.get("active", True))))
        elif event_type == "openStageRequest":
            send_json(self.stream, "openStageResult", {"url": str(self.stage_path), "result": "success", "root_prim_path": self.current_stage_root_path})
        elif event_type == "getAvailableAOVs":
            send_json(
                self.stream,
                "availableAOVsResult",
                {"aovs": list(self.r17_available_outputs), "available": list(self.r17_available_outputs)},
            )
        elif event_type == R17_COMMAND_EVENT:
            self.commands.put(("r17_command", payload))
        else:
            logging.debug("Unhandled message: %s", event_type)

    def _camera_button_from_ovstream(self, raw_button):
        try:
            button = raw_button if isinstance(raw_button, ovstream.MouseButton) else ovstream.MouseButton(raw_button)
        except Exception:
            return None
        if button == ovstream.MouseButton.LEFT:
            return 0
        if button == ovstream.MouseButton.MIDDLE:
            return 1
        if button == ovstream.MouseButton.RIGHT:
            return 2
        return None

    def on_input(self, event) -> None:
        self.commands.put(("native_input", event))

    def handle_input_on_render_thread(self, event) -> None:
        if not self.viewport_input_active:
            self.camera.cancel_interaction()
            return
        if event.type != ovstream.InputEventType.MOUSE:
            return
        mouse = event.mouse
        if mouse.type == ovstream.MouseEventType.MOVE:
            before = (self.camera.azimuth, self.camera.elevation, float(self.camera.distance), *map(float, self.camera.target))
            self.camera.on_mouse_move(float(mouse.x), float(mouse.y))
            after = (self.camera.azimuth, self.camera.elevation, float(self.camera.distance), *map(float, self.camera.target))
            if after != before:
                self.note_custom_camera_intent()
                logging.info(
                    "Native camera drag: button=%s x=%.1f y=%.1f az=%.3f el=%.3f dist=%.3f target=(%.3f, %.3f, %.3f)",
                    self.camera._button,
                    float(mouse.x),
                    float(mouse.y),
                    self.camera.azimuth,
                    self.camera.elevation,
                    self.camera.distance,
                    float(self.camera.target[0]),
                    float(self.camera.target[1]),
                    float(self.camera.target[2]),
                )
            return
        if mouse.type == ovstream.MouseEventType.WHEEL:
            delta = getattr(mouse, "scroll_y", 0) or getattr(mouse, "data", 0)
            before = float(self.camera.distance)
            self.camera.on_scroll(float(delta))
            if float(self.camera.distance) != before:
                self.note_custom_camera_intent()
                logging.info("Native camera wheel: delta=%.3f dist=%.3f", float(delta), self.camera.distance)
            return
        if mouse.type != ovstream.MouseEventType.BUTTON:
            return
        button = self._camera_button_from_ovstream(mouse.data)
        if button is None:
            return
        is_down = mouse.button_state == ovstream.KeyState.DOWN
        if is_down:
            logging.info("Native camera button down: button=%s x=%.1f y=%.1f", button, float(mouse.x), float(mouse.y))
            self.camera.on_mouse_button_down(float(mouse.x), float(mouse.y), button)
        else:
            was_click = self.camera.on_mouse_button_up(float(mouse.x), float(mouse.y), button)
            logging.info("Native camera button up: button=%s x=%.1f y=%.1f click=%s", button, float(mouse.x), float(mouse.y), was_click)
            if button == 0 and was_click:
                logging.info("Viewport click at %.1f %.1f", float(mouse.x), float(mouse.y))

    def drain_commands(self) -> None:
        while True:
            try:
                name, payload = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "viewport_active":
                self.viewport_input_active = bool(payload)
                logging.info("Viewport input active=%s", self.viewport_input_active)
                if not self.viewport_input_active:
                    self.camera.cancel_interaction()
            elif name == "cancel_camera":
                self.camera.cancel_interaction()
            elif name == "r17_command":
                self.handle_r17_command(payload)
            elif name == "native_input":
                self.handle_input_on_render_thread(payload)

    def render_loop(self) -> None:
        dt = 1.0 / max(1, self.fps)
        while not self.stop_event.is_set():
            start = time.time()
            try:
                self.drain_commands()
                self.advance_r17_transition()
                self.write_camera()
                # One renderer owner, one camera RenderProduct. While LiDAR is
                # on, its RenderProduct joins the same step set.
                render_products = {RENDER_PRODUCT}
                if self.r17_lidar_enabled:
                    self.write_lidar_sensor()
                    render_products.add(R17_LIDAR_RENDER_PRODUCT)
                products = self.renderer.step(render_products=render_products, delta_time=dt)
                if self.r17_lidar_enabled:
                    self.read_lidar_pointcloud(products)
                frame = self.extract_frame(products, save_first_cpu=False)
                self.frame_index += 1
                if not self.first_frame_logged:
                    self.first_frame_logged = True
                    self.ready_event.set()
                    logging.info("First BGRA frame ready: %dx%d", self.width, self.height)
                if self.stream is not None:
                    try:
                        self.stream.stream_video(frame)
                    except Exception:
                        logging.debug("Dropped frame during disconnect/no-client", exc_info=True)
                self.complete_r17_transition_after_render()
                self.complete_r17_view_after_render()
                self.complete_r17_render_after_render()
                self.complete_r17_lidar_after_render()
                self.broadcast_custom_view_after_render()
            except Exception as exc:
                self.last_error = str(exc)
                logging.exception("Render loop error")
                time.sleep(0.25)
            elapsed = time.time() - start
            time.sleep(max(0.0, dt - elapsed))

    def run(self) -> None:
        logging.info("Creating ovrtx renderer")
        # enable_motion_bvh keeps the LiDAR sensor's motion BVH available so
        # returns stay correct while the sensor follows the live camera.
        self.renderer = ovrtx.Renderer(
            config=ovrtx.RendererConfig(
                sync_mode=True,
                active_cuda_gpus="0",
                keep_system_alive=True,
                enable_motion_bvh=True,
            )
        )
        self.renderer_create_count += 1
        wp.init()
        self.load_stage()
        self.warmup()
        self.verify_memory_cube()
        self.initialize_r17_memory_cube()
        self.start_health()
        self.start_stream()
        thread = threading.Thread(target=self.render_loop, daemon=True)
        thread.start()
        logging.info("Attic Portal server readying. Health waits for first streamed frame.")
        try:
            while not self.stop_event.is_set():
                time.sleep(0.5)
        finally:
            self.stop_event.set()
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    logging.debug("stream close failed", exc_info=True)
            try:
                ovstream.shutdown()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Attic Portal ovrtx/ovstream server")
    parser.add_argument("--stage", default=str(DEFAULT_STAGE), help="Mission stage path or Attic_NVIDIA directory")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--signaling-port", type=int, default=49100)
    parser.add_argument("--health-port", type=int, default=8081)
    parser.add_argument("--public-ip", default="127.0.0.1")
    parser.add_argument("--log", default=str(ROOT / "logs" / "server.log"))
    args = parser.parse_args()

    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(args.log), logging.StreamHandler(sys.stdout)],
    )
    server = AtticPortalServer(Path(args.stage), args.width, args.height, args.fps, args.signaling_port, args.health_port, args.public_ip)
    signal.signal(signal.SIGTERM, lambda *_: server.stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: server.stop_event.set())
    server.run()


if __name__ == "__main__":
    main()
