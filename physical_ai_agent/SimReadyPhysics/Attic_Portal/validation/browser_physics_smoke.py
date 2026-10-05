#!/usr/bin/env python3
"""Browser smoke for the R-17 Physics Probe ("Run Physics Simluation").

Clicks the panel's PLAY button in a real Firefox session and asserts that
ovphysx loaded the stage and stepped it, found no rigid bodies, and left the
rendered scene, the cube transform, the camera, and the stage file untouched.

Expects a freshly started server (physics status NOT_RUN).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

APP_ROOT = Path(__file__).resolve().parents[1]
SECTION_TITLE = "Run Physics Simluation"
PLAY_LABEL = "▶ PLAY"


def _public_ip() -> str:
    """WebRTC ICE must advertise a routable address, not loopback."""

    configured = os.environ.get("ATTIC_PORTAL_PUBLIC_IP")
    if configured:
        return configured
    try:
        return subprocess.check_output(["hostname", "-I"], text=True).split()[0]
    except Exception:
        return "127.0.0.1"


CLIENT_PORT = os.environ.get("ATTIC_PORTAL_CLIENT_PORT", "5176")
SIGNALING_PORT = os.environ.get("ATTIC_PORTAL_SIGNALING_PORT", "49101")
URL = os.environ.get("URL", f"http://127.0.0.1:{CLIENT_PORT}/?server={_public_ip()}&signalingport={SIGNALING_PORT}")
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8082/state.json")
# Leave FIREFOX_BIN empty so the snap geckodriver resolves its own Firefox.
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "")
GECKODRIVER = os.environ.get("GECKODRIVER", "/snap/bin/geckodriver")
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", str(APP_ROOT / "artifacts")))
EXPECTED_STAGE = os.environ.get("ATTIC_PORTAL_MISSION_STAGE", "")
# Allowed mean-abs pixel change from Play, beyond the noise floor measured
# between two frames taken before Play.
PIXEL_MARGIN = float(os.environ.get("PHYSICS_PIXEL_MARGIN", "1.5"))

VIDEO_FRAME_JS = """
const v = document.getElementById('remote-video');
const c = document.createElement('canvas');
c.width = v.videoWidth; c.height = v.videoHeight;
c.getContext('2d').drawImage(v, 0, 0);
return c.toDataURL('image/png');
"""


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def video_frame(driver: webdriver.Firefox) -> Image.Image:
    """Raw decoded stream frame, so the DOM panel overlay never enters the diff."""

    data_url = driver.execute_script(VIDEO_FRAME_JS)
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")


def mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    return float(sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3.0)


def click_button(driver: webdriver.Firefox, label: str) -> None:
    for button in driver.find_elements(By.CSS_SELECTOR, ".r17-signal-panel button"):
        if button.text.strip() == label:
            driver.execute_script("arguments[0].click();", button)
            return
    raise AssertionError(f"button not found: {label}")


def wait_physics(predicate, description: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = get_state()
        if predicate(last.get("physics") or {}):
            return last
        time.sleep(0.1)
    raise AssertionError({"timedOutWaitingFor": description, "lastPhysics": last.get("physics")})


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    if FIREFOX_BIN:
        options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    try:
        # Tall enough that the whole panel, including the new section, is visible.
        driver.set_window_size(1280, 1300)
        driver.get(URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: d.find_element(By.ID, "remote-video"))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        wait.until(lambda d: "/Root/Workshop/Cube" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)

        panel_text = driver.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text
        if SECTION_TITLE not in panel_text:
            raise AssertionError({"missingSectionTitle": SECTION_TITLE, "panelText": panel_text})
        play_buttons = [b for b in driver.find_elements(By.CSS_SELECTOR, ".r17-signal-panel button") if b.text.strip() == PLAY_LABEL]
        if len(play_buttons) != 1:
            raise AssertionError({"expectedOnePlayButton": len(play_buttons)})
        wait.until(lambda d: not play_buttons[0].get_attribute("disabled"))

        stage_path = get_state().get("stage") or ""
        if EXPECTED_STAGE and Path(stage_path).resolve() != Path(EXPECTED_STAGE).resolve():
            raise AssertionError({"stageMismatch": stage_path, "expected": EXPECTED_STAGE})
        hash_before = sha256(stage_path)

        # Noise floor: two settled frames before Play.
        time.sleep(2.0)
        frame_a = video_frame(driver)
        time.sleep(0.8)
        frame_b = video_frame(driver)
        noise = mean_abs_diff(frame_a, frame_b)

        before = get_state()
        if (before.get("physics") or {}).get("status") != "NOT_RUN":
            raise AssertionError({"physicsAlreadyRan": before.get("physics")})

        click_button(driver, PLAY_LABEL)
        after = wait_physics(lambda p: p.get("status") not in (None, "NOT_RUN", "RUNNING"), "physics result")
        # Let the panel apply the r17-state-v1 broadcast and the renderer keep
        # streaming frames after the probe returned control to the render loop.
        wait.until(lambda d: "NOT_SIMULATION_READY" in d.find_element(By.CSS_SELECTOR, ".r17-physics-link").text)
        time.sleep(1.5)
        frame_c = video_frame(driver)
        moved = mean_abs_diff(frame_b, frame_c)
        final = get_state()

        driver.execute_script("document.querySelector('.r17-physics-link').scrollIntoView({block: 'center'});")
        time.sleep(0.4)
        screenshot = ARTIFACT_DIR / "r17-physics-probe.png"
        driver.save_screenshot(str(screenshot))
        section_text = driver.find_element(By.CSS_SELECTOR, ".r17-physics-link").text

        # A second Play must load, step, and release a fresh ovphysx runtime
        # without stalling the renderer or reopening the stage.
        wait.until(lambda d: not play_buttons[0].get_attribute("disabled"))
        click_button(driver, PLAY_LABEL)
        second = wait_physics(lambda p: int(p.get("playCount") or 0) >= 2 and p.get("status") not in ("RUNNING",), "second physics result")
        time.sleep(1.0)
        second_final = get_state()

        physics = final.get("physics") or {}
        r17_physics = (final.get("r17") or {}).get("physics") or {}
        hash_after = sha256(stage_path)

        failures = []
        if physics.get("runtimeInstalled") is not True:
            failures.append(("runtimeInstalled", physics.get("runtimeInstalled")))
        if not int(physics.get("stepCount") or 0) >= 1:
            failures.append(("stepCount", physics.get("stepCount")))
        if not float(physics.get("elapsedTime") or 0.0) > 0.0:
            failures.append(("elapsedTime", physics.get("elapsedTime")))
        if physics.get("rigidBodyCount") != 0:
            failures.append(("rigidBodyCount", physics.get("rigidBodyCount")))
        if physics.get("status") != "NOT_SIMULATION_READY":
            failures.append(("status", physics.get("status")))
        if physics.get("bridgeReady") is not False:
            failures.append(("bridgeReady", physics.get("bridgeReady")))
        if final.get("renderer_owner_count") != 1:
            failures.append(("renderer_owner_count", final.get("renderer_owner_count")))
        if final.get("stage_open_count") != before.get("stage_open_count"):
            failures.append(("stageReopened", [before.get("stage_open_count"), final.get("stage_open_count")]))
        if Path(str(final.get("stage"))).name != "OldAttic_Mission_2.usda":
            failures.append(("stage", final.get("stage")))
        if physics.get("stagePath") != final.get("stage"):
            failures.append(("physics.stagePath", physics.get("stagePath")))
        if r17_physics.get("status") != physics.get("status"):
            failures.append(("r17.physics.status", r17_physics.get("status")))
        if hash_before != hash_after:
            failures.append(("missionStageHashChanged", [hash_before, hash_after]))
        if (before.get("r17") or {}).get("currentTransformRowMajor") != (final.get("r17") or {}).get("currentTransformRowMajor"):
            failures.append(("cubeTransformChanged", None))
        if before.get("camera_state") != final.get("camera_state"):
            failures.append(("cameraChanged", [before.get("camera_state"), final.get("camera_state")]))
        if not int(final.get("frame_index") or 0) > int(before.get("frame_index") or 0):
            failures.append(("rendererStalled", [before.get("frame_index"), final.get("frame_index")]))
        if moved > noise + PIXEL_MARGIN:
            failures.append(("renderedSceneMoved", {"noiseFloor": noise, "afterPlay": moved, "margin": PIXEL_MARGIN}))
        for needle in ("NOT_SIMULATION_READY", "rigid bodies 0", "steps 1", "bridge NOT READY"):
            if needle not in section_text:
                failures.append(("panelMissingText", needle))
        second_physics = second_final.get("physics") or {}
        if second_physics.get("playCount") != 2:
            failures.append(("secondPlayCount", second_physics.get("playCount")))
        if second_physics.get("status") != "NOT_SIMULATION_READY" or second_physics.get("stepCount") != 1 or second_physics.get("rigidBodyCount") != 0:
            failures.append(("secondPlayResult", second_physics))
        if second_final.get("renderer_owner_count") != 1 or second_final.get("stage_open_count") != final.get("stage_open_count"):
            failures.append(("secondPlayRendererState", [second_final.get("renderer_owner_count"), second_final.get("stage_open_count")]))
        if not int(second_final.get("frame_index") or 0) > int(second.get("frame_index") or 0):
            failures.append(("rendererStalledAfterSecondPlay", [second.get("frame_index"), second_final.get("frame_index")]))
        if sha256(stage_path) != hash_before:
            failures.append(("missionStageHashChangedAfterSecondPlay", None))
        if failures:
            raise AssertionError(failures)

        result = {
            "url": URL,
            "sectionTitle": SECTION_TITLE,
            "playButton": PLAY_LABEL,
            "stage": final.get("stage"),
            "missionStageSha256Before": hash_before,
            "missionStageSha256After": hash_after,
            "physics": {key: physics.get(key) for key in (
                "runtimeInstalled", "runtimeVersion", "status", "stepCount", "elapsedTime", "fixedDt",
                "loadMs", "stepMs", "rigidBodyCount", "bridgeReady", "playCount", "loadedStagePath", "message",
            )},
            "renderer_owner_count": final.get("renderer_owner_count"),
            "stage_open_count": final.get("stage_open_count"),
            "frameIndexBefore": before.get("frame_index"),
            "frameIndexAfter": final.get("frame_index"),
            "pixelNoiseFloor": round(noise, 4),
            "pixelChangeAfterPlay": round(moved, 4),
            "secondPlay": {key: second_physics.get(key) for key in ("playCount", "status", "stepCount", "elapsedTime", "rigidBodyCount", "loadMs", "stepMs")},
            "panelSectionText": section_text,
            "artifact": str(screenshot),
        }
    finally:
        driver.quit()
    out = ARTIFACT_DIR / "r17-physics-probe-smoke.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # Superseded by Mission 4: Play is now continuous simulation and the one-shot
    # probe this asserted no longer exists. The helpers above stay in use by the
    # newer smokes. See validation/browser_mission4_ready.py.
    raise SystemExit("browser_physics_smoke.py is superseded by browser_mission4_ready.py")
