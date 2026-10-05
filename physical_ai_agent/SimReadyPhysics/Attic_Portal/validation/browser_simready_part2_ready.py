#!/usr/bin/env python3
"""Browser smoke for Mission 3 Part 2 readiness. It never runs the fix.

Clicks only "run targets" in a real Firefox session, then confirms the report
contains RB.MB.001 and "run fixes" became enabled. It does not click "run
fixes" and never sends simready.fixTargets. Expects a freshly started server
with no other browser attached to the stream.
"""
from __future__ import annotations

import json
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
FORBIDDEN_FILES = [SESSION_ROOT / "OldAttic_Mission_3_Fixed.usda", SESSION_ROOT / "C9_ContainmentPod_Mission_3_Fixed.usda", b.APP_ROOT / "artifacts" / "R17_PhysicsOutlines.usda"]
SERVER_LOG = b.APP_ROOT / "logs" / "server.log"
SCREENSHOT = "r17-mission3-part2-ready.png"


def log_text() -> str:
    return SERVER_LOG.read_text(errors="replace") if SERVER_LOG.exists() else ""


def main() -> None:
    options = Options()
    options.add_argument("-headless")
    driver = webdriver.Firefox(service=Service(b.GECKODRIVER), options=options)
    failures: list = []
    try:
        driver.set_window_size(1280, 1700)
        driver.get(b.URL)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: "SimReady Validate" in d.find_element(By.CSS_SELECTOR, ".r17-signal-panel").text)
        panel = driver.find_element(By.CSS_SELECTOR, ".r17-signal-panel")
        buttons = {x.text.strip(): x for x in panel.find_elements(By.CSS_SELECTOR, "button")}
        for label in ("run targets", "run fixes"):
            if label not in buttons:
                failures.append(("missingButton", label))
        if failures:
            raise AssertionError(failures)
        order = [x.text.strip() for x in driver.find_element(By.CSS_SELECTOR, ".r17-simready-controls").find_elements(By.CSS_SELECTOR, "button")]
        if order != ["run targets", "run fixes"]:
            failures.append(("notAdjacent", order))
        wait.until(lambda d: not buttons["run targets"].get_attribute("disabled"))

        before = b.get_state()
        sim0 = before["simready"]
        if sim0["status"] != "IDLE" or sim0["report"] is not None:
            raise AssertionError({"notFresh": sim0["status"]})
        disabled_before = buttons["run fixes"].get_attribute("disabled") is not None
        if not disabled_before:
            failures.append(("runFixesEnabledBeforeReport", None))
        reason_before = "Run targets first" in driver.find_element(By.CSS_SELECTOR, ".r17-simready-link").text
        if not reason_before:
            failures.append(("noDisabledReasonBeforeReport", None))
        hashes0 = [b.sha256(p) for p in SOURCES]
        log0 = log_text()

        # The only click: run targets.
        driver.execute_script("arguments[0].click();", buttons["run targets"])
        deadline = time.time() + 60
        while time.time() < deadline:
            s = b.get_state()["simready"]
            if s["runCount"] >= 1 and s["status"] != "RUNNING":
                break
            time.sleep(0.2)
        wait.until(lambda d: "RB.MB.001" in d.find_element(By.CSS_SELECTOR, ".r17-simready-link").text)
        wait.until(lambda d: not buttons["run fixes"].get_attribute("disabled"))
        time.sleep(1.0)
        after = b.get_state()
        sim1 = after["simready"]
        driver.execute_script("document.querySelector('.r17-simready-link').scrollIntoView({block: 'center'});")
        time.sleep(0.4)
        driver.save_screenshot(str(b.ARTIFACT_DIR / SCREENSHOT))
        enabled_after = buttons["run fixes"].get_attribute("disabled") is None
        new_log = log_text()[len(log0):]

        report = sim1["report"] or {}
        if "RB.MB.001" not in report.get("ruleIds", []) or not report.get("repairable"):
            failures.append(("reportNotRepairable", report.get("ruleIds")))
        if not any(m.get("ruleId") == "RB.MB.001" for m in sim1["missing"]):
            failures.append(("noRB.MB.001Finding", None))
        if not enabled_after:
            failures.append(("runFixesStillDisabled", None))
        fixes = sim1["fixes"]
        if fixes["status"] != "IDLE" or fixes["appliedCount"] != 0 or fixes["outlineVisible"] is not False or fixes["outputs"]:
            failures.append(("fixesNotIdle", fixes))
        if Path(str(after.get("stage"))).resolve() != SOURCES[0].resolve():
            failures.append(("activeStage", after.get("stage")))
        if Path(sim1["stagePath"]).resolve() != SOURCES[0].resolve() or Path(sim1["podPath"]).resolve() != SOURCES[1].resolve():
            failures.append(("simreadyTargets", [sim1["stagePath"], sim1["podPath"]]))
        if after.get("renderer_owner_count") != 1:
            failures.append(("renderer_owner_count", after.get("renderer_owner_count")))
        if after.get("stage_open_count") != before.get("stage_open_count"):
            failures.append(("stageReopened", [before.get("stage_open_count"), after.get("stage_open_count")]))
        if [b.sha256(p) for p in SOURCES] != hashes0 or report.get("sha256") != {"stage": hashes0[0], "pod": hashes0[1]}:
            failures.append(("sourceHashes", hashes0))
        for path in FORBIDDEN_FILES:
            if path.exists():
                failures.append(("unexpectedFile", str(path)))
        for needle in ("simready.fixTargets", "SimReady fixes"):
            if needle in log_text():
                failures.append(("unexpectedLog", needle))

        result = {
            "runFixesDisabledBeforeReport": disabled_before,
            "disabledReasonShown": reason_before,
            "adjacentButtons": order,
            "reportRuleIds": report.get("ruleIds"),
            "repairable": report.get("repairable"),
            "runFixesEnabledAfterReport": enabled_after,
            "fixes": fixes,
            "activeStage": after.get("stage"),
            "renderer_owner_count": after.get("renderer_owner_count"),
            "sourceSha256": dict(zip((p.name for p in SOURCES), hashes0)),
            "fixTargetsInRunLog": "simready.fixTargets" in new_log,
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
