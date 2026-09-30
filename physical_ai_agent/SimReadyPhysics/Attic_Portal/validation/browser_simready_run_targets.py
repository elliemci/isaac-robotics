#!/usr/bin/env python3
"""Clicks "run targets" in a real Firefox session and prints the simready state.

Usage: browser_simready_run_targets.py <screenshot-name>.png
Expects the app running (see README). Read-only: only the panel button is used.
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import browser_physics_smoke as b
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

shot = sys.argv[1] if len(sys.argv) > 1 else "r17-simready-run.png"
options = Options()
options.add_argument("-headless")
driver = webdriver.Firefox(service=Service(b.GECKODRIVER), options=options)
try:
    driver.set_window_size(1280, 1500)
    driver.get(b.URL)
    wait = WebDriverWait(driver, 60)
    wait.until(lambda d: "SimReady Validate" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
    buttons = [x for x in driver.find_elements(By.CSS_SELECTOR, ".r17-signal-panel button") if x.text.strip() == "run targets"]
    assert len(buttons) == 1
    wait.until(lambda d: not buttons[0].get_attribute("disabled"))
    before = b.get_state()["simready"]["runCount"]
    driver.execute_script("arguments[0].click();", buttons[0])
    deadline = time.time() + 60
    while time.time() < deadline:
        s = b.get_state()["simready"]
        if s["runCount"] > before and s["status"] != "RUNNING":
            break
        time.sleep(0.2)
    time.sleep(1.0)
    driver.execute_script("document.querySelector('.r17-simready-link').scrollIntoView({block: 'center'});")
    driver.save_screenshot(str(b.ARTIFACT_DIR / shot))
    print(json.dumps(b.get_state()["simready"], indent=1))
finally:
    driver.quit()
