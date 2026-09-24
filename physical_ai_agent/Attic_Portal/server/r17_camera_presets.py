"""Helpers for R-17 camera presets.

Used by the renderer-owning server loop for DEFAULT VIEW and CUBE FOCUS. They
keep camera-layer authoring, focus framing, and active viewer-camera writes out
of the message-handling code.

Conventions that must hold:

* The attic stage is Z-up, so every pose is built with world up ``(0, 0, 1)``.
* Camera matrices use the USD row-vector convention consumed by ovrtx:
  rows are right, up, -forward, eye.
* ``R17_CAMERA_LAYER`` only ever holds viewer-owned camera prims. The protected
  scene under ``Attic_NVIDIA`` is never written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import ovrtx

R17_FOCUS_CAMERA_PATH = "/Session/Cameras/R17CubeFocus"
ACTIVE_VIEWER_CAMERA_PATH = "/OVCamera"
DEFAULT_FOCAL_LENGTH = 24.0
FOCUS_FOCAL_LENGTH = 35.0
HORIZONTAL_APERTURE = 20.955
DEFAULT_CLIPPING_RANGE = (1.0, 10000000.0)
DEFAULT_ASPECT = 540.0 / 960.0
DEFAULT_ORBIT = {
    "target": [-620.0, -1125.0, 121.0],
    "distance": 455.0,
    "azimuth": 0.0,
    "elevation": 0.34,
}
# Named Memory Cube poses from Part 1, in stage units along world X.
POSE_OFFSETS = (-15.0, 0.0, 15.0)
# Fraction of the narrower half-FOV the framed envelope is allowed to fill.
# Leaves attic context (floor, rafters, props) around the cube.
FOCUS_FILL_FRACTION = 0.42
MIN_FOCUS_DISTANCE = 260.0
# Target-to-eye direction for the focus pose. Positive Z keeps the camera above
# the attic floor; negative Y keeps it on the open side of the workshop.
FOCUS_DIRECTION = (0.25, -1.0, 0.48)


@dataclass(frozen=True)
class CameraPreset:
    name: str
    target: tuple[float, float, float]
    distance: float
    azimuth: float
    elevation: float
    focal_length: float
    horizontal_aperture: float = HORIZONTAL_APERTURE
    clipping_range: tuple[float, float] = DEFAULT_CLIPPING_RANGE
    aspect: float = DEFAULT_ASPECT

    @property
    def vertical_aperture(self) -> float:
        return self.horizontal_aperture * float(self.aspect)


def matrix_from_eye_target(eye: Iterable[float], target: Iterable[float], up=(0.0, 0.0, 1.0)) -> np.ndarray:
    eye_v = np.asarray(tuple(eye), dtype=np.float64)
    target_v = np.asarray(tuple(target), dtype=np.float64)
    up_v = np.asarray(up, dtype=np.float64)
    forward = target_v - eye_v
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, up_v)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    matrix = np.identity(4, dtype=np.float64)
    matrix[0, 0:3] = right
    matrix[1, 0:3] = true_up
    matrix[2, 0:3] = -forward
    matrix[3, 0:3] = eye_v
    return matrix


def orbit_eye(preset: CameraPreset) -> np.ndarray:
    """Eye position for a preset, matching OrbitCamera.eye() exactly."""

    target = np.asarray(preset.target, dtype=np.float64)
    ce = math.cos(preset.elevation)
    return np.array(
        [
            target[0] + math.sin(preset.azimuth) * ce * preset.distance,
            target[1] - math.cos(preset.azimuth) * ce * preset.distance,
            target[2] + math.sin(preset.elevation) * preset.distance,
        ],
        dtype=np.float64,
    )


def camera_matrix_from_orbit(preset: CameraPreset) -> np.ndarray:
    return matrix_from_eye_target(orbit_eye(preset), preset.target)


def cube_pose_envelope(
    home_matrix: np.ndarray,
    half_extent: Iterable[float] = (20.0, 20.0, 20.0),
    pose_offsets: Iterable[float] = POSE_OFFSETS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return world bounds covering every named cube pose.

    ``half_extent`` is the cube's world-space half size (queried from USD by the
    caller). The named poses only translate along world X, so the union is the
    home bound widened by the extreme pose offsets.
    """

    home = np.asarray(home_matrix, dtype=np.float64).reshape(4, 4)
    center = home[3, 0:3]
    extent = np.asarray(tuple(half_extent), dtype=np.float64).reshape(3)
    corners = []
    for offset_x in pose_offsets:
        posed = center.copy()
        posed[0] += float(offset_x)
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    corners.append(posed + np.asarray([sx * extent[0], sy * extent[1], sz * extent[2]]))
    points = np.asarray(corners, dtype=np.float64)
    return points.min(axis=0), points.max(axis=0)


def focus_preset_from_bounds(
    bounds_min: Iterable[float],
    bounds_max: Iterable[float],
    aspect: float = DEFAULT_ASPECT,
) -> CameraPreset:
    """One Z-up orbit pose that frames the whole pose envelope with context."""

    bmin = np.asarray(tuple(bounds_min), dtype=np.float64)
    bmax = np.asarray(tuple(bounds_max), dtype=np.float64)
    center = (bmin + bmax) * 0.5
    span = bmax - bmin
    radius = float(np.linalg.norm(span) * 0.5)
    h_fov = 2.0 * math.atan(HORIZONTAL_APERTURE / (2.0 * FOCUS_FOCAL_LENGTH))
    v_fov = 2.0 * math.atan((HORIZONTAL_APERTURE * float(aspect)) / (2.0 * FOCUS_FOCAL_LENGTH))
    distance = max(MIN_FOCUS_DISTANCE, radius / math.sin(min(h_fov, v_fov) * FOCUS_FILL_FRACTION))

    direction = np.asarray(FOCUS_DIRECTION, dtype=np.float64)
    direction /= np.linalg.norm(direction)
    offset = direction * distance
    elevation = float(math.asin(offset[2] / distance))
    ce = max(1e-8, float(math.cos(elevation)))
    azimuth = float(math.atan2(offset[0] / (distance * ce), -offset[1] / (distance * ce)))
    return CameraPreset(
        name="CUBE_FOCUS",
        target=(float(center[0]), float(center[1]), float(center[2])),
        distance=float(distance),
        azimuth=azimuth,
        elevation=elevation,
        focal_length=FOCUS_FOCAL_LENGTH,
        aspect=float(aspect),
    )


def default_view_preset(aspect: float = DEFAULT_ASPECT, **overrides: Any) -> CameraPreset:
    """The Part 1 fitted startup pose and lens, not the live camera state."""

    orbit = {**DEFAULT_ORBIT, **overrides}
    return CameraPreset(
        name="DEFAULT",
        target=tuple(float(v) for v in orbit["target"]),
        distance=float(orbit["distance"]),
        azimuth=float(orbit["azimuth"]),
        elevation=float(orbit["elevation"]),
        focal_length=DEFAULT_FOCAL_LENGTH,
        aspect=float(aspect),
    )


def camera_layer_usda(preset: CameraPreset, camera_path: str = R17_FOCUS_CAMERA_PATH) -> str:
    matrix = camera_matrix_from_orbit(preset)
    rows = [", ".join(f"{float(v):.12g}" for v in row) for row in matrix]
    camera_name = camera_path.rstrip("/").split("/")[-1]
    return """#usda 1.0
(
    defaultPrim = "Session"
)

def Scope "Session"
{{
    def Scope "Cameras"
    {{
        def Camera "{camera_name}"
        {{
            float2 clippingRange = ({clip0:.12g}, {clip1:.12g})
            float focalLength = {focal:.12g}
            float horizontalAperture = {hap:.12g}
            float verticalAperture = {vap:.12g}
            token projection = "perspective"
            matrix4d xformOp:transform = (
            ({row0}),
            ({row1}),
            ({row2}),
            ({row3})
            )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}
    }}
}}
""".format(
        camera_name=camera_name,
        clip0=preset.clipping_range[0],
        clip1=preset.clipping_range[1],
        focal=preset.focal_length,
        hap=preset.horizontal_aperture,
        vap=preset.vertical_aperture,
        row0=rows[0],
        row1=rows[1],
        row2=rows[2],
        row3=rows[3],
    )


def write_camera_layer(layer_path: Path, preset: CameraPreset, camera_path: str = R17_FOCUS_CAMERA_PATH) -> str:
    """Author the viewer-owned camera layer. Never touches the user scene."""

    layer_path.parent.mkdir(parents=True, exist_ok=True)
    text = camera_layer_usda(preset, camera_path)
    layer_path.write_text(text, encoding="utf-8")
    return text


def write_camera_lens(renderer: ovrtx.Renderer, camera_path: str, preset: CameraPreset) -> None:
    """writing-attributes: scalar lens values on the active viewer camera."""

    renderer.write_attribute(
        prim_paths=[camera_path],
        attribute_name="focalLength",
        tensor=np.asarray([preset.focal_length], dtype=np.float32),
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )
    renderer.write_attribute(
        prim_paths=[camera_path],
        attribute_name="horizontalAperture",
        tensor=np.asarray([preset.horizontal_aperture], dtype=np.float32),
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )
    renderer.write_attribute(
        prim_paths=[camera_path],
        attribute_name="verticalAperture",
        tensor=np.asarray([preset.vertical_aperture], dtype=np.float32),
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )
    renderer.write_attribute(
        prim_paths=[camera_path],
        attribute_name="clippingRange",
        tensor=np.asarray([preset.clipping_range], dtype=np.float32),
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )


def bind_camera_xform(renderer: ovrtx.Renderer, camera_path: str = ACTIVE_VIEWER_CAMERA_PATH) -> Any:
    return renderer.bind_attribute(
        prim_paths=[camera_path],
        attribute_name="omni:xform",
        dtype="float64",
        semantic=ovrtx.Semantic.XFORM_MAT4x4,
        prim_mode=ovrtx.PrimMode.CREATE_NEW,
    )
