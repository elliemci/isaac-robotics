#!/usr/bin/env python3
"""Browser smoke for the R-17 Memory Cube Link.

Run after the portal is launched. This script assumes the workshop snap Firefox
layout used in Session_1. Override URL/STATE_URL/FIREFOX_BIN/GECKODRIVER if the
environment changes.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

URL = os.environ.get("URL", "http://127.0.0.1:5176/?server=127.0.0.1&signalingport=49101")
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8082/state.json")
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "/snap/firefox/8595/usr/lib/firefox/firefox")
GECKODRIVER = os.environ.get("GECKODRIVER", "/snap/firefox/8595/usr/lib/firefox/geckodriver")
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", "/home/nvidia/Desktop/Session_1/Attic_Portal/artifacts"))


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def wait_server_pose(pose: str, offset: int, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = get_state()
        r17 = last["r17"]
        if r17["status"] == "READY" and r17["requestedPose"] == pose and r17["offsetX"] == offset and not r17["transitionActive"]:
            return last
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {pose}/{offset}: {last}")


def assert_transform(state: dict, pose: str, offset: int) -> dict:
    r17 = state["r17"]
    home = r17["homeTransformRowMajor"]
    current = r17["currentTransformRowMajor"]
    expected_x = home[3][0] + offset
    rotation_scale_ok = all(math.isclose(current[r][c], home[r][c], abs_tol=1e-9) for r in range(3) for c in range(4))
    rotation_scale_ok = rotation_scale_ok and math.isclose(current[3][3], home[3][3], abs_tol=1e-9)
    target_ok = (
        math.isclose(current[3][0], expected_x, abs_tol=1e-9)
        and math.isclose(current[3][1], home[3][1], abs_tol=1e-9)
        and math.isclose(current[3][2], home[3][2], abs_tol=1e-9)
    )
    if not rotation_scale_ok or not target_ok:
        raise AssertionError({"pose": pose, "offset": offset, "home": home, "current": current})
    return {
        "pose": pose,
        "offsetX": offset,
        "cubePath": r17["cubePath"],
        "translate": current[3][0:3],
        "rotationScaleUnchanged": rotation_scale_ok,
        "targetExact": target_ok,
    }


def click_button(driver: webdriver.Firefox, *labels: str) -> None:
    expected = set(labels)
    for button in driver.find_elements(By.CSS_SELECTOR, ".r17-pose-controls button"):
        if button.text.strip() in expected:
            button.click()
            return
    raise AssertionError(f"button not found: {sorted(expected)}")


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    results: dict[str, object] = {}
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 45)
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        wait.until(lambda d: "/Root/Workshop/Cube" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        wait.until(lambda d: all(not b.get_attribute("disabled") for b in d.find_elements(By.CSS_SELECTOR, ".r17-pose-controls button")))

        results["initial"] = assert_transform(wait_server_pose("HOME", 0), "HOME", 0)
        click_button(driver, "LEFT POSE -15", "LEFT POSE \u221215")
        results["left"] = assert_transform(wait_server_pose("LEFT", -15), "LEFT", -15)
        click_button(driver, "RIGHT POSE +15")
        results["right"] = assert_transform(wait_server_pose("RIGHT", 15), "RIGHT", 15)
        click_button(driver, "HOME")
        results["home"] = assert_transform(wait_server_pose("HOME", 0), "HOME", 0)
        driver.save_screenshot(str(ARTIFACT_DIR / "starter-cube-link-smoke.png"))
    finally:
        driver.quit()

    out = ARTIFACT_DIR / "starter-cube-link-smoke.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
