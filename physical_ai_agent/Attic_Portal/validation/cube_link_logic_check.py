#!/usr/bin/env python3
"""Focused non-rendering checks for the R-17 Cube Link request state machine."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import attic_portal_server as portal


class Binding:
    def __init__(self) -> None:
        self.writes: list[np.ndarray] = []

    def write(self, matrix: np.ndarray) -> None:
        self.writes.append(np.asarray(matrix, dtype=np.float64).reshape(4, 4).copy())


def make_server() -> portal.AtticPortalServer:
    server = portal.AtticPortalServer.__new__(portal.AtticPortalServer)
    home = np.array(
        [
            [0.0, 2.0, 0.0, 0.0],
            [-3.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 4.0, 0.0],
            [-620.0, -1125.0, 121.0, 1.0],
        ],
        dtype=np.float64,
    )
    server.stream = object()
    server.r17_cube_path = portal.MEMORY_CUBE_PATH
    server.r17_home_transform = home
    server.r17_current_transform = home.copy()
    server.r17_xform_binding = Binding()
    server.r17_glow_home_transform = None
    server.r17_glow_current_transform = None
    server.r17_glow_xform_binding = None
    server.r17_seen_request_ids = set()
    server.r17_active_request_id = None
    server.r17_transition_started_at = 0.0
    server.r17_transition_duration = 0.45
    server.r17_transition_start = None
    server.r17_transition_target = None
    server.r17_glow_transition_start = None
    server.r17_glow_transition_target = None
    server.r17_pending_ready_request_id = None
    server.r17_requested_pose = "HOME"
    server.r17_offset_x = 0
    server.r17_status = "READY"
    server.r17_message = "Memory Cube Link ready"
    server.r17_error = ""
    server.r17_transition_active = False
    # Camera-preset state read by r17_state_payload().
    server.r17_active_view = "DEFAULT"
    server.r17_focus_camera_path = portal.R17_FOCUS_CAMERA_PATH
    server.r17_camera_layer = portal.CAMERA_LAYER
    return server


def command(request_id: str, pose: str) -> dict:
    return {
        "requestId": request_id,
        "command": "cube.setPose",
        "payload": {"pose": pose},
    }


def assert_target(server: portal.AtticPortalServer, pose: str, offset: int) -> None:
    home = server.r17_home_transform
    current = server.r17_current_transform
    assert home is not None and current is not None
    expected = home.copy()
    expected[3, 0] += offset
    np.testing.assert_allclose(current, expected, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(current[:3, :], home[:3, :], rtol=0.0, atol=1e-12)
    assert server.r17_requested_pose == pose
    assert server.r17_offset_x == offset


def finish(server: portal.AtticPortalServer) -> None:
    server.r17_transition_started_at = time.monotonic() - 1.0
    server.advance_r17_transition()
    assert server.r17_pending_ready_request_id
    server.complete_r17_transition_after_render()
    assert server.r17_status == "READY"
    assert not server.r17_transition_active


def main() -> None:
    emitted: list[dict] = []
    original_send = portal.send_json
    portal.send_json = lambda _server, _event, payload: emitted.append(payload.copy())
    try:
        server = make_server()

        writes_before = len(server.r17_xform_binding.writes)
        server.handle_r17_command(command("already-home", "HOME"))
        assert len(server.r17_xform_binding.writes) == writes_before
        assert emitted[-1]["status"] == "READY"
        assert "already active" in emitted[-1]["message"]

        server.handle_r17_command(command("left-1", "LEFT"))
        started_at = server.r17_transition_started_at
        server.handle_r17_command(command("left-1", "LEFT"))
        assert server.r17_transition_started_at == started_at
        assert emitted[-1]["status"] == "APPLYING"
        assert "Duplicate" in emitted[-1]["message"]
        finish(server)
        assert_target(server, "LEFT", -15)

        server.handle_r17_command(command("right-1", "RIGHT"))
        finish(server)
        assert_target(server, "RIGHT", 15)

        server.handle_r17_command(command("home-1", "HOME"))
        finish(server)
        assert_target(server, "HOME", 0)
    finally:
        portal.send_json = original_send

    print(
        {
            "cubePath": portal.MEMORY_CUBE_PATH,
            "homeRelativeTargets": [-15, 0, 15],
            "duplicateRequestRestarted": False,
            "alreadyActiveRestarted": False,
            "rotationScalePreserved": True,
            "homeRestoredExactly": True,
        }
    )


if __name__ == "__main__":
    main()
