#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.by import By
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

URL = os.environ.get("URL", "http://127.0.0.1:5176/?server=10.110.50.187&signalingport=49101")
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8082/state.json")
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "/snap/firefox/8595/usr/lib/firefox/firefox")
GECKODRIVER = os.environ.get("GECKODRIVER", "/snap/firefox/8595/usr/lib/firefox/geckodriver")
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", "/home/nvidia/Desktop/Session_1/Attic_Portal/artifacts"))


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def camera_signature() -> list:
    camera = get_state()["camera_state"]
    return [
        round(float(camera["azimuth"]), 6),
        round(float(camera["elevation"]), 6),
        round(float(camera["distance"]), 6),
        [round(float(value), 6) for value in camera["target"]],
    ]


def wait_for_change(before: list, predicate, timeout: float = 5.0) -> list:
    deadline = time.time() + timeout
    latest = before
    while time.time() < deadline:
        latest = camera_signature()
        if predicate(before, latest):
            return latest
        time.sleep(0.1)
    return latest


def pointer_drag(driver: webdriver.Firefox, element, button: int, dx: int, dy: int) -> None:
    mouse = PointerInput("mouse", "mouse")
    actions = ActionBuilder(driver, mouse=mouse)
    rect = element.rect
    start_x = int(rect["x"] + rect["width"] * 0.45)
    start_y = int(rect["y"] + rect["height"] * 0.52)
    actions.pointer_action.move_to_location(start_x, start_y)
    actions.pointer_action.pointer_down(button=button)
    actions.pointer_action.pause(0.1)
    actions.pointer_action.move_to_location(start_x + dx, start_y + dy)
    actions.pointer_action.pause(0.1)
    actions.pointer_action.pointer_up(button=button)
    actions.perform()


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    result: dict[str, object] = {"url": URL}
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 45)
        video = wait.until(lambda d: d.find_element(By.ID, "remote-video"))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        panel = wait.until(lambda d: d.find_element(By.CSS_SELECTOR, ".r17-signal-panel"))
        panel_text = panel.text
        if "R-17 SIGNAL PANEL" not in panel_text or "MODULE NOT INSTALLED" not in panel_text:
            raise AssertionError(panel_text)

        video_state = driver.execute_script("const v=document.getElementById('remote-video'); return {w:v.videoWidth,h:v.videoHeight,ready:v.readyState};")
        result["video"] = video_state
        result["panelText"] = panel_text

        before = camera_signature()
        pointer_drag(driver, video, 0, 140, 90)
        after_orbit = wait_for_change(before, lambda a, b: a[:2] != b[:2])

        before_pan = after_orbit
        pointer_drag(driver, video, 1, 95, -55)
        after_pan = wait_for_change(before_pan, lambda a, b: a[3] != b[3])

        before_zoom = after_pan
        origin = ScrollOrigin.from_element(video)
        webdriver.ActionChains(driver).scroll_from_origin(origin, 0, -420).perform()
        after_zoom = wait_for_change(before_zoom, lambda a, b: a[2] != b[2])

        panel_before = after_zoom
        pointer_drag(driver, panel, 0, 80, 30)
        time.sleep(0.5)
        panel_after = camera_signature()

        screenshot = ARTIFACT_DIR / "browser-empty-r17-live.png"
        driver.save_screenshot(str(screenshot))
        result.update(
            {
                "cameraBefore": before,
                "cameraAfterOrbit": after_orbit,
                "cameraAfterPan": after_pan,
                "cameraAfterZoom": after_zoom,
                "panelBefore": panel_before,
                "panelAfter": panel_after,
                "orbitChanged": before[:2] != after_orbit[:2],
                "panChanged": after_orbit[3] != after_pan[3],
                "zoomChanged": after_pan[2] != after_zoom[2],
                "panelGated": panel_before == panel_after,
                "screenshot": str(screenshot),
            }
        )
        if not all(bool(result[key]) for key in ("orbitChanged", "panChanged", "zoomChanged", "panelGated")):
            raise AssertionError(result)
    finally:
        driver.quit()

    out = ARTIFACT_DIR / "browser-empty-r17-live.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
