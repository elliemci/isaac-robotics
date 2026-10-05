#!/usr/bin/env python3
"""Browser smoke for Mission 3 Part 1: "run fixes" is inert.

Clicks only "run fixes" in a real Firefox session and asserts it reports
NOT_IMPLEMENTED with appliedCount=0 and outlineVisible=false, while running no
target validation, authoring no USD, writing no output, and leaving physics and
the renderer untouched. Expects a freshly started server (simready IDLE).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import browser_physics_smoke as b
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

SESSION_ROOT = b.APP_ROOT.parent
SOURCES = [SESSION_ROOT / "OldAttic_Mission_2.usda", SESSION_ROOT / "C9_ContainmentPod.usda"]
SERVER_LOG = b.APP_ROOT / "logs" / "server.log"
SCREENSHOT = "r17-mission3-part1-inert-fixes.png"


def artifact_snapshot() -> dict[str, tuple[int, int]]:
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in b.ARTIFACT_DIR.iterdir() if p.is_file() and p.name != SCREENSHOT}


def log_text() -> str:
    return SERVER_LOG.read_text(errors="replace") if SERVER_LOG.exists() else ""


def main() -> None:
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(b.GECKODRIVER), options=options)
    try:
        driver.set_window_size(1280, 1500)
        driver.get(b.URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: "SimReady Validate" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        panel = driver.find_element(By.CSS_SELECTOR, ".r17-signal-panel")
        buttons = {x.text.strip(): x for x in panel.find_elements(By.CSS_SELECTOR, "button")}
        failures: list = []
        for label in ("run targets", "run fixes"):
            if label not in buttons:
                failures.append(("missingButton", label))
        if failures:
            raise AssertionError(failures)
        controls = driver.find_element(By.CSS_SELECTOR, ".r17-simready-controls")
        order = [x.text.strip() for x in controls.find_elements(By.CSS_SELECTOR, "button")]
        if order != ["run targets", "run fixes"]:
            failures.append(("notAdjacent", order))
        wait.until(lambda d: not buttons["run fixes"].get_attribute("disabled"))

        before = b.get_state()
        sim0 = before["simready"]
        if sim0["status"] != "IDLE" or sim0["fixes"]["status"] != "IDLE":
            raise AssertionError({"notFresh": sim0})
        hashes0 = [b.sha256(p) for p in SOURCES]
        artifacts0 = artifact_snapshot()
        log0 = log_text()

        driver.execute_script("arguments[0].click();", buttons["run fixes"])
        deadline = time.time() + 30
        while time.time() < deadline and b.get_state()["simready"]["fixes"]["runCount"] < 1:
            time.sleep(0.1)
        wait.until(lambda d: "NOT_IMPLEMENTED" in d.find_element(By.CSS_SELECTOR, ".r17-simready-link").text)
        time.sleep(1.5)
        after = b.get_state()
        sim1 = after["simready"]
        driver.execute_script("document.querySelector('.r17-simready-link').scrollIntoView({block: 'center'});")
        time.sleep(0.4)
        driver.save_screenshot(str(b.ARTIFACT_DIR / SCREENSHOT))
        section = driver.find_element(By.CSS_SELECTOR, ".r17-simready-link").text
        new_log = log_text()[len(log0):]

        fixes = sim1["fixes"]
        if fixes["status"] != "NOT_IMPLEMENTED":
            failures.append(("fixes.status", fixes["status"]))
        if fixes["appliedCount"] != 0:
            failures.append(("appliedCount", fixes["appliedCount"]))
        if fixes["outlineVisible"] is not False:
            failures.append(("outlineVisible", fixes["outlineVisible"]))
        if fixes["runCount"] != 1:
            failures.append(("fixes.runCount", fixes["runCount"]))
        for key in ("status", "runCount", "missingCount", "missing", "targets"):
            if sim1[key] != sim0[key]:
                failures.append((f"simready.{key}Changed", [sim0[key], sim1[key]]))
        if "not implemented" not in section.lower():
            failures.append(("panelText", section))
        if [b.sha256(p) for p in SOURCES] != hashes0:
            failures.append(("sourceHashChanged", hashes0))
        if artifact_snapshot() != artifacts0:
            failures.append(("artifactsChanged", None))
        if after.get("physics") != before.get("physics"):
            failures.append(("physicsChanged", after.get("physics")))
        if after.get("renderer_owner_count") != 1:
            failures.append(("renderer_owner_count", after.get("renderer_owner_count")))
        if after.get("stage_open_count") != before.get("stage_open_count"):
            failures.append(("stageReopened", [before.get("stage_open_count"), after.get("stage_open_count")]))
        for needle in ("simready.validateTargets", "SimReady: request", "physics probe"):
            if needle in new_log:
                failures.append(("unexpectedLog", needle))

        # A second click is acknowledged and still inert.
        wait.until(lambda d: not buttons["run fixes"].get_attribute("disabled"))
        driver.execute_script("arguments[0].click();", buttons["run fixes"])
        deadline = time.time() + 30
        while time.time() < deadline and b.get_state()["simready"]["fixes"]["runCount"] < 2:
            time.sleep(0.1)
        second = b.get_state()["simready"]
        if second["fixes"]["runCount"] != 2 or second["fixes"]["appliedCount"] != 0 or second["status"] != "IDLE":
            failures.append(("secondClick", second["fixes"]))

        result = {
            "fixes": second["fixes"],
            "simreadyStatus": second["status"],
            "targetsExecuted": second["runCount"] > 0,
            "adjacentButtons": order,
            "renderer_owner_count": after.get("renderer_owner_count"),
            "sourceSha256": dict(zip((p.name for p in SOURCES), hashes0)),
            "screenshot": str(b.ARTIFACT_DIR / SCREENSHOT),
            "failures": failures,
        }
        print(json.dumps(result, indent=1))
        if failures:
            raise SystemExit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
