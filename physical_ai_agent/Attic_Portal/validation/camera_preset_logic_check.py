#!/usr/bin/env python3
"""Focused non-rendering checks for the R-17 camera preset request machine.

Covers the parts the browser check cannot isolate: command validation,
requestId correlation, one-in-flight gating, READY only after a rendered
frame, and the CUSTOM transition on accepted native input.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import attic_portal_server as portal
from camera_controller import OrbitCamera


class FakeRenderer:
    """Records lens writes instead of touching a real ovrtx renderer."""

    def __init__(self) -> None:
        self.writes: list[tuple[tuple[str, ...], str, list]] = []

    def write_attribute(self, prim_paths, attribute_name, tensor, **_kwargs) -> None:
        self.writes.append((tuple(prim_paths), attribute_name, np.asarray(tensor).reshape(-1).tolist()))

    def lens(self, camera_path: str) -> dict[str, list]:
        return {name: values for paths, name, values in self.writes if paths == (camera_path,)}


def make_server() -> portal.AtticPortalServer:
    server = portal.AtticPortalServer.__new__(portal.AtticPortalServer)
    server.width, server.height = 960, 540
    server.stream = object()
    server.renderer = FakeRenderer()
    server.camera = OrbitCamera(server.width, server.height)
    server.camera.fit_attic()
    server.frame_index = 0
    server.last_error = ""
    server.viewport_input_active = True

    home = np.identity(4, dtype=np.float64)
    home[3, 0:3] = [-620.0, -1125.0, 121.0]
    bounds_min, bounds_max = portal.cube_pose_envelope(home, (20.0, 20.0, 20.0), portal.POSE_OFFSETS.values())
    aspect = server.height / server.width
    server.r17_view_presets = {
        "DEFAULT": portal.default_view_preset(aspect=aspect),
        "CUBE_FOCUS": portal.focus_preset_from_bounds(bounds_min, bounds_max, aspect=aspect),
    }
    server.r17_focus_bounds_min = bounds_min
    server.r17_focus_bounds_max = bounds_max
    server.r17_focus_camera_path = portal.R17_FOCUS_CAMERA_PATH
    server.r17_camera_layer = portal.CAMERA_LAYER
    server.r17_active_view = "DEFAULT"
    server.r17_active_view_request_id = None
    server.r17_pending_view_request_id = None
    server.r17_pending_custom_broadcast = False

    server.r17_cube_path = portal.MEMORY_CUBE_PATH
    server.r17_home_transform = home
    server.r17_current_transform = home.copy()
    server.r17_xform_binding = None
    server.r17_seen_request_ids = set()
    server.r17_active_request_id = None
    server.r17_pending_ready_request_id = None
    server.r17_requested_pose = "HOME"
    server.r17_offset_x = 0
    server.r17_status = "READY"
    server.r17_message = "Memory Cube Link ready"
    server.r17_error = ""
    server.r17_transition_active = False
    return server


def command(request_id: str, view: object) -> dict:
    return {"requestId": request_id, "command": "camera.setView", "payload": {"view": view}}


def orbit_signature(server: portal.AtticPortalServer) -> tuple:
    camera = server.camera
    return (camera.azimuth, camera.elevation, float(camera.distance), tuple(float(v) for v in camera.target))


def preset_signature(view: str, server: portal.AtticPortalServer) -> tuple:
    preset = server.r17_view_presets[view]
    return (preset.azimuth, preset.elevation, float(preset.distance), tuple(float(v) for v in preset.target))


def main() -> None:
    emitted: list[dict] = []
    original_send = portal.send_json
    portal.send_json = lambda _server, _event, payload: emitted.append(payload.copy())
    try:
        server = make_server()

        # Unsupported views and payload shapes are rejected without moving.
        before = orbit_signature(server)
        for bad in ("TOP_DOWN", "", None, "CUSTOM"):
            server.handle_r17_command(command(f"bad-{bad!r}", bad))
            assert emitted[-1]["status"] == "ERROR", emitted[-1]
            assert emitted[-1]["activeView"] == "DEFAULT", emitted[-1]
        assert orbit_signature(server) == before

        # CUBE FOCUS: APPLYING first, READY only after a rendered frame.
        server.handle_r17_command(command("focus-1", "CUBE_FOCUS"))
        assert emitted[-1]["status"] == "APPLYING", emitted[-1]
        assert emitted[-1]["requestId"] == "focus-1"
        assert emitted[-1]["activeView"] == "CUBE_FOCUS"
        assert orbit_signature(server) == preset_signature("CUBE_FOCUS", server)
        lens = server.renderer.lens(portal.ACTIVE_VIEWER_CAMERA_PATH)
        assert lens["focalLength"] == [35.0], lens
        assert server.r17_pending_view_request_id == "focus-1"

        # A duplicate requestId acknowledges without re-applying.
        pending = server.r17_pending_view_request_id
        writes = len(server.renderer.writes)
        server.handle_r17_command(command("focus-1", "CUBE_FOCUS"))
        assert "Duplicate" in emitted[-1]["message"], emitted[-1]
        assert len(server.renderer.writes) == writes
        assert server.r17_pending_view_request_id == pending

        # A second request while one is in flight is rejected, not queued.
        server.handle_r17_command(command("default-early", "DEFAULT"))
        assert emitted[-1]["status"] == "ERROR" and "in flight" in emitted[-1]["error"], emitted[-1]
        assert server.r17_active_view == "CUBE_FOCUS"

        server.complete_r17_view_after_render()
        assert emitted[-1]["status"] == "READY" and emitted[-1]["requestId"] == "focus-1", emitted[-1]
        assert emitted[-1]["activeView"] == "CUBE_FOCUS"
        assert emitted[-1]["focusCameraPath"] == portal.R17_FOCUS_CAMERA_PATH
        assert server.r17_active_view_request_id is None

        # Accepted native navigation flips the published view to CUSTOM,
        # broadcast after the next rendered frame, and never blocks input.
        server.camera.on_mouse_button_down(100.0, 100.0, 0)
        server.camera.on_mouse_move(160.0, 140.0)
        server.note_custom_camera_intent()
        assert server.r17_active_view == "CUSTOM"
        assert server.r17_pending_custom_broadcast
        server.broadcast_custom_view_after_render()
        assert emitted[-1]["activeView"] == "CUSTOM" and emitted[-1]["status"] == "READY", emitted[-1]
        assert not server.r17_pending_custom_broadcast
        server.broadcast_custom_view_after_render()  # idempotent
        assert emitted[-1]["activeView"] == "CUSTOM"

        # DEFAULT VIEW restores the Part 1 startup pose and lens exactly.
        server.handle_r17_command(command("default-1", "DEFAULT"))
        server.complete_r17_view_after_render()
        assert server.r17_active_view == "DEFAULT"
        assert orbit_signature(server) == preset_signature("DEFAULT", server)
        assert orbit_signature(server) == before, (orbit_signature(server), before)
        lens = server.renderer.lens(portal.ACTIVE_VIEWER_CAMERA_PATH)
        assert lens["focalLength"] == [24.0], lens
        # Lens values round-trip through float32 tensors.
        assert abs(lens["horizontalAperture"][0] - portal.H_APERTURE) < 1e-4, lens
    finally:
        portal.send_json = original_send

    print(
        {
            "focusCameraPath": portal.R17_FOCUS_CAMERA_PATH,
            "focusBoundsMin": [float(v) for v in server.r17_focus_bounds_min],
            "focusBoundsMax": [float(v) for v in server.r17_focus_bounds_max],
            "invalidViewRejected": True,
            "duplicateRequestReapplied": False,
            "secondRequestWhileInFlightRejected": True,
            "readyOnlyAfterRenderedFrame": True,
            "nativeInputBecomesCustom": True,
            "defaultRestoresPart1Preset": True,
        }
    )


if __name__ == "__main__":
    main()
