#!/usr/bin/env python3
"""Browser smoke for Mission 4 readiness. It clicks nothing.

Confirms the physics-ready panel and state without pressing Play or sending
physics.play: no ovphysx instance, binding, step, or drop test exists. Expects
a freshly started server with no other browser attached to the stream. Set
SMOKE_LOG_START to the first server.log line written by this run.
"""
from __future__ import annotations

import json
import os
import subprocess
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
SOURCES = [SESSION_ROOT / n for n in ("OldAttic_Mission_3_Fixed.usda", "OldAttic_Mission_2.usda", "C9_ContainmentPod.usda", "C9_ContainmentPod_Mission_3_Fixed.usda")]
STAGE = SESSION_ROOT / "OldAttic_Mission_4_Physics.usda"
SERVER_LOG = b.APP_ROOT / "logs" / "server.log"
SCREENSHOT = "r17-mission4-physics-ready.png"
REPORT = "mission4-physics-ready.json"
BACKUP_PATTERNS = ("*.bak", "*~", "*.orig", "*backup*", "*.backup")


def backups() -> set[str]:
    found: set[str] = set()
    for pattern in BACKUP_PATTERNS:
        found |= {str(p) for p in SESSION_ROOT.glob(f"**/{pattern}") if "node_modules" not in p.parts and ".tools" not in p.parts and "vendor" not in p.parts}
    return found


def new_log() -> str:
    start = int(os.environ.get("SMOKE_LOG_START", "1"))
    lines = SERVER_LOG.read_text(errors="replace").splitlines() if SERVER_LOG.exists() else []
    return "\n".join(lines[start - 1:])


def main() -> None:
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(b.GECKODRIVER), options=options)
    failures: list = []
    try:
        driver.set_window_size(1280, 1900)
        driver.get(b.URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: "Run Physics Simluation" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        wait.until(lambda d: "PhysicsScene ENABLED" in d.find_element(By.CSS_SELECTOR, ".r17-physics-link").text)
        hashes0 = {p.name: b.sha256(p) for p in SOURCES if p.exists()}
        backups0 = backups()
        before = b.get_state()

        time.sleep(1.5)
        section = driver.find_element(By.CSS_SELECTOR, ".r17-physics-link").text
        for needle in ("PhysicsScene ENABLED", "RigidBodyAPI", "CollisionAPI", "PhysicsScene (blue)", "outlines VISIBLE", "READY_TO_RUN"):
            if needle not in section:
                failures.append(("panelMissing", needle))
        play = [x for x in driver.find_elements(By.CSS_SELECTOR, ".r17-signal-panel button") if "PLAY" in x.text]
        if len(play) != 1:
            failures.append(("playButtons", len(play)))
        play_enabled = bool(play) and play[0].get_attribute("disabled") is None
        if not play_enabled:
            failures.append(("playDisabled", None))

        driver.execute_script("document.querySelector('.r17-physics-link').scrollIntoView({block: 'start'});")
        time.sleep(0.5)
        driver.save_screenshot(str(b.ARTIFACT_DIR / SCREENSHOT))
        # Viewport-only shot: the streamed frame shows the outlines without panel chrome.
        driver.execute_script("window.scrollTo(0,0);")

        state = b.get_state()
        physics = state["physics"]
        expect = {
            "status": "READY_TO_RUN", "playing": False, "stepCount": 0, "elapsedTime": 0.0, "sceneEnabled": True,
            "sceneCount": 1, "rigidBodyCount": 2, "colliderCount": 11, "visualizationVisible": True, "bridgeReady": False, "playCount": 0,
        }
        for key, value in expect.items():
            if physics.get(key) != value:
                failures.append((f"physics.{key}", physics.get(key)))
        contract = physics.get("contract", {})
        for key, value in {"rootType": "Xform", "upAxis": "Z", "metersPerUnit": 0.01, "sceneCount": 1, "rigidBodyCount": 2, "colliderCount": 11,
                           "cubeDynamic": True, "podKinematic": True, "podOpenTop": True, "groundStatic": True}.items():
            if contract.get(key) != value:
                failures.append((f"contract.{key}", contract.get(key)))
        if not (contract.get("podMinimumOpeningRadius") or 0) >= 32:
            failures.append(("podMinimumOpeningRadius", contract.get("podMinimumOpeningRadius")))
        if Path(str(state.get("stage"))).resolve() != STAGE.resolve():
            failures.append(("activeStage", state.get("stage")))
        if state.get("renderer_owner_count") != 1:
            failures.append(("renderer_owner_count", state.get("renderer_owner_count")))
        if state.get("stage_open_count") != before.get("stage_open_count"):
            failures.append(("stageReopened", None))
        if {p.name: b.sha256(p) for p in SOURCES if p.exists()} != hashes0:
            failures.append(("sourceHashesChanged", None))
        if backups() != backups0:
            failures.append(("backupFilesCreated", sorted(backups() - backups0)))
        log = new_log()
        for needle in ("physics.play", "physics started", "PhysicsSession", "ovphysx"):
            if needle in log:
                failures.append(("unexpectedLog", needle))

        result = {
            "dropTestExecuted": False,
            "playClicked": False,
            "physicsPlayCommandSent": "physics.play" in log,
            "physics": {k: physics.get(k) for k in expect},
            "contract": contract,
            "playEnabled": play_enabled,
            "activeStage": state.get("stage"),
            "renderer_owner_count": state.get("renderer_owner_count"),
            "sourceSha256": hashes0,
            "screenshot": str(b.ARTIFACT_DIR / SCREENSHOT),
            "failures": failures,
        }
        (b.ARTIFACT_DIR / REPORT).write_text(json.dumps(result, indent=1))
        print(json.dumps(result, indent=1))
        if failures:
            raise SystemExit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
