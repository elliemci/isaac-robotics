#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from selenium import webdriver
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

URL = os.environ.get("URL", "http://127.0.0.1:5174/?server=10.110.50.187&signalingport=49101")
STATE_URL = os.environ.get("STATE_URL", "http://127.0.0.1:8082/state.json")
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "/snap/firefox/8595/usr/lib/firefox/firefox")
GECKODRIVER = os.environ.get("GECKODRIVER", "/snap/firefox/8595/usr/lib/firefox/geckodriver")
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", "/home/nvidia/Desktop/Session_1/Attic_Portal/artifacts"))


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def drag(driver: webdriver.Firefox, element) -> None:
    rect = element.rect
    start_x = int(rect["x"] + rect["width"] * 0.45)
    start_y = int(rect["y"] + rect["height"] * 0.52)
    mouse = PointerInput("mouse", "mouse")
    actions = ActionBuilder(driver, mouse=mouse)
    actions.pointer_action.move_to_location(start_x, start_y)
    actions.pointer_action.pointer_down(button=0)
    actions.pointer_action.pause(0.2)
    actions.pointer_action.move_to_location(start_x + 180, start_y + 100)
    actions.pointer_action.pause(0.2)
    actions.pointer_action.pointer_up(button=0)
    actions.perform()


def rms_difference(a: Path, b: Path) -> float:
    with Image.open(a) as img_a, Image.open(b) as img_b:
        diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB"))
        stat = ImageStat.Stat(diff)
        return float(sum(value * value for value in stat.rms) ** 0.5)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.binary_location = FIREFOX_BIN
    options.add_argument("-headless")
    options.set_preference("media.autoplay.default", 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 45)
        video = wait.until(lambda d: d.find_element(By.ID, "remote-video"))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        time.sleep(1.0)
        before_state = get_state()
        before_time = driver.execute_script("return document.getElementById('remote-video').currentTime")
        before_png = ARTIFACT_DIR / "live-video-before.png"
        video.screenshot(str(before_png))
        drag(driver, video)
        time.sleep(1.5)
        after_state = get_state()
        after_time = driver.execute_script("return document.getElementById('remote-video').currentTime")
        after_png = ARTIFACT_DIR / "live-video-after.png"
        video.screenshot(str(after_png))
        result = {
            "url": URL,
            "beforeFrameIndex": before_state.get("frame_index"),
            "afterFrameIndex": after_state.get("frame_index"),
            "beforeCamera": before_state.get("camera_state"),
            "afterCamera": after_state.get("camera_state"),
            "beforeVideoTime": before_time,
            "afterVideoTime": after_time,
            "screenshotRmsDifference": rms_difference(before_png, after_png),
            "beforeScreenshot": str(before_png),
            "afterScreenshot": str(after_png),
        }
        out = ARTIFACT_DIR / "live-video-pixels-check.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
