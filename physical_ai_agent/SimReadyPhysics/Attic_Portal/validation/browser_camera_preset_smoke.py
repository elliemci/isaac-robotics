#!/usr/bin/env python3
"""Focused camera check for the R-17 DEFAULT VIEW and CUBE FOCUS presets.

Drives a real Firefox through geckodriver's W3C HTTP endpoints (the same
transport browser_cube_link_check.py uses on this host, so no selenium
dependency is required) and asserts server-authoritative r17-state-v1 /
state.json results for both camera presets plus native orbit, pan, and zoom.

Checks, in order:

1. Live WebRTC video, one video track, and an enabled DEFAULT VIEW / CUBE FOCUS
   control pair.
2. The focus envelope is the union of the LEFT, HOME, and RIGHT cube bounds.
3. CUBE FOCUS frames every corner of that envelope with attic context around it.
4. The focused frame is not black.
5. DEFAULT VIEW restores the Part 1 fitted startup pose and lens exactly.
6. Native orbit, pan, and zoom each still work and each report CUSTOM.
7. One renderer, one RenderProduct, one video track throughout.

Environment overrides: URL, STATE_URL, GECKODRIVER, WEBDRIVER_PORT,
ARTIFACT_DIR, CAMERA_LAYER, HEADLESS.
"""

from __future__ import annotations

import base64
import json
import math
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
CLIENT_PORT = os.environ.get("ATTIC_PORTAL_CLIENT_PORT", "5176")
SERVER_HOST = os.environ.get("VITE_SERVER_HOST", "127.0.0.1")
SIGNALING_PORT = os.environ.get("ATTIC_PORTAL_SIGNALING_PORT", "49101")
HEALTH_PORT = os.environ.get("ATTIC_PORTAL_HEALTH_PORT", "8082")
URL = os.environ.get("URL", f"http://127.0.0.1:{CLIENT_PORT}/?server={SERVER_HOST}&signalingport={SIGNALING_PORT}")
STATE_URL = os.environ.get("STATE_URL", f"http://127.0.0.1:{HEALTH_PORT}/state.json")
GECKODRIVER = os.environ.get("GECKODRIVER", shutil.which("geckodriver") or "geckodriver")
WEBDRIVER_PORT = int(os.environ.get("WEBDRIVER_PORT", "4444"))
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", str(ROOT / "artifacts")))
CAMERA_LAYER = Path(os.environ.get("CAMERA_LAYER", str(ROOT / "usd" / "R17_Camera.usda")))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

FOCUS_CAMERA_PATH = "/Session/Cameras/R17CubeFocus"
ACTIVE_VIEWER_CAMERA = "/OVCamera"
RENDER_PRODUCT = "/Render/OVServer/ViewportTexture0"
VIEW_LABELS = {"DEFAULT": "DEFAULT VIEW", "CUBE_FOCUS": "CUBE FOCUS"}
POSE_OFFSET_SPAN = 30.0  # RIGHT(+15) minus LEFT(-15)
# Part 1 fitted startup preset (see DEFAULT_VIEW_PRESET in frontend/src/types/r17.ts).
DEFAULT_CAMERA = {"target": [-620.0, -1125.0, 121.0], "distance": 455.0, "azimuth": 0.0, "elevation": 0.34}
DEFAULT_LENS = {"focalLength": 24.0, "horizontalAperture": 20.955}
H_APERTURE = 20.955
V_APERTURE = H_APERTURE * 540.0 / 960.0
FOCAL_LENGTH = 35.0
# The framed envelope may fill at most this fraction of each half-FOV, which is
# what keeps surrounding attic context in shot.
FRAME_MARGIN = 0.86


class WebDriver:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.session_id: str | None = None

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            raise RuntimeError(f"webdriver {method} {path} failed: {exc.code} {detail}") from None

    def wait_ready(self, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.request("GET", "/status")
                return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError(f"geckodriver did not become ready on {self.base}")

    def start_session(self, headless: bool) -> str:
        args = ["--width=1280", "--height=900"]
        if headless:
            args.insert(0, "-headless")
        response = self.request(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "firefox",
                        "moz:firefoxOptions": {
                            "args": args,
                            # A fresh WebDriver profile blocks loopback ICE and
                            # obfuscates host candidates, which fails the
                            # ovstream handshake with "No ICE candidate pairs
                            # were nominated."
                            "prefs": {
                                "media.autoplay.default": 0,
                                "media.autoplay.blocking_policy": 0,
                                "media.peerconnection.ice.loopback": True,
                                "media.peerconnection.ice.obfuscate_host_addresses": False,
                                "media.navigator.permission.disabled": True,
                            },
                        },
                    }
                }
            },
        )
        self.session_id = response["value"]["sessionId"]
        return self.session_id

    def session(self, method: str, path: str, body: dict | None = None) -> dict:
        return self.request(method, f"/session/{self.session_id}{path}", body)

    def navigate(self, url: str) -> None:
        self.session("POST", "/url", {"url": url})

    def script(self, source: str) -> object:
        return self.session("POST", "/execute/sync", {"script": source, "args": []})["value"]

    def elements(self, css: str) -> list[str]:
        found = self.session("POST", "/elements", {"using": "css selector", "value": css})["value"]
        return [element[ELEMENT_KEY] for element in found]

    def element(self, css: str) -> str:
        return self.session("POST", "/element", {"using": "css selector", "value": css})["value"][ELEMENT_KEY]

    def text(self, element_id: str) -> str:
        return str(self.session("GET", f"/element/{element_id}/text")["value"]).strip()

    def rect(self, element_id: str) -> dict:
        return self.session("GET", f"/element/{element_id}/rect")["value"]

    def enabled(self, element_id: str) -> bool:
        return bool(self.session("GET", f"/element/{element_id}/enabled")["value"])

    def click(self, element_id: str) -> None:
        self.session("POST", f"/element/{element_id}/click", {})

    def view_buttons(self) -> dict[str, str]:
        return {self.text(element_id): element_id for element_id in self.elements(".r17-view-controls button")}

    def perform(self, actions: list[dict]) -> None:
        self.session("POST", "/actions", {"actions": actions})
        self.session("DELETE", "/actions")

    def pointer_drag(self, rect: dict, button: int, dx: int, dy: int) -> None:
        start_x = int(rect["x"] + rect["width"] * 0.45)
        start_y = int(rect["y"] + rect["height"] * 0.52)
        self.perform(
            [
                {
                    "type": "pointer",
                    "id": "mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": start_x, "y": start_y},
                        {"type": "pointerDown", "button": button},
                        {"type": "pause", "duration": 150},
                        {"type": "pointerMove", "duration": 150, "x": start_x + dx // 2, "y": start_y + dy // 2},
                        {"type": "pointerMove", "duration": 150, "x": start_x + dx, "y": start_y + dy},
                        {"type": "pause", "duration": 150},
                        {"type": "pointerUp", "button": button},
                    ],
                }
            ]
        )

    def wheel(self, rect: dict, delta_y: int) -> None:
        x = int(rect["x"] + rect["width"] * 0.45)
        y = int(rect["y"] + rect["height"] * 0.52)
        self.perform(
            [
                {
                    "type": "pointer",
                    "id": "mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [{"type": "pointerMove", "duration": 0, "x": x, "y": y}],
                },
                {
                    "type": "wheel",
                    "id": "wheel",
                    "actions": [{"type": "scroll", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y, "duration": 150}],
                },
            ]
        )

    def screenshot(self, destination: Path) -> None:
        encoded = self.session("GET", "/screenshot")["value"]
        destination.write_bytes(base64.b64decode(encoded))

    def quit(self) -> None:
        if self.session_id:
            try:
                self.session("DELETE", "")
            except Exception:
                pass
            self.session_id = None


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=5) as response:
        return json.load(response)


def wait_until(predicate, timeout: float, description: str):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {description}: {last!r}")


def wait_view(view: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        last = get_state()
        r17 = last["r17"]
        if r17.get("status") == "READY" and r17.get("activeView") == view:
            return last
        time.sleep(0.05)
    raise AssertionError({"wantedView": view, "last": last})


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def cross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a: list[float], b: list[float]) -> float:
    return sum(a[i] * b[i] for i in range(3))


def camera_basis(cam: dict):
    """Z-up orbit basis, matching server/camera_controller.py."""

    target = [float(v) for v in cam["target"]]
    distance = float(cam["distance"])
    az = float(cam["azimuth"])
    el = float(cam["elevation"])
    ce = math.cos(el)
    eye = [
        target[0] + math.sin(az) * ce * distance,
        target[1] - math.cos(az) * ce * distance,
        target[2] + math.sin(el) * distance,
    ]
    forward = normalize([target[i] - eye[i] for i in range(3)])
    right = normalize(cross(forward, [0.0, 0.0, 1.0]))
    up = normalize(cross(right, forward))
    return eye, forward, right, up


def camera_signature(state: dict) -> list:
    cam = state["camera_state"]
    return [
        round(float(cam["azimuth"]), 6),
        round(float(cam["elevation"]), 6),
        round(float(cam["distance"]), 6),
        [round(float(v), 6) for v in cam["target"]],
    ]


def assert_default_camera(state: dict) -> dict:
    cam = state["camera_state"]
    for key in ("distance", "azimuth", "elevation"):
        if not math.isclose(float(cam[key]), DEFAULT_CAMERA[key], abs_tol=1e-6):
            raise AssertionError({"key": key, "camera": cam, "expected": DEFAULT_CAMERA})
    for got, expected in zip(cam["target"], DEFAULT_CAMERA["target"]):
        if not math.isclose(float(got), expected, abs_tol=1e-6):
            raise AssertionError({"target": cam["target"], "expected": DEFAULT_CAMERA["target"]})
    lens = (state.get("camera_presets") or {}).get("DEFAULT") or {}
    for key, expected in DEFAULT_LENS.items():
        if not math.isclose(float(lens.get(key, 0.0)), expected, abs_tol=1e-6):
            raise AssertionError({"lens": lens, "expected": DEFAULT_LENS})
    return {"activeView": state["r17"]["activeView"], "camera": cam, "lens": lens}


def assert_envelope_is_pose_union(state: dict) -> dict:
    """The focus bounds must be the union of the LEFT, HOME, and RIGHT poses."""

    presets = state["camera_presets"]
    bmin = [float(v) for v in presets["focusBoundsMin"]]
    bmax = [float(v) for v in presets["focusBoundsMax"]]
    home = state["r17"]["homeTransformRowMajor"][3][0:3]
    span = [bmax[i] - bmin[i] for i in range(3)]
    center = [(bmax[i] + bmin[i]) * 0.5 for i in range(3)]
    for i in range(3):
        if not math.isclose(center[i], float(home[i]), abs_tol=1e-6):
            raise AssertionError({"envelopeNotCenteredOnHome": center, "home": home})
    # Only X widens, and by exactly the LEFT..RIGHT offset span.
    if not math.isclose(span[0] - span[1], POSE_OFFSET_SPAN, abs_tol=1e-6):
        raise AssertionError({"span": span, "expectedExtraX": POSE_OFFSET_SPAN})
    if not math.isclose(span[1], span[2], abs_tol=1e-6):
        raise AssertionError({"span": span})
    if sorted(presets.get("poseOffsets") or []) != [-15, 0, 15]:
        raise AssertionError({"poseOffsets": presets.get("poseOffsets")})
    return {"boundsMin": bmin, "boundsMax": bmax, "span": span, "homeTranslate": [float(v) for v in home]}


def assert_focus_frames_bounds(state: dict) -> dict:
    cam = state["camera_state"]
    presets = state["camera_presets"]
    bmin = [float(v) for v in presets["focusBoundsMin"]]
    bmax = [float(v) for v in presets["focusBoundsMax"]]
    eye, forward, right, up = camera_basis(cam)
    tan_x = math.tan(2.0 * math.atan(H_APERTURE / (2.0 * FOCAL_LENGTH)) * 0.5)
    tan_y = math.tan(2.0 * math.atan(V_APERTURE / (2.0 * FOCAL_LENGTH)) * 0.5)
    max_abs_x = 0.0
    max_abs_y = 0.0
    min_depth = 1e9
    for x in (bmin[0], bmax[0]):
        for y in (bmin[1], bmax[1]):
            for z in (bmin[2], bmax[2]):
                rel = [x - eye[0], y - eye[1], z - eye[2]]
                depth = dot(rel, forward)
                if depth <= 1.0:
                    raise AssertionError({"cornerBehindCamera": [x, y, z], "depth": depth})
                nx = dot(rel, right) / depth
                ny = dot(rel, up) / depth
                max_abs_x = max(max_abs_x, abs(nx))
                max_abs_y = max(max_abs_y, abs(ny))
                min_depth = min(min_depth, depth)
                if abs(nx) > tan_x * FRAME_MARGIN or abs(ny) > tan_y * FRAME_MARGIN:
                    raise AssertionError(
                        {"cornerOutsideFocusFrame": [x, y, z], "nx": nx, "ny": ny, "tanX": tan_x, "tanY": tan_y}
                    )
    focus_lens = presets.get("CUBE_FOCUS") or {}
    if not math.isclose(float(focus_lens.get("focalLength", 0.0)), FOCAL_LENGTH, abs_tol=1e-6):
        raise AssertionError({"focusLens": focus_lens})
    return {
        "activeView": state["r17"]["activeView"],
        "boundsMin": bmin,
        "boundsMax": bmax,
        "maxAbsX": max_abs_x,
        "maxAbsY": max_abs_y,
        "minDepth": min_depth,
        "horizontalFill": max_abs_x / tan_x,
        "verticalFill": max_abs_y / tan_y,
        "lens": focus_lens,
    }


def assert_focus_visual_not_black(driver: WebDriver, video_rect: dict) -> dict:
    artifact = ARTIFACT_DIR / "r17-cube-focus-visual.png"
    driver.screenshot(artifact)
    image = Image.open(artifact).convert("RGB")
    left = max(0, int(video_rect["x"]))
    top = max(0, int(video_rect["y"]))
    right = min(image.width, int(video_rect["x"] + video_rect["width"] * 0.68))
    bottom = min(image.height, int(video_rect["y"] + video_rect["height"]))
    crop = image.crop((left, top, right, bottom))
    stat = ImageStat.Stat(crop)
    mean_rgb = sum(stat.mean) / 3.0
    variance = sum(stat.var) / 3.0
    result = {"artifact": str(artifact), "crop": [left, top, right, bottom], "meanRgb": mean_rgb, "variance": variance}
    if mean_rgb < 8.0 or variance < 2.0:
        raise AssertionError({"focusFrameLooksBlack": result})
    return result


def click_view(driver: WebDriver, view: str) -> None:
    label = VIEW_LABELS[view]

    def ready() -> dict | None:
        buttons = driver.view_buttons()
        if label in buttons and driver.enabled(buttons[label]):
            return buttons
        return None

    buttons = wait_until(ready, timeout=30.0, description=f"enabled {label} control")
    driver.click(buttons[label])


def assert_single_stream(state: dict) -> dict:
    health = {
        "ready": state["ready"],
        "rendererOwnerCount": state["renderer_owner_count"],
        "renderProduct": state["render_product"],
        "activeViewerCamera": state["camera"],
        "frameIndex": state["frame_index"],
        "lastError": state["last_error"],
    }
    if not state["ready"] or state["renderer_owner_count"] != 1 or state["last_error"]:
        raise AssertionError(health)
    if state["camera"] != ACTIVE_VIEWER_CAMERA or state["render_product"] != RENDER_PRODUCT:
        raise AssertionError(health)
    return health


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    layer_text = CAMERA_LAYER.read_text(encoding="utf-8") if CAMERA_LAYER.exists() else ""
    if 'def Camera "R17CubeFocus"' not in layer_text:
        raise AssertionError(f"camera layer missing focus camera: {CAMERA_LAYER}")

    results: dict[str, object] = {
        "url": URL,
        "stateUrl": STATE_URL,
        "headless": HEADLESS,
        "cameraLayer": str(CAMERA_LAYER),
    }
    log = (ROOT / "logs" / "geckodriver-camera-focus.log").open("wb")
    driver_process = subprocess.Popen(
        [GECKODRIVER, "--port", str(WEBDRIVER_PORT), "--log", "info"], stdout=log, stderr=subprocess.STDOUT
    )
    driver = WebDriver(WEBDRIVER_PORT)
    try:
        driver.wait_ready()
        driver.start_session(HEADLESS)
        driver.navigate(URL)

        seen: dict[str, object] = {}

        def live_video() -> dict | None:
            state = driver.script(
                "const v = document.getElementById('remote-video');"
                "return v ? {readyState: v.readyState, width: v.videoWidth, height: v.videoHeight, paused: v.paused} : null;"
            )
            seen["video"] = state
            if not state:
                return None
            ok = state["readyState"] >= 2 and state["width"] > 0 and state["height"] > 0 and not state["paused"]
            return state if ok else None

        try:
            results["video"] = wait_until(live_video, timeout=90.0, description="live WebRTC video frames")
        except AssertionError:
            raise AssertionError(f"no live WebRTC video; last video state={seen.get('video')!r}") from None

        results["videoTracks"] = driver.script(
            "const v = document.getElementById('remote-video');"
            "const s = v && v.srcObject; return s ? s.getVideoTracks().length : -1;"
        )
        if results["videoTracks"] != 1:
            raise AssertionError({"expectedOneVideoTrack": results["videoTracks"]})

        panel_text = "return document.querySelector('.r17-signal-panel').innerText;"
        results["panelFocusCamera"] = wait_until(
            lambda: FOCUS_CAMERA_PATH if FOCUS_CAMERA_PATH in str(driver.script(panel_text)) else None,
            timeout=30.0,
            description=f"{FOCUS_CAMERA_PATH} displayed in the R-17 panel",
        )
        results["viewButtonLabels"] = sorted(
            wait_until(
                lambda: (lambda b: b if {"DEFAULT VIEW", "CUBE FOCUS"} <= set(b) else None)(driver.view_buttons()),
                timeout=30.0,
                description="DEFAULT VIEW and CUBE FOCUS controls",
            )
        )
        video_rect = driver.rect(driver.element("#remote-video"))

        initial = wait_view("DEFAULT", timeout=30.0)
        results["initial"] = assert_default_camera(initial)
        results["envelope"] = assert_envelope_is_pose_union(initial)

        # 1. CUBE FOCUS frames the whole three-pose envelope.
        click_view(driver, "CUBE_FOCUS")
        results["cubeFocus"] = assert_focus_frames_bounds(wait_view("CUBE_FOCUS"))
        time.sleep(1.0)
        results["cubeFocusVisual"] = assert_focus_visual_not_black(driver, video_rect)
        results["panelReportsCubeFocus"] = wait_until(
            lambda: "CUBE_FOCUS" if "CUBE_FOCUS" in str(driver.script(panel_text)) else None,
            timeout=10.0,
            description="panel readout showing CUBE_FOCUS",
        )

        # 2. DEFAULT VIEW restores the Part 1 startup preset.
        click_view(driver, "DEFAULT")
        results["defaultView"] = assert_default_camera(wait_view("DEFAULT"))

        # 3. Orbit still works and reports CUSTOM.
        before_orbit = camera_signature(get_state())
        driver.pointer_drag(video_rect, button=0, dx=140, dy=90)
        orbit_state = wait_view("CUSTOM")
        after_orbit = camera_signature(orbit_state)
        if after_orbit[:2] == before_orbit[:2]:
            raise AssertionError({"orbitDidNotRotate": after_orbit, "before": before_orbit})
        results["customAfterOrbit"] = {"activeView": orbit_state["r17"]["activeView"], "camera": after_orbit}
        results["panelReportsCustom"] = wait_until(
            lambda: "CUSTOM" if "CUSTOM" in str(driver.script(panel_text)) else None,
            timeout=10.0,
            description="panel readout showing CUSTOM",
        )

        # 4. Pan still works from a preset and reports CUSTOM.
        click_view(driver, "CUBE_FOCUS")
        before_pan = camera_signature(wait_view("CUBE_FOCUS"))
        driver.pointer_drag(video_rect, button=1, dx=100, dy=55)
        pan_state = wait_view("CUSTOM")
        after_pan = camera_signature(pan_state)
        if after_pan[3] == before_pan[3]:
            raise AssertionError({"panDidNotChangeTarget": after_pan, "before": before_pan})
        results["customAfterPan"] = {"activeView": pan_state["r17"]["activeView"], "camera": after_pan}

        # 5. Zoom still works from a preset and reports CUSTOM.
        click_view(driver, "CUBE_FOCUS")
        before_zoom = camera_signature(wait_view("CUBE_FOCUS"))
        driver.wheel(video_rect, delta_y=-420)
        zoom_state = wait_view("CUSTOM")
        after_zoom = camera_signature(zoom_state)
        if math.isclose(after_zoom[2], before_zoom[2], abs_tol=1e-6):
            raise AssertionError({"zoomDidNotChangeDistance": after_zoom, "before": before_zoom})
        results["customAfterZoom"] = {"activeView": zoom_state["r17"]["activeView"], "camera": after_zoom}

        # 6. DEFAULT VIEW still restores the startup preset after navigation.
        click_view(driver, "DEFAULT")
        final_state = wait_view("DEFAULT")
        results["finalDefault"] = assert_default_camera(final_state)
        results["streamHealth"] = assert_single_stream(final_state)
        results["focusCameraPath"] = final_state["r17"]["focusCameraPath"]
        if results["focusCameraPath"] != FOCUS_CAMERA_PATH:
            raise AssertionError({"focusCameraPath": results["focusCameraPath"]})

        screenshot = ARTIFACT_DIR / "r17-camera-preset-smoke.png"
        driver.screenshot(screenshot)
        results["screenshot"] = str(screenshot)
        results["result"] = "PASS"
    finally:
        driver.quit()
        driver_process.terminate()
        try:
            driver_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            driver_process.kill()
        log.close()

    out = ARTIFACT_DIR / "r17-camera-preset-smoke.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
