#!/usr/bin/env python3
"""Play and cube-ownership guard check (no stream, no renderer, no physics).

Drives the real command handlers on an AtticPortalServer built without its
constructor. PhysicsSession is replaced by a tripwire, so any path that would
start ovphysx fails this check. It never starts, steps, or binds physics.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "server"))
sys.path.insert(0, str(APP_ROOT / ".tools" / "pydeps"))

import attic_portal_server as server  # noqa: E402
import r17_physics as phys  # noqa: E402


def check(condition: bool, label: str, detail=None) -> None:
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f" -> {detail}"))
    if not condition:
        raise SystemExit(1)


class Tripwire:
    constructed = 0

    def __init__(self, *args, **kwargs):
        Tripwire.constructed += 1
        raise AssertionError("PhysicsSession must not be created in this check")


server.PhysicsSession = Tripwire


def make_server(status: str, playing: bool = False):
    portal = server.AtticPortalServer.__new__(server.AtticPortalServer)
    portal.r17_physics = {
        **phys.initial_physics_state(APP_ROOT.parent / "OldAttic_Mission_4_Physics.usda"),
        "status": status, "playing": playing,
    }
    portal.r17_seen_request_ids = set()
    portal.r17_active_request_id = None
    portal.r17_physics_session = None
    portal.r17_cube_path = "/Root/Workshop/Cube"
    portal.r17_home_transform = np.eye(4)
    portal.r17_xform_binding = object()
    portal.sent = []
    portal.send_r17_state = lambda request_id, **kw: portal.sent.append((request_id, kw))
    return portal


def play(request_id: str, user_initiated):
    inner = {} if user_initiated is None else {"userInitiated": user_initiated}
    return {"requestId": request_id, "command": server.R17_PHYSICS_COMMAND, "payload": inner}


def main() -> None:
    check(server.R17_PHYSICS_COMMAND == "physics.play", "command name is physics.play")

    portal = make_server(phys.PHYSICS_READY_TO_RUN)
    portal.handle_r17_physics_command("p1", play("p1", None))
    check(portal.sent[-1][1]["status"] == "ERROR" and "userInitiated" in portal.sent[-1][1]["error"], "Play rejected without userInitiated")
    check(portal.r17_physics["status"] == phys.PHYSICS_READY_TO_RUN and not portal.r17_physics["playing"], "state still READY_TO_RUN after rejection")

    portal = make_server(phys.PHYSICS_NOT_READY)
    portal.handle_r17_physics_command("p2", play("p2", True))
    check(portal.sent[-1][1]["status"] == "ERROR" and "NOT_READY" in portal.sent[-1][1]["error"], "Play rejected when the stage contract is not met")

    portal = make_server(phys.PHYSICS_RUNNING, playing=True)
    portal.handle_r17_physics_command("p3", play("p3", True))
    check("already running" in portal.sent[-1][1]["error"], "Play rejected while already running")

    portal = make_server(phys.PHYSICS_READY_TO_RUN)
    portal.r17_xform_binding = None
    portal.handle_r17_physics_command("p4", play("p4", True))
    check("not ready" in portal.sent[-1][1]["error"], "Play rejected without a Memory Cube link")
    check(Tripwire.constructed == 0, "no PhysicsSession was ever constructed")

    # Manual cube-pose commands must not compete with physics.
    portal = make_server(phys.PHYSICS_RUNNING, playing=True)
    portal.handle_r17_command({"requestId": "c1", "command": server.R17_POSE_COMMAND, "payload": {"pose": "LEFT"}})
    reply = portal.sent[-1][1]
    check(reply["status"] == "ERROR" and "physics" in reply["error"].lower(), "cube.setPose rejected while physics is playing", reply)

    # No session: the tick does nothing and writes nothing.
    portal = make_server(phys.PHYSICS_READY_TO_RUN)
    portal.write_bound_xform = lambda *a: (_ for _ in ()).throw(AssertionError("must not write"))
    portal.physics_tick(1 / 30)
    check(portal.r17_physics["stepCount"] == 0, "physics_tick is a no-op without a session")

    # Pure helpers used by the handoff.
    ident = phys.pose_to_matrix(np.array([1, 2, 3, 0, 0, 0, 1.0]))
    check(np.allclose(ident[3, :3], [1, 2, 3]) and np.allclose(ident[:3, :3], np.eye(3)), "pose_to_matrix: identity rotation, translation in row 3")
    z90 = phys.pose_to_matrix(np.array([0, 0, 0, 0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4)]))
    check(np.allclose(np.array([1.0, 0, 0]) @ z90[:3, :3], [0, 1, 0]), "pose_to_matrix: +90 deg about Z (row-vector convention)")
    home = np.array([-620.0, -1125.0, 121.0])
    check(phys.resolve_position_scale(home + 0.1, home, 0.01) == 1.0, "pose scale: stage units detected")
    check(abs(phys.resolve_position_scale(home * 0.01, home, 0.01) - 100.0) < 1e-6, "pose scale: meters detected")
    try:
        phys.resolve_position_scale(home + 500.0, home, 0.01)
        check(False, "pose scale: mismatch rejected")
    except RuntimeError:
        check(True, "pose scale: mismatch rejected")
    print("ALL PASS")


if __name__ == "__main__":
    main()
