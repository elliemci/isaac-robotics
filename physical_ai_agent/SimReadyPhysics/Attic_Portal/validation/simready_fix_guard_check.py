#!/usr/bin/env python3
"""Server-side guard check for simready.fixTargets (no stream, no renderer).

Builds an AtticPortalServer without running its constructor and calls the real
handler, proving the command is rejected before anything is written: no
userInitiated flag, and no current report. Never produces a valid report and
never reaches the fixer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "server"))
sys.path.insert(0, str(APP_ROOT / ".tools" / "pydeps"))

import attic_portal_server as server  # noqa: E402
import r17_simready as sr  # noqa: E402

SESSION = APP_ROOT.parent
OUTPUTS = [SESSION / "OldAttic_Mission_3_Fixed.usda", SESSION / "C9_ContainmentPod_Mission_3_Fixed.usda", APP_ROOT / "artifacts" / "R17_PhysicsOutlines.usda"]


def check(condition: bool, label: str, detail=None) -> None:
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f" -> {detail}"))
    if not condition:
        raise SystemExit(1)


def make_server():
    portal = server.AtticPortalServer.__new__(server.AtticPortalServer)
    portal.simready_stage_path = sr.default_stage_path(SESSION)
    portal.simready_pod_path = sr.default_pod_path(SESSION)
    portal.r17_simready = sr.initial_simready_state(portal.simready_stage_path, portal.simready_pod_path)
    portal.r17_seen_request_ids = set()
    portal.r17_active_request_id = None
    portal.stage_path = portal.simready_stage_path
    portal.r17_outlines_layer = None
    portal.sent = []
    portal.send_r17_state = lambda request_id, **kw: portal.sent.append((request_id, kw))
    portal.reload_stage = lambda: portal.sent.append(("reload", {}))
    return portal


def command(request_id: str, user_initiated) -> dict:
    inner = {} if user_initiated is None else {"userInitiated": user_initiated}
    return {"requestId": request_id, "command": server.R17_SIMREADY_FIX_COMMAND, "payload": inner}


def main() -> None:
    check(server.R17_SIMREADY_FIX_COMMAND == "simready.fixTargets", "command name is simready.fixTargets")

    portal = make_server()
    portal.handle_r17_simready_fix_command("r1", command("r1", None))
    check(portal.sent[-1][1]["status"] == "ERROR" and "userInitiated" in portal.sent[-1][1]["error"], "rejected without userInitiated")

    portal.handle_r17_simready_fix_command("r2", command("r2", True))
    reply = portal.sent[-1][1]
    check(reply["status"] == "ERROR" and "run targets first" in reply["error"], "rejected without a current report", reply)
    state = portal.r17_simready
    check(state["fixes"]["status"] == "IDLE" and state["fixes"]["appliedCount"] == 0 and state["fixes"]["outlineVisible"] is False, "fixes stay unapplied, outlineVisible false")
    check(state["report"] is None and state["status"] == "IDLE", "no validation was triggered")
    check(all(entry[0] != "reload" for entry in portal.sent), "stage was not reloaded")
    check(portal.stage_path == portal.simready_stage_path and portal.r17_outlines_layer is None, "active stage and outlines unchanged")
    check(not any(path.exists() for path in OUTPUTS), "no output or outline file exists")

    # A report that is not repairable is also refused (still never reaches the fixer).
    portal = make_server()
    portal.r17_simready["report"] = {"ruleIds": [sr.RULE_RB_MB_001], "repairable": False, "stagePath": str(portal.simready_stage_path), "podPath": str(portal.simready_pod_path), "sha256": {}}
    portal.handle_r17_simready_fix_command("r3", command("r3", True))
    check("not repairable" in portal.sent[-1][1]["error"] and not any(path.exists() for path in OUTPUTS), "rejected when RB.MB.001 is not repairable")
    print("ALL PASS")


if __name__ == "__main__":
    main()
