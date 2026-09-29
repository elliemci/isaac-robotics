"""R-17 Physics Probe.

Loads the composed Attic stage into ovphysx, advances it by fixed steps, and
reads rigid-body state. The probe is strictly read-only: it never authors USD,
never writes a pose back to ovrtx, and never touches the renderer. The current
authored scene has no PhysX rigid bodies, so the expected result is a
successful load and step with rigidBodyCount == 0 and the rendered scene still.

Contract (ovphysx >= 0.6, installed API):
  * `import ovrtx` must precede `import ovphysx` in the process.
  * PhysX USD schemas are codeless resources and must be registered with
    ovstage once, before the first population call.
  * populate an ovstage, seal its ordinal, attach it, then `step_sync(dt)`.
  * read state with `PhysX.read()`; drop every retained array before
    `PhysX.destroy()`.
"""

import gc
import importlib.util
import logging
import time
from pathlib import Path
from typing import Any

PHYSICS_FIXED_DT = 1.0 / 60.0
PHYSICS_STEP_COUNT = 1
PHYSICS_MAX_REPORTED_POSES = 64
PHYSICS_POSE_ATTRIBUTES = ("position", "orientation")
PHYSICS_STAGE_NAME = "attic-portal-physics-probe"
PHYSICS_POPULATION_ORDINAL = 1

PHYSICS_NOT_RUN = "NOT_RUN"
PHYSICS_RUNNING = "RUNNING"
PHYSICS_NOT_READY = "NOT_SIMULATION_READY"
PHYSICS_READY = "SIMULATION_READY"
PHYSICS_ERROR = "ERROR"
PHYSICS_STATUSES = (PHYSICS_NOT_RUN, PHYSICS_RUNNING, PHYSICS_NOT_READY, PHYSICS_READY, PHYSICS_ERROR)

_schemas_registered = False


def runtime_installed() -> bool:
    """True when both ovphysx and its ovstage dependency are importable.

    Uses find_spec so the check never imports either package; the real import
    happens inside run_physics_probe after ovrtx.
    """

    try:
        return all(importlib.util.find_spec(name) is not None for name in ("ovphysx", "ovstage"))
    except (ImportError, ValueError):
        return False


def initial_physics_state(stage_path: Path | str) -> dict[str, Any]:
    return {
        "runtimeInstalled": runtime_installed(),
        "runtimeVersion": "",
        "status": PHYSICS_NOT_RUN,
        "stagePath": str(stage_path),
        "loadedStagePath": "",
        "playCount": 0,
        "stepCount": 0,
        "elapsedTime": 0.0,
        "fixedDt": PHYSICS_FIXED_DT,
        "loadMs": None,
        "stepMs": None,
        "rigidBodyCount": 0,
        "rigidBodyPoses": [],
        "poseAttributes": list(PHYSICS_POSE_ATTRIBUTES),
        # A renderer pose bridge is intentionally not implemented. Handoff
        # state above is exposed for a future bridge; nothing is written back.
        "bridgeReady": False,
        "message": "Physics not run",
        "error": "",
    }


def _read_column(physx: Any, attribute: str) -> list[list[float]]:
    """Read one rigid-body attribute as row lists; empty when nothing matches."""

    from ovphysx.types import ObjectScope, SimObjectType

    rows: list[list[float]] = []
    with physx.read(SimObjectType.RIGID_BODY, [attribute], scope=ObjectScope.ALL) as result:
        for group in result.groups:
            for tensor in group.tensors:
                rows.extend(tensor.numpy().copy().reshape(int(group.prim_count), -1).tolist())
    return rows


def run_physics_probe(
    stage_usd: Path | str,
    *,
    dt: float = PHYSICS_FIXED_DT,
    steps: int = PHYSICS_STEP_COUNT,
) -> dict[str, Any]:
    """Load stage_usd into ovphysx, step it, read rigid bodies, release all.

    Must be called from the renderer-owner thread. Raises on any load, step, or
    read failure; the runtime is released either way.
    """

    global _schemas_registered
    if steps < 1 or dt <= 0.0:
        raise ValueError(f"steps must be >= 1 and dt > 0: steps={steps} dt={dt}")
    stage_usd = Path(stage_usd)
    if not stage_usd.is_file():
        raise FileNotFoundError(f"physics stage not found: {stage_usd}")

    import ovrtx  # noqa: F401  ovrtx must be imported before ovphysx.
    import ovphysx
    import ovstage
    from ovphysx import PhysX

    if not ovstage.population.available():
        raise RuntimeError("ovstage population bridge is unavailable")
    if not _schemas_registered:
        ovstage.population.register_usd_schemas([str(ovphysx.codeless_schema_root())])
        _schemas_registered = True

    physx = None
    stage = None
    attached = False
    positions: list[list[float]] = []
    orientations: list[list[float]] = []
    try:
        physx = PhysX()
        stage = ovstage.Stage(PHYSICS_STAGE_NAME)

        load_started = time.perf_counter()
        # ALL, not PHYSICS: a physics-only mask can silently omit colliders
        # under native USD scene-graph instances.
        ovstage.population.open_usd(
            stage,
            str(stage_usd),
            ordinal=PHYSICS_POPULATION_ORDINAL,
            domains=ovstage.PopulationDomain.ALL,
        )
        stage.advance_write_floor(ordinal=PHYSICS_POPULATION_ORDINAL).wait()
        physx.attach_ovstage(stage, read_ordinal=PHYSICS_POPULATION_ORDINAL)
        attached = True
        load_ms = (time.perf_counter() - load_started) * 1000.0

        step_started = time.perf_counter()
        for _ in range(steps):
            physx.step_sync(dt)
        step_ms = (time.perf_counter() - step_started) * 1000.0

        # Read after the step: direct-GPU rigid bodies produce nothing before it.
        positions = _read_column(physx, "position")
        orientations = _read_column(physx, "orientation")
        version = str(getattr(ovphysx, "__version__", ""))
    finally:
        if physx is not None and attached:
            try:
                physx.detach_ovstage()
            except Exception:
                logging.exception("ovphysx detach_ovstage failed")
        if stage is not None:
            try:
                stage.destroy()
            except Exception:
                logging.exception("ovstage destroy failed")
        if physx is not None:
            try:
                gc.collect()
                physx.destroy()
            except Exception:
                logging.exception("ovphysx destroy failed")

    poses = [
        {"position": position, "orientation": orientation}
        for position, orientation in zip(positions, orientations)
    ][:PHYSICS_MAX_REPORTED_POSES]
    return {
        "runtimeVersion": version,
        "loadedStagePath": str(stage_usd),
        "stepCount": int(steps),
        "elapsedTime": float(steps) * float(dt),
        "fixedDt": float(dt),
        "loadMs": round(load_ms, 3),
        "stepMs": round(step_ms, 3),
        "rigidBodyCount": len(positions),
        "rigidBodyPoses": poses,
    }
