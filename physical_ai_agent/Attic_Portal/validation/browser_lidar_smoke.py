#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

APP_ROOT = Path(__file__).resolve().parents[1]


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
# The snap geckodriver wrapper resolves its own confined Firefox, and rejects
# an explicit binary path pointing at the /usr/bin wrapper. Leave FIREFOX_BIN
# empty to let geckodriver choose; set it for a non-snap Firefox install.
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "")
GECKODRIVER = os.environ.get("GECKODRIVER", "/snap/bin/geckodriver")
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", str(APP_ROOT / "artifacts")))
LIDAR_LAYER = Path(os.environ.get("LIDAR_LAYER", str(APP_ROOT / "usd" / "R17_Lidar.usda")))
CUBE_MATERIAL_NAME = "MemoryCubeMaterial"
CUBE_NONVISUAL_ATTRIBUTES = (
    "omni:simready:nonvisual:base",
    "omni:simready:nonvisual:coating",
    "omni:simready:nonvisual:attributes",
    "inputs:nonvisual:base",
    "inputs:nonvisual:coating",
    "inputs:nonvisual:attributes",
)


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def click_button(driver: webdriver.Firefox, label: str) -> None:
    for button in driver.find_elements(By.CSS_SELECTOR, ".r17-signal-panel button"):
        if button.text.strip() == label:
            driver.execute_script("arguments[0].click();", button)
            return
    raise AssertionError(f"button not found: {label}")


def wait_lidar_status(status: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = get_state()
        lidar = last.get("lidar") or {}
        r17 = last.get("r17") or {}
        if lidar.get("status") == status or r17.get("lidarStatus") == status:
            return last
        time.sleep(0.1)
    raise AssertionError({"wantedLidarStatus": status, "last": last})


def assert_lidar_layer() -> None:
    text = LIDAR_LAYER.read_text(encoding="utf-8")
    for needle in ("OmniLidar", "R17Lidar", "R17LidarProduct", "PointCloud", "Coordinates", "Intensity", "ObjectId", "Flags", "Counts", "omni:simready:nonvisual:base", "inputs:nonvisual:base"):
        if needle not in text:
            raise AssertionError({"missingLidarLayerText": needle})
    if re.search(r"omni:sensor:Core:instantLidar\s*=\s*(?:1|true)", text) is None:
        raise AssertionError("instantLidar is not enabled")
    if re.search(r"omni:sensor:Core:partialOutputs\s*=\s*(?:0|false)", text) is None:
        raise AssertionError("partialOutputs is not disabled")
    if re.search(r'omni:sensor:Core:outputFrameOfReference\s*=\s*"SENSOR"', text) is None:
        raise AssertionError("LiDAR output frame is not SENSOR")
    if re.search(r"omni:sensor:Core:includeInvalidPoints\s*=\s*(?:0|false)", text) is None:
        raise AssertionError("invalid LiDAR points are not disabled")
    if re.search(r'omni:sensor:Core:outputMotionCompensationState\s*=\s*"NONCOMPENSATED"', text) is None:
        raise AssertionError("unexpected LiDAR motion compensation state")
    if text.count("omni:simready:nonvisual:base") < 1:
        raise AssertionError("no viewer-owned nonvisual material defaults were authored")
    cube_material = re.search(rf'over "{CUBE_MATERIAL_NAME}"\s*\{{(?P<body>[^{{}}]*)\}}', text, re.DOTALL)
    if cube_material is None:
        raise AssertionError({"missingCubeMaterialOverride": CUBE_MATERIAL_NAME})
    missing = [name for name in CUBE_NONVISUAL_ATTRIBUTES if name not in cube_material.group("body")]
    if missing:
        raise AssertionError({"cubeMaterialMissingNonvisualAttributes": missing})


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert_lidar_layer()
    options = Options()
    if FIREFOX_BIN:
        options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    result: dict[str, object] = {}
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: d.find_element(By.ID, "remote-video"))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        wait.until(lambda d: "/Root/Workshop/Cube" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        wait.until(lambda d: all(not b.get_attribute("disabled") for b in d.find_elements(By.CSS_SELECTOR, ".r17-lidar-controls button")))

        before = get_state()
        click_button(driver, "LIDAR ON")
        enabled = wait_lidar_status("READY")
        # lidar.status turns READY on the frame the first validated scan lands;
        # the panel re-enables one r17-state-v1 broadcast later. Wait for that
        # so the camera-follow click cannot land on a still-disabled button.
        wait.until(lambda d: all(not b.get_attribute("disabled") for b in d.find_elements(By.CSS_SELECTOR, ".r17-view-controls button")))
        click_button(driver, "CUBE FOCUS")
        focused = wait.until(
            lambda d: (
                (state := get_state()).get("r17", {}).get("activeView") == "CUBE_FOCUS"
                and state.get("lidar", {}).get("status") == "READY"
                and int(state.get("lidar", {}).get("validPointCount") or 0) > 0
                and state
            )
        )
        time.sleep(0.7)
        screenshot = ARTIFACT_DIR / "r17-lidar-preview.png"
        driver.save_screenshot(str(screenshot))
        click_button(driver, "LIDAR OFF")
        disabled = wait_lidar_status("DISABLED")

        lidar = enabled.get("lidar") or {}
        r17 = enabled.get("r17") or {}
        valid_count = lidar.get("validPointCount") if lidar.get("validPointCount") is not None else r17.get("validPointCount")
        nearest = lidar.get("nearestRange") if lidar.get("nearestRange") is not None else r17.get("nearestRange")
        output_keys = lidar.get("outputKeys") or r17.get("outputKeys") or []
        if int(valid_count or 0) <= 0:
            raise AssertionError({"validPointCount": valid_count})
        if nearest is None or float(nearest) <= 0:
            raise AssertionError({"nearestRange": nearest})
        if int(lidar.get("nonvisualMaterialCount") or r17.get("lidarNonvisualMaterialCount") or 0) <= 0:
            raise AssertionError({"nonvisualMaterialCount": lidar.get("nonvisualMaterialCount")})
        if "PointCloud" not in output_keys:
            raise AssertionError({"missingPointCloudOutput": output_keys})
        if enabled.get("renderer_owner_count") != 1 or disabled.get("renderer_owner_count") != 1:
            raise AssertionError({"rendererOwnerCount": [enabled.get("renderer_owner_count"), disabled.get("renderer_owner_count")]})
        disabled_lidar = disabled.get("lidar") or {}
        if disabled_lidar.get("validPointCount") is not None or disabled_lidar.get("nearestRange") is not None:
            raise AssertionError({"disabledTelemetryNotCleared": disabled_lidar})

        result = {
            "layer": str(LIDAR_LAYER),
            "enabled": {
                "status": lidar.get("status") or r17.get("lidarStatus"),
                "sensorPath": lidar.get("sensorPath") or r17.get("lidarSensorPath"),
                "renderProduct": lidar.get("renderProduct") or r17.get("lidarRenderProduct"),
                "pointCloudOutput": lidar.get("pointCloudOutput"),
                "requestedChannels": lidar.get("requestedChannels") or r17.get("lidarRequestedChannels"),
                "nonvisualMaterialCount": lidar.get("nonvisualMaterialCount") or r17.get("lidarNonvisualMaterialCount"),
                "outputKeys": output_keys,
                "validPointCount": valid_count,
                "nearestRange": nearest,
            },
            "focused": {
                "activeView": focused.get("r17", {}).get("activeView"),
                "status": focused.get("lidar", {}).get("status"),
                "validPointCount": focused.get("lidar", {}).get("validPointCount"),
                "nearestRange": focused.get("lidar", {}).get("nearestRange"),
            },
            "disabled": {
                "status": disabled_lidar.get("status"),
                "validPointCount": disabled_lidar.get("validPointCount"),
                "nearestRange": disabled_lidar.get("nearestRange"),
            },
            "rendererOwnerCountBefore": before.get("renderer_owner_count"),
            "rendererOwnerCountAfter": disabled.get("renderer_owner_count"),
            "artifact": str(screenshot),
        }
    finally:
        driver.quit()
    out = ARTIFACT_DIR / "focused-lidar-runtime.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
