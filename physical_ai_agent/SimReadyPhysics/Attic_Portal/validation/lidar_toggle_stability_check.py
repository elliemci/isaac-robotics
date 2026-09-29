#!/usr/bin/env python3
"""Prove repeated LIDAR ON/OFF toggles reuse one renderer and one stream.

browser_lidar_smoke.py owns the LiDAR Link contract for a single ON/OFF cycle.
This adds the repeated-toggle evidence: two full cycles from the real panel,
asserting the renderer owner count never leaves 1, the server process is never
respawned, and no additional WebRTC connection is negotiated.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from browser_lidar_smoke import (
    ARTIFACT_DIR,
    FIREFOX_BIN,
    GECKODRIVER,
    STATE_URL,
    URL,
    click_button,
    get_state,
    wait_lidar_status,
)

APP_ROOT = Path(__file__).resolve().parents[1]
SERVER_LOG = Path(os.environ.get("SERVER_LOG", str(APP_ROOT / "logs" / "server.log")))
SERVER_PID_FILE = Path(os.environ.get("SERVER_PID_FILE", str(APP_ROOT / "logs" / "server.pid")))
CYCLES = int(os.environ.get("LIDAR_TOGGLE_CYCLES", "2"))


def webrtc_connect_count() -> int:
    if not SERVER_LOG.exists():
        return 0
    return SERVER_LOG.read_text(encoding="utf-8", errors="replace").count("WebRTC connected=True")


def server_start_marker() -> str:
    """Identify the server process; a respawn changes pid or start time."""

    pid = SERVER_PID_FILE.read_text(encoding="utf-8").strip()
    started = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[21]
    return f"{pid}:{started}"


def enabled_buttons(driver: webdriver.Firefox, selector: str) -> bool:
    buttons = driver.find_elements(By.CSS_SELECTOR, selector)
    return bool(buttons) and all(not b.get_attribute("disabled") for b in buttons)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    if FIREFOX_BIN:
        options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    result: dict[str, object] = {"stateUrl": STATE_URL, "cycles": []}
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: d.find_element(By.ID, "remote-video"))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0;"))
        wait.until(lambda d: "/Root/Workshop/Cube" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        wait.until(lambda d: enabled_buttons(d, ".r17-lidar-controls button"))

        # Baseline after the viewer is streaming, so the browser's own
        # connection is already counted and only a respawn can move these.
        baseline_connections = webrtc_connect_count()
        baseline_server = server_start_marker()
        baseline_state = get_state()
        owner_counts: list[int] = [baseline_state.get("renderer_owner_count")]
        baseline_stage_opens = baseline_state.get("stage_open_count")
        baseline_stream_starts = baseline_state.get("stream_start_count")

        for cycle in range(1, CYCLES + 1):
            wait.until(lambda d: enabled_buttons(d, ".r17-lidar-controls button"))
            click_button(driver, "LIDAR ON")
            on_state = wait_lidar_status("READY", timeout=60.0)
            on_lidar = on_state.get("lidar") or {}
            owner_counts.append(on_state.get("renderer_owner_count"))
            valid = on_lidar.get("validPointCount")
            nearest = on_lidar.get("nearestRange")
            if not isinstance(valid, int) or valid <= 0:
                raise AssertionError({"cycle": cycle, "validPointCount": valid})
            if nearest is None or not (float(nearest) > 0):
                raise AssertionError({"cycle": cycle, "nearestRange": nearest})

            time.sleep(0.5)
            wait.until(lambda d: enabled_buttons(d, ".r17-lidar-controls button"))
            click_button(driver, "LIDAR OFF")
            off_state = wait_lidar_status("DISABLED", timeout=60.0)
            off_lidar = off_state.get("lidar") or {}
            owner_counts.append(off_state.get("renderer_owner_count"))
            if off_lidar.get("validPointCount") is not None or off_lidar.get("nearestRange") is not None:
                raise AssertionError({"cycle": cycle, "staleTelemetry": off_lidar})

            result["cycles"].append({
                "cycle": cycle,
                "on": {
                    "status": on_lidar.get("status"),
                    "validPointCount": valid,
                    "nearestRange": nearest,
                    "nonvisualMaterialCount": on_lidar.get("nonvisualMaterialCount"),
                    "outputKeys": on_lidar.get("outputKeys"),
                },
                "off": {
                    "status": off_lidar.get("status"),
                    "validPointCount": off_lidar.get("validPointCount"),
                    "nearestRange": off_lidar.get("nearestRange"),
                },
            })

        final_connections = webrtc_connect_count()
        final_server = server_start_marker()
        final_state = get_state()
        # Toggles gate the LiDAR RenderProduct in the step set only; they must
        # never reopen the composite stage or restart the ovstream server.
        if final_state.get("stage_open_count") != baseline_stage_opens or baseline_stage_opens != 1:
            raise AssertionError({"stageOpenCount": [baseline_stage_opens, final_state.get("stage_open_count")]})
        if final_state.get("stream_start_count") != baseline_stream_starts or baseline_stream_starts != 1:
            raise AssertionError({"streamStartCount": [baseline_stream_starts, final_state.get("stream_start_count")]})
        if set(owner_counts) != {1}:
            raise AssertionError({"rendererOwnerCounts": owner_counts})
        if final_server != baseline_server:
            raise AssertionError({"serverRespawned": [baseline_server, final_server]})
        if final_connections != baseline_connections:
            raise AssertionError({"webrtcConnectionsChanged": [baseline_connections, final_connections]})

        result.update({
            "rendererOwnerCounts": owner_counts,
            "serverProcess": final_server,
            "webrtcConnections": final_connections,
            "stageOpenCount": final_state.get("stage_open_count"),
            "streamStartCount": final_state.get("stream_start_count"),
            "pass": True,
        })
    finally:
        driver.quit()
    out = ARTIFACT_DIR / "lidar-toggle-stability.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
