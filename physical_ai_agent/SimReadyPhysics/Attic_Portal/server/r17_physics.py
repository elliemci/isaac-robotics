"""R-17 Physics (Mission 4).

Startup state is read-only: the physical-stage contract is read with pxr and no
ovphysx instance exists until the user clicks Play. A PhysicsSession then runs
on the renderer-owner thread, one fixed 1/60 s step at a time, and hands the
Memory Cube pose to ovrtx; nothing here authors USD or touches the renderer.

ovphysx 0.6 contract (installed API):
  * `import ovrtx` must precede `import ovphysx` in the process.
  * PhysX USD schemas are codeless resources and must be registered with
    ovstage once, before the first population call.
  * populate an ovstage, seal its ordinal, attach it, create the persistent
    RIGID_BODY_POSE binding once, then `step_sync(dt)` and `binding.read(buf)`
    into the same buffer every step.
  * release in order: binding, detach, stage, then `PhysX.destroy()` with every
    retained array dropped first.

The tensor-binding API is deprecated in 0.6 in favor of PhysX.read; it is used
here because the pose handoff needs one persistent binding reused every step.
RIGID_BODY_POSE rows are (px, py, pz, qx, qy, qz, qw), world frame.
"""

import gc
import importlib.util
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

PHYSICS_FIXED_DT = 1.0 / 60.0
PHYSICS_MAX_STEPS_PER_FRAME = 4
PHYSICS_STAGE_NAME = "attic-portal-physics"
PHYSICS_POPULATION_ORDINAL = 1
# First-read check: the simulated cube must start near its authored position.
PHYSICS_POSE_MATCH_TOLERANCE = 5.0  # stage units (cm)

PHYSICS_NOT_READY = "NOT_READY"
PHYSICS_READY_TO_RUN = "READY_TO_RUN"
PHYSICS_STARTING = "STARTING"
PHYSICS_RUNNING = "RUNNING"
PHYSICS_ERROR = "ERROR"
PHYSICS_STATUSES = (PHYSICS_NOT_READY, PHYSICS_READY_TO_RUN, PHYSICS_STARTING, PHYSICS_RUNNING, PHYSICS_ERROR)

_schemas_registered = False
_cpu_mode_set = False


def runtime_installed() -> bool:
    """True when both ovphysx and its ovstage dependency are importable.

    Uses find_spec so the check never imports either package.
    """

    try:
        return all(importlib.util.find_spec(name) is not None for name in ("ovphysx", "ovstage"))
    except (ImportError, ValueError):
        return False


def initial_physics_state(stage_path: Path | str) -> dict[str, Any]:
    """Read-only startup state from the physical-stage contract (pxr only)."""

    from r17_physics_stage import contract_failures, physical_stage_contract

    state: dict[str, Any] = {
        "runtimeInstalled": runtime_installed(),
        "runtimeVersion": "",
        "status": PHYSICS_NOT_READY,
        "playing": False,
        "stagePath": str(stage_path),
        "playCount": 0,
        "stepCount": 0,
        "elapsedTime": 0.0,
        "fixedDt": PHYSICS_FIXED_DT,
        "sceneEnabled": False,
        "sceneCount": 0,
        "rigidBodyCount": 0,
        "colliderCount": 0,
        # Set by the server once the outline layer is composed into the stage.
        "visualizationVisible": False,
        # True only while a pose binding exists and poses flow to ovrtx.
        "bridgeReady": False,
        "contract": {},
        "contractFailures": [],
        "message": "Physics stage not checked",
        "error": "",
    }
    try:
        contract = physical_stage_contract(stage_path)
    except Exception as exc:
        state.update(message="Physical stage could not be read", error=str(exc))
        return state
    failures = contract_failures(contract)
    state.update(
        contract=contract,
        contractFailures=failures,
        sceneEnabled=bool(contract["sceneEnabled"]),
        sceneCount=int(contract["sceneCount"]),
        rigidBodyCount=int(contract["rigidBodyCount"]),
        colliderCount=int(contract["colliderCount"]),
    )
    if failures:
        state.update(status=PHYSICS_NOT_READY, message="Physical stage contract not met: " + ", ".join(failures))
    elif not state["runtimeInstalled"]:
        state.update(status=PHYSICS_NOT_READY, message="ovphysx runtime is not installed")
    else:
        state.update(status=PHYSICS_READY_TO_RUN, message="Ready to run: click Play")
    return state


def pose_to_matrix(pose: np.ndarray) -> np.ndarray:
    """(px,py,pz,qx,qy,qz,qw) -> 4x4 float64, row-vector convention (translation in row 3)."""

    px, py, pz, qx, qy, qz, qw = (float(v) for v in pose)
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if not math.isfinite(norm) or norm < 1e-6:
        raise ValueError(f"invalid orientation in pose: {pose}")
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    rotation = np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ]
    )
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation.T  # row-vector convention
    matrix[3, :3] = (px, py, pz)
    return matrix


def resolve_position_scale(read_position: np.ndarray, authored_position: np.ndarray, meters_per_unit: float) -> float:
    """Scale taking ovphysx positions to stage units, checked against the authored cube.

    ovphysx reports world poses; whether those are stage units or meters is
    settled by comparing the first post-step read with where the cube was
    authored (a 1/60 s fall moves it well under a centimeter).
    """

    candidates = (1.0, 1.0 / meters_per_unit)
    for scale in candidates:
        if float(np.linalg.norm(np.asarray(read_position, dtype=np.float64) * scale - authored_position)) <= PHYSICS_POSE_MATCH_TOLERANCE:
            return scale
    raise RuntimeError(
        f"simulated cube pose {np.round(read_position, 3).tolist()} does not match its authored position "
        f"{np.round(authored_position, 3).tolist()} in stage units or meters"
    )


class PhysicsSession:
    """One ovphysx run of the Mission 4 stage. Created only on a user Play click.

    Must be created, stepped and closed from the renderer-owner thread.
    """

    def __init__(self, stage_usd: Path | str, cube_path: str):
        self.stage_usd = Path(stage_usd)
        self.cube_path = cube_path
        self.physx: Any = None
        self.stage: Any = None
        self.binding: Any = None
        self.buffer: np.ndarray | None = None
        self.attached = False
        self.version = ""

    def start(self) -> None:
        """Load the stage, wait for it, attach, and create the pose binding once."""

        global _schemas_registered, _cpu_mode_set
        if not self.stage_usd.is_file():
            raise FileNotFoundError(f"physics stage not found: {self.stage_usd}")

        import ovrtx  # noqa: F401  ovrtx must be imported before ovphysx.
        import ovphysx
        import ovstage
        from ovphysx import PhysX
        from ovphysx.types import TensorType

        if not ovstage.population.available():
            raise RuntimeError("ovstage population bridge is unavailable")
        if not _schemas_registered:
            ovstage.population.register_usd_schemas([str(ovphysx.codeless_schema_root())])
            _schemas_registered = True
        if not _cpu_mode_set:
            # Keeps ovphysx off CUDA so it cannot contend with ovrtx; also makes
            # the pose binding host-readable.
            PhysX.set_cpu_mode(True)
            _cpu_mode_set = True
        try:
            self.physx = PhysX()
            self.stage = ovstage.Stage(PHYSICS_STAGE_NAME)
            # ALL, not PHYSICS: a physics-only mask can silently omit colliders
            # under native USD scene-graph instances.
            ovstage.population.open_usd(
                self.stage,
                str(self.stage_usd),
                ordinal=PHYSICS_POPULATION_ORDINAL,
                domains=ovstage.PopulationDomain.ALL,
            )
            self.stage.advance_write_floor(ordinal=PHYSICS_POPULATION_ORDINAL).wait()
            self.physx.attach_ovstage(self.stage, read_ordinal=PHYSICS_POPULATION_ORDINAL)
            self.attached = True
            self.binding = self.physx.create_tensor_binding(
                prim_paths=[self.cube_path], tensor_type=TensorType.RIGID_BODY_POSE, raise_if_empty=True
            )
            if tuple(self.binding.shape) != (1, 7):
                raise RuntimeError(f"unexpected pose binding shape {tuple(self.binding.shape)}")
            self.buffer = np.zeros(self.binding.shape, dtype=np.float32)
            self.version = str(getattr(ovphysx, "__version__", ""))
        except Exception:
            self.close()
            raise

    def step(self, dt: float = PHYSICS_FIXED_DT) -> np.ndarray:
        """One fixed step, then read the cube pose into the reused buffer."""

        assert self.physx is not None and self.binding is not None and self.buffer is not None
        self.physx.step_sync(dt)
        self.binding.read(self.buffer)
        return self.buffer[0].astype(np.float64)

    def close(self) -> None:
        """Release in order: binding, detach, stage, runtime. Safe to call twice."""

        if self.binding is not None:
            try:
                self.binding.destroy()
            except Exception:
                logging.exception("ovphysx tensor binding destroy failed")
            self.binding = None
        self.buffer = None
        if self.physx is not None and self.attached:
            try:
                self.physx.detach_ovstage()
            except Exception:
                logging.exception("ovphysx detach_ovstage failed")
        self.attached = False
        if self.stage is not None:
            try:
                self.stage.destroy()
            except Exception:
                logging.exception("ovstage destroy failed")
            self.stage = None
        if self.physx is not None:
            try:
                gc.collect()
                self.physx.destroy()
            except Exception:
                logging.exception("ovphysx destroy failed")
            self.physx = None
