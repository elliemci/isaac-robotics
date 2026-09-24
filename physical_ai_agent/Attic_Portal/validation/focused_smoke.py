#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSION_ROOT = ROOT.parent
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8081/state.json")
HEALTH_URL = os.environ.get("HEALTH_URL", "http://127.0.0.1:8081/healthz")
BASE_STAGE = SESSION_ROOT / "Attic_NVIDIA/Attic_NVIDIA.usd"
MISSION_STAGE = SESSION_ROOT / "Attic_NVIDIA/OldAttic_Mission.usda"
EXPECTED_HASHES = {
    str(BASE_STAGE): "12db25c282bcf57ba371381d96c5ea11dd0709386493b27e99b2c6c70992502c",
    str(MISSION_STAGE): "80b9adfcef7a587caddd0eb04dfa85d84baff52f4bb80712d9f19bad29657739",
}


def read_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.read()


def wait_json(url: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return json.loads(read_url(url))
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_contains(path: Path, pattern: str) -> None:
    if not re.search(pattern, path.read_text(encoding="utf-8"), flags=re.MULTILINE):
        raise AssertionError(f"{path} missing pattern {pattern!r}")


def assert_not_contains(path: Path, pattern: str) -> None:
    if re.search(pattern, path.read_text(encoding="utf-8"), flags=re.MULTILINE):
        raise AssertionError(f"{path} unexpectedly contains {pattern!r}")


def main() -> None:
    health = read_url(HEALTH_URL).decode("utf-8")
    state = wait_json(STATE_URL)
    if health != "ok" or not state.get("ready"):
        raise AssertionError({"health": health, "state_ready": state.get("ready")})
    if state.get("renderer_owner_count") != 1:
        raise AssertionError(f"renderer_owner_count={state.get('renderer_owner_count')}")
    if state.get("mission_cube_matches") != [["/Root/Workshop/Cube", "Memory Cube"]]:
        raise AssertionError(f"mission_cube_matches={state.get('mission_cube_matches')}")
    resolution = state.get("resolution") or {}
    if resolution.get("width", 0) <= 0 or resolution.get("height", 0) <= 0:
        raise AssertionError(f"invalid resolution={resolution}")
    if state.get("frame_index", 0) <= 0:
        raise AssertionError(f"invalid frame_index={state.get('frame_index')}")

    r17 = state.get("r17") or {}
    if r17.get("cubePath") != "/Root/Workshop/Cube":
        raise AssertionError(f"cubePath={r17.get('cubePath')}")
    if not r17.get("moduleInstalled"):
        raise AssertionError("r17.moduleInstalled is false")
    if r17.get("status") != "READY" or r17.get("transitionActive"):
        raise AssertionError({"status": r17.get("status"), "transitionActive": r17.get("transitionActive")})
    if r17.get("requestedPose") not in {"LEFT", "HOME", "RIGHT"}:
        raise AssertionError(f"requestedPose={r17.get('requestedPose')}")
    if r17.get("offsetX") not in {-15, 0, 15}:
        raise AssertionError(f"offsetX={r17.get('offsetX')}")
    home = r17.get("homeTransformRowMajor") or []
    current = r17.get("currentTransformRowMajor") or []
    if len(home) != 4 or len(current) != 4:
        raise AssertionError({"home": home, "current": current})
    expected_x = home[3][0] + r17["offsetX"]
    if abs(current[3][0] - expected_x) > 1e-9:
        raise AssertionError({"currentX": current[3][0], "expectedX": expected_x})
    rotation_scale_ok = all(abs(current[r][c] - home[r][c]) <= 1e-9 for r in range(3) for c in range(4))
    if not rotation_scale_ok or abs(current[3][1] - home[3][1]) > 1e-9 or abs(current[3][2] - home[3][2]) > 1e-9:
        raise AssertionError({"home": home, "current": current})

    panel = ROOT / "frontend/src/components/R17SignalPanel.tsx"
    button = ROOT / "frontend/src/components/R17CommandButton.tsx"
    sender = ROOT / "frontend/src/hooks/useR17CommandSender.ts"
    subscription = ROOT / "frontend/src/hooks/useR17StateSubscription.ts"
    types = ROOT / "frontend/src/types/r17.ts"
    app = ROOT / "frontend/src/App.tsx"
    styles = ROOT / "frontend/src/styles.css"
    assert_contains(panel, "cube\\.setPose")
    assert_contains(panel, "r17-pose-controls")
    assert_contains(panel, "LEFT POSE -15")
    assert_contains(panel, "RIGHT POSE \\+15")
    assert_contains(panel, "onRequestStart=\\{setInFlightRequestId\\}")
    assert_contains(panel, "disabled=\\{controlsDisabled\\}")
    assert_contains(styles, "\\.r17-pose-controls")
    assert_contains(types, "R17Pose")
    assert_contains(types, "isR17OffsetX")
    assert_contains(button, "presentationFromState")
    assert_contains(button, "disabled \\|\\| Boolean\\(requestId\\)")
    assert_contains(sender, "sendR17Command")
    assert_contains(types, "r17-command-v1")
    assert_contains(types, "r17-state-v1")
    assert_contains(types, "isNonemptyRequestId")
    assert_contains(types, "DEFAULT_VIEW_PRESET")
    assert_contains(subscription, "event.payload.requestId !== requestId")
    assert_contains(app, "setViewportInputActive\\(false\\)")

    # One provider, one protocol, one stream, one renderer owner.
    server_source = ROOT / "server/attic_portal_server.py"
    assert_contains(server_source, "self.advance_r17_transition\\(\\)")
    assert_contains(server_source, "self.complete_r17_transition_after_render\\(\\)")
    assert_contains(server_source, "Duplicate request")
    assert_contains(server_source, "already active")
    for source in (ROOT / "frontend/src").rglob("*"):
        if source.is_file() and source.suffix in {".ts", ".tsx"}:
            if source.name != "StreamingProvider.tsx":
                assert_not_contains(source, "AppStreamer\\.connect|new RTCPeerConnection")
            assert_not_contains(source, "three|babylon|@react-three")
    if len(list((ROOT / "frontend/src/streaming").glob("*.tsx"))) != 1:
        raise AssertionError("expected exactly one streaming provider module")

    hashes = {path: sha256(Path(path)) for path in EXPECTED_HASHES}
    if hashes != EXPECTED_HASHES:
        raise AssertionError({"hashes": hashes, "expected": EXPECTED_HASHES})

    report = {
        "health": health,
        "ready": state["ready"],
        "renderer_owner_count": state["renderer_owner_count"],
        "first_valid_converted_frame": {
            "frame_index": state["frame_index"],
            "width": resolution["width"],
            "height": resolution["height"],
            "artifact": state["first_frame"],
        },
        "mission_cube_matches": state["mission_cube_matches"],
        "runtime_mission_role_query": state.get("runtime_mission_role_query"),
        "r17_cube_link": {
            "cubePath": r17["cubePath"],
            "status": r17["status"],
            "requestedPose": r17["requestedPose"],
            "offsetX": r17["offsetX"],
            "transitionActive": r17["transitionActive"],
            "homeTranslate": home[3][0:3],
            "currentTranslate": current[3][0:3],
            "rotationScaleUnchanged": rotation_scale_ok,
        },
        "source_hashes": hashes,
    }
    out = ROOT / "artifacts/focused-smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
