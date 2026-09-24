#!/usr/bin/env python3
"""Focused non-rendering checks for R-17 Robot Vision.

Covers the parts of the ROBOT_VISION_CONTRACT that do not need a GPU:
the `render.setMode` request state machine, the app-owned SemanticsAPI layer
text, the `SemanticIdMap` decoder, and the candy-color semantic-ID conversion.
Use `browser_robot_vision_smoke.py` for the live rendered evidence.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

import attic_portal_server as portal
import r17_robot_vision as vision


def make_server() -> portal.AtticPortalServer:
    server = portal.AtticPortalServer.__new__(portal.AtticPortalServer)
    server.stream = object()
    server.frame_index = 0
    server.width = 8
    server.height = 4
    server.bgra = None
    server.last_error = ""
    # Memory Cube Link state read by r17_state_payload().
    server.r17_cube_path = portal.MEMORY_CUBE_PATH
    server.r17_home_transform = None
    server.r17_current_transform = None
    server.r17_requested_pose = "HOME"
    server.r17_offset_x = 0
    server.r17_transition_active = False
    server.r17_seen_request_ids = set()
    server.r17_active_request_id = None
    server.r17_pending_ready_request_id = None
    # Camera-preset state read by r17_state_payload().
    server.r17_active_view = "DEFAULT"
    server.r17_focus_camera_path = "/Session/Cameras/R17CubeFocus"
    server.r17_camera_layer = portal.CAMERA_LAYER
    server.r17_active_view_request_id = None
    server.r17_pending_view_request_id = None
    # Robot Vision state.
    server.r17_semantics_layer = portal.SEMANTICS_LAYER
    server.r17_render_mode = "BEAUTY"
    server.r17_available_outputs = [vision.BEAUTY_OUTPUT, vision.SEMANTIC_OUTPUT, vision.SEMANTIC_ID_MAP_OUTPUT]
    server.r17_output_keys = sorted(server.r17_available_outputs)
    server.r17_semantic_id_map = {}
    server.r17_semantic_unique_ids = []
    server.r17_semantic_nonzero_pixels = 0
    server.r17_semantic_label_count = 0
    server.r17_cube_semantic_class = portal.CUBE_SEMANTIC_CLASS
    server.r17_cube_semantic_label = portal.CUBE_SEMANTIC_LABEL
    server.r17_active_render_request_id = None
    server.r17_pending_render_request_id = None
    server.r17_render_frame_error = ""
    server.r17_status = "READY"
    server.r17_message = "Memory Cube Link ready"
    server.r17_error = ""
    return server


def command(request_id: str, mode: object) -> dict:
    return {"requestId": request_id, "command": portal.R17_RENDER_COMMAND, "payload": {"mode": mode}}


def check_render_mode_state_machine(published: list[dict]) -> dict:
    server = make_server()

    # A valid mode stays APPLYING until the frame that used it was streamed.
    server.handle_r17_render_command("sem-1", command("sem-1", "SEMANTIC"))
    assert server.r17_render_mode == "SEMANTIC", server.r17_render_mode
    assert server.r17_status == "APPLYING", server.r17_status
    assert published[-1]["status"] == "APPLYING", published[-1]
    server.complete_r17_render_after_render()
    assert server.r17_status == "READY", server.r17_status
    assert published[-1]["status"] == "READY" and published[-1]["renderMode"] == "SEMANTIC", published[-1]

    # A duplicate requestId acknowledges without re-applying.
    server.handle_r17_render_command("sem-1", command("sem-1", "BEAUTY"))
    assert server.r17_render_mode == "SEMANTIC", server.r17_render_mode
    assert server.r17_pending_render_request_id is None

    # The already-active mode acknowledges READY without another frame.
    server.handle_r17_render_command("sem-2", command("sem-2", "SEMANTIC"))
    assert server.r17_pending_render_request_id is None
    assert published[-1]["status"] == "READY", published[-1]

    # Only one render mode request may be in flight.
    server.handle_r17_render_command("beauty-1", command("beauty-1", "BEAUTY"))
    assert server.r17_pending_render_request_id == "beauty-1"
    server.handle_r17_render_command("beauty-2", command("beauty-2", "SEMANTIC"))
    assert published[-1]["status"] == "ERROR", published[-1]
    assert server.r17_render_mode == "BEAUTY", server.r17_render_mode
    server.complete_r17_render_after_render()
    assert server.r17_render_mode == "BEAUTY" and server.r17_status == "READY"

    # An invalid output request falls back safely to BEAUTY.
    server.r17_render_mode = "SEMANTIC"
    server.handle_r17_render_command("bad-1", command("bad-1", "SEMANTIC_SD"))
    assert server.r17_render_mode == "BEAUTY", server.r17_render_mode
    assert published[-1]["status"] == "ERROR" and published[-1]["renderMode"] == "BEAUTY", published[-1]

    # A frame that failed to convert reports ERROR and leaves BEAUTY streaming.
    server.r17_status = "READY"
    server.handle_r17_render_command("sem-3", command("sem-3", "SEMANTIC"))
    server.r17_render_mode = "BEAUTY"
    server.r17_render_frame_error = "SemanticSegmentation output missing"
    server.complete_r17_render_after_render()
    assert published[-1]["status"] == "ERROR", published[-1]
    assert server.r17_render_mode == "BEAUTY" and server.r17_render_frame_error == ""

    payload = server.r17_state_payload(request_id="final")
    for key in ("renderMode", "availableOutputs", "outputKeys", "semanticsLayer", "semanticIdMap",
                "semanticUniqueIds", "semanticNonzeroPixels", "cubeSemanticClass", "cubeSemanticLabel"):
        assert key in payload, key
    return {
        "modes": sorted(portal.R17_RENDER_MODES),
        "duplicateReapplied": False,
        "concurrentRequestRejected": True,
        "invalidModeFallback": "BEAUTY",
        "frameErrorFallback": "BEAUTY",
        "statePayloadFields": sorted(k for k in payload if k.startswith("semantic") or k in {"renderMode", "availableOutputs", "outputKeys", "cubeSemanticClass", "cubeSemanticLabel"}),
    }


def check_semantics_layer() -> dict:
    paths = ["/Root/Geometry/chair_471", "/Root/Geometry/chest_473", "/Root/Geometry/telescope_537"]
    with tempfile.TemporaryDirectory() as tmp:
        layer = Path(tmp) / "R17_Semantics.usda"
        vision.write_r17_semantics_layer(
            layer,
            root_path="/Root",
            cube_path=portal.MEMORY_CUBE_PATH,
            environment_paths=paths,
        )
        text = layer.read_text(encoding="utf-8")
    for needle in ('SemanticsAPI:label', 'SemanticsAPI:class', 'attic_environment', 'retrieval_target',
                   'memory_cube', 'chair_471', 'chest_473', 'telescope_537'):
        assert needle in text, needle
    # Scene object roots only; never RenderProduct/RenderVar prims.
    for forbidden in ("RenderProduct", "RenderVar", "MemoryCubeGlow"):
        assert forbidden not in text, forbidden
    assert text.count('semanticType = "class"') == len(paths) + 1
    assert text.count('semanticType = "label"') == len(paths) + 1
    return {
        "environmentLabels": len(paths),
        "cubeClassLabel": [portal.CUBE_SEMANTIC_CLASS, portal.CUBE_SEMANTIC_LABEL],
        "glowLabeled": False,
    }


def check_semantic_id_map_decode() -> dict:
    labels = {3: "class: attic_environment; label: chair_471;", 7: "class: retrieval_target; label: memory_cube;"}
    entry_dtype = np.dtype([("id", "<u4", (4)), ("label_length", "<u4"), ("label_offset", "<u4")])
    header = np.zeros(len(labels), dtype=entry_dtype)
    blob = bytearray(header.nbytes)
    for index, (semantic_id, label) in enumerate(labels.items()):
        encoded = label.encode("utf-8")
        header[index]["id"][0] = semantic_id
        header[index]["label_offset"] = len(blob)
        header[index]["label_length"] = len(encoded)
        blob.extend(encoded)
    blob[: header.nbytes] = header.tobytes()
    blob.extend(int(len(labels)).to_bytes(4, "little"))
    decoded = vision.decode_semantic_id_map_tensor(np.frombuffer(bytes(blob), dtype=np.uint8))
    assert decoded == labels, decoded
    assert vision.decode_semantic_id_map_tensor(np.zeros(2, dtype=np.uint8)) == {}
    return {"decodedIds": sorted(decoded), "truncatedBufferSafe": True}


def check_candy_colors() -> dict:
    height, width = 4, 8
    ids = np.zeros((height, width, 1), dtype=np.uint32)
    ids[0, :, 0] = 1
    ids[1, :, 0] = 2
    ids[2, :, 0] = 7
    bgra = vision.candy_colorize_semantic_ids(ids, height, width)
    assert bgra.shape == (height, width, 4) and bgra.dtype == np.uint8, (bgra.shape, bgra.dtype)
    # ID 0 stays black/unlabeled; every labeled ID gets a distinct bright color.
    assert (bgra[3] == np.array([0, 0, 0, 255], dtype=np.uint8)).all()
    labeled = {tuple(int(v) for v in bgra[row, 0]) for row in (0, 1, 2)}
    assert len(labeled) == 3, labeled
    assert all(max(color[:3]) >= 180 for color in labeled), labeled
    assert (bgra[:, :, 3] == 255).all()
    return {"idZeroBlack": True, "distinctColors": len(labeled), "channels": "BGRA"}


def main() -> None:
    published: list[dict] = []
    original_send = portal.send_json
    portal.send_json = lambda stream, event_type, payload: published.append(payload)
    try:
        state_machine = check_render_mode_state_machine(published)
    finally:
        portal.send_json = original_send

    print(
        {
            "renderModeStateMachine": state_machine,
            "semanticsLayer": check_semantics_layer(),
            "semanticIdMap": check_semantic_id_map_decode(),
            "candyColors": check_candy_colors(),
            "semanticOutput": vision.SEMANTIC_OUTPUT,
            "semanticIdMapOutput": vision.SEMANTIC_ID_MAP_OUTPUT,
            "beautyOutput": vision.BEAUTY_OUTPUT,
        }
    )


if __name__ == "__main__":
    main()
