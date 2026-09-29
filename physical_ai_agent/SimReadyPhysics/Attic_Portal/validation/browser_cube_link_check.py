#!/usr/bin/env python3
"""Focused browser check for the R-17 Memory Cube Link.

Drives a real Firefox through geckodriver's W3C HTTP endpoints (the same
transport the prepared launch_and_verify.sh check uses on this host, so no
selenium dependency is required) and asserts server-authoritative
r17-state-v1 / state.json results for every pose control.

Environment overrides: URL, STATE_URL, GECKODRIVER, WEBDRIVER_PORT,
ARTIFACT_DIR, HEADLESS.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

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
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
CUBE_PATH = "/Root/Workshop/Cube"
POSE_LABELS = {"LEFT": "LEFT POSE -15", "HOME": "HOME", "RIGHT": "RIGHT POSE +15"}
TOLERANCE = 1e-9


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

    def pose_buttons(self) -> dict[str, str]:
        elements = self.session(
            "POST", "/elements", {"using": "css selector", "value": ".r17-pose-controls button"}
        )["value"]
        buttons: dict[str, str] = {}
        for element in elements:
            element_id = element[ELEMENT_KEY]
            label = str(self.session("GET", f"/element/{element_id}/text")["value"]).strip()
            buttons[label] = element_id
        return buttons

    def enabled(self, element_id: str) -> bool:
        return bool(self.session("GET", f"/element/{element_id}/enabled")["value"])

    def click(self, element_id: str) -> None:
        self.session("POST", f"/element/{element_id}/click", {})

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


def wait_server_pose(pose: str, offset: int, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        last = get_state()
        r17 = last["r17"]
        if (
            r17["status"] == "READY"
            and r17["requestedPose"] == pose
            and r17["offsetX"] == offset
            and not r17["transitionActive"]
        ):
            return last
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {pose}/{offset}: {last}")


def close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= TOLERANCE


def assert_transform(state: dict, pose: str, offset: int) -> dict:
    r17 = state["r17"]
    home = r17["homeTransformRowMajor"]
    current = r17["currentTransformRowMajor"]
    if not home or not current:
        raise AssertionError({"home": home, "current": current})
    if r17["cubePath"] != CUBE_PATH:
        raise AssertionError(f"unexpected cubePath: {r17['cubePath']}")
    if r17["offsetX"] not in (-15, 0, 15):
        raise AssertionError(f"offsetX out of contract: {r17['offsetX']}")
    rotation_scale_ok = all(close(current[r][c], home[r][c]) for r in range(3) for c in range(4))
    rotation_scale_ok = rotation_scale_ok and close(current[3][3], home[3][3])
    target_ok = (
        close(current[3][0], home[3][0] + offset)
        and close(current[3][1], home[3][1])
        and close(current[3][2], home[3][2])
    )
    if not (rotation_scale_ok and target_ok):
        raise AssertionError({"pose": pose, "offset": offset, "home": home, "current": current})
    return {
        "pose": pose,
        "offsetX": offset,
        "cubePath": r17["cubePath"],
        "translate": current[3][0:3],
        "homeTranslate": home[3][0:3],
        "rotationScaleUnchanged": rotation_scale_ok,
        "targetExactFromHome": target_ok,
        "status": r17["status"],
        "transitionActive": r17["transitionActive"],
    }


def panel_text(driver: WebDriver) -> str:
    return str(driver.script("return document.querySelector('.r17-signal-panel').innerText;"))


def status_line(driver: WebDriver) -> str:
    return str(driver.script("return document.querySelector('.r17-status-line').innerText;"))


def video_state(driver: WebDriver) -> dict:
    return driver.script(
        "const v = document.getElementById('remote-video');"
        "return v ? {readyState: v.readyState, width: v.videoWidth, height: v.videoHeight, paused: v.paused} : null;"
    )


def apply_pose(driver: WebDriver, pose: str, offset: int, results: dict) -> None:
    buttons = driver.pose_buttons()
    label = POSE_LABELS[pose]
    if label not in buttons:
        raise AssertionError(f"button not found: {label}; have {sorted(buttons)}")
    driver.click(buttons[label])
    gated = wait_until(
        lambda: not any(driver.enabled(element_id) for element_id in driver.pose_buttons().values()),
        timeout=2.0,
        description="all pose controls disabled while the request is in flight",
    )
    state = wait_server_pose(pose, offset)
    record = assert_transform(state, pose, offset)
    record["controlsDisabledWhileInFlight"] = bool(gated)
    wait_until(
        lambda: all(driver.enabled(element_id) for element_id in driver.pose_buttons().values()),
        timeout=10.0,
        description="pose controls re-enabled after matching READY state",
    )
    record["controlsReenabledAfterReady"] = True
    results[pose.lower()] = record


def repeat_active_pose(driver: WebDriver, pose: str, results: dict) -> None:
    """Press the already-active pose again: acknowledge, never move."""

    before = get_state()["r17"]
    buttons = driver.pose_buttons()
    driver.click(buttons[POSE_LABELS[pose]])
    moved = False
    deadline = time.time() + 1.5
    while time.time() < deadline:
        probe = get_state()["r17"]
        if probe["transitionActive"] or probe["currentTransformRowMajor"] != before["currentTransformRowMajor"]:
            moved = True
            break
        time.sleep(0.05)
    after = get_state()["r17"]
    acknowledgement = wait_until(
        lambda: status_line(driver) if "already active" in status_line(driver) else None,
        timeout=5.0,
        description="already-active acknowledgement in the panel status line",
    )
    if moved or after["currentTransformRowMajor"] != before["currentTransformRowMajor"]:
        raise AssertionError({"pose": pose, "before": before, "after": after})
    if after["status"] != "READY" or after["requestedPose"] != pose:
        raise AssertionError({"status": after["status"], "requestedPose": after["requestedPose"]})
    results[f"{pose.lower()}Repeat"] = {
        "pose": pose,
        "restartedMovement": moved,
        "transformUnchanged": after["currentTransformRowMajor"] == before["currentTransformRowMajor"],
        "status": after["status"],
        "offsetX": after["offsetX"],
        "acknowledgement": acknowledgement,
    }


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {"url": URL, "stateUrl": STATE_URL, "headless": HEADLESS}
    log = (ROOT / "logs" / "geckodriver-cube-link.log").open("wb")
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
            state = video_state(driver)
            seen["video"] = state
            if not state:
                return None
            ok = state["readyState"] >= 2 and state["width"] > 0 and state["height"] > 0 and not state["paused"]
            return state if ok else None

        try:
            results["video"] = wait_until(live_video, timeout=90.0, description="live WebRTC video frames")
        except AssertionError:
            raise AssertionError(f"no live WebRTC video; last video state={seen.get('video')!r}") from None
        results["panelCubePath"] = wait_until(
            lambda: CUBE_PATH if CUBE_PATH in panel_text(driver) else None,
            timeout=30.0,
            description=f"{CUBE_PATH} displayed in the R-17 panel",
        )
        wait_until(
            lambda: all(driver.enabled(element_id) for element_id in driver.pose_buttons().values()),
            timeout=30.0,
            description="pose controls enabled once the Memory Cube Link is READY",
        )
        results["poseButtonLabels"] = sorted(driver.pose_buttons())

        # Sequence under test: HOME -> LEFT -> LEFT -> RIGHT -> HOME.
        results["sequence"] = ["HOME", "LEFT", "LEFT(repeat)", "RIGHT", "HOME"]
        results["initial"] = assert_transform(wait_server_pose("HOME", 0), "HOME", 0)
        recorded_home = get_state()["r17"]["homeTransformRowMajor"]
        apply_pose(driver, "LEFT", -15, results)
        repeat_active_pose(driver, "LEFT", results)
        apply_pose(driver, "RIGHT", 15, results)
        apply_pose(driver, "HOME", 0, results)

        home_state = get_state()["r17"]
        if home_state["homeTransformRowMajor"] != recorded_home:
            raise AssertionError({"recordedHome": recorded_home, "publishedHome": home_state["homeTransformRowMajor"]})
        if home_state["currentTransformRowMajor"] != recorded_home:
            raise AssertionError({"recordedHome": recorded_home, "current": home_state["currentTransformRowMajor"]})
        results["homeRestoresCompleteTransform"] = {
            "recordedHomeRowMajor": recorded_home,
            "currentRowMajor": home_state["currentTransformRowMajor"],
            "allSixteenElementsEqual": True,
            "homeUnchangedByTheWholeSequence": True,
        }

        stream = get_state()
        results["streamHealth"] = {
            "ready": stream["ready"],
            "frameIndex": stream["frame_index"],
            "rendererOwnerCount": stream["renderer_owner_count"],
            "lastError": stream["last_error"],
        }
        if not stream["ready"] or stream["renderer_owner_count"] != 1 or stream["last_error"]:
            raise AssertionError(results["streamHealth"])

        screenshot = ARTIFACT_DIR / "cube-link-browser.png"
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

    out = ARTIFACT_DIR / "cube-link-browser.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
