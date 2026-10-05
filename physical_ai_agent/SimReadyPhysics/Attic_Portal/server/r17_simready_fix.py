"""R-17 SimReady fixer (Mission 3, Part 2).

Applies the report-driven RB.MB.001 repair: a rigid body, a mass, and an
open-top compound collision built from the pod's existing authored proxies
(never top/lid/ceiling/cap geometry), plus a physics material.

The fixer only ever writes to the output paths it is given. It exports a copy
of each source layer and edits the copy; the Mission 2 sources are never
opened for write. Callers must gate it with check_fix_guard().
"""

from pathlib import Path
from typing import Any

from r17_simready import (
    FIXES_IDLE,
    RULE_RB_MB_001,
    _find_pod,
    classify_proxies,
    memory_cube_size,
    sha256_file,
)

FIXED_MESSAGE = "fixes implemented, run report again"
POD_MASS_KG = 2.0
STATIC_FRICTION = 0.6
DYNAMIC_FRICTION = 0.5
RESTITUTION = 0.1
PHYSICS_MATERIAL_NAME = "ContainmentPhysicsMaterial"

STAGE_OUTPUT_NAME = "OldAttic_Mission_3_Fixed.usda"
POD_OUTPUT_NAME = "C9_ContainmentPod_Mission_3_Fixed.usda"


def fixed_output_paths(session_root: Path) -> tuple[Path, Path]:
    return session_root / STAGE_OUTPUT_NAME, session_root / POD_OUTPUT_NAME


def check_fix_guard(simready: dict[str, Any], stage_path: Path | str, pod_path: Path | str) -> str | None:
    """Return why a fix must be rejected, or None when it may run.

    Pure and side-effect free: the server calls it before touching anything.
    """

    report = simready.get("report")
    if not report:
        return "run targets first: there is no current validation report"
    if simready.get("fixes", {}).get("status") != FIXES_IDLE:
        return "fixes were already applied in this session"
    if RULE_RB_MB_001 not in report.get("ruleIds", []):
        return f"the current report has no {RULE_RB_MB_001} finding"
    if not report.get("repairable"):
        return f"the {RULE_RB_MB_001} finding is not repairable from the existing collision proxies"
    if report.get("stagePath") != str(stage_path) or report.get("podPath") != str(pod_path):
        return "the report targets are not the active Mission 2 sources"
    try:
        current = {"stage": sha256_file(stage_path), "pod": sha256_file(pod_path)}
    except OSError as exc:
        return f"cannot read the active sources: {exc}"
    if current != report.get("sha256"):
        return "the report is stale: a source changed since run targets"
    return None


def _prepare_outputs(sources: list[Path], outputs: list[Path]) -> None:
    resolved = {s.resolve() for s in sources}
    for out in outputs:
        if out.resolve() in resolved:
            raise ValueError(f"refusing to write over a source: {out}")
        if out.exists():
            raise FileExistsError(f"refusing to overwrite an existing output: {out}")


def _apply_pod_physics(stage, pod, cube_size: float | None) -> tuple[int, list[dict[str, str]], dict[str, Any]]:
    from pxr import Sdf, UsdGeom, UsdPhysics, UsdShade

    analysis = classify_proxies(stage, pod, cube_size)
    if not analysis["ok"]:
        raise ValueError(
            "pod opening cannot be preserved from the existing proxies "
            f"(floor={bool(analysis['floor'])}, walls={analysis['wallCount']}, slack={analysis['openingSlack']})"
        )
    applied = 0
    UsdPhysics.RigidBodyAPI.Apply(pod).CreateRigidBodyEnabledAttr(True)
    UsdPhysics.MassAPI.Apply(pod).CreateMassAttr(POD_MASS_KG)
    applied += 2

    looks = UsdGeom.Scope.Define(stage, pod.GetPath().AppendChild("Looks"))
    material = UsdShade.Material.Define(stage, looks.GetPath().AppendChild(PHYSICS_MATERIAL_NAME))
    physics_material = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics_material.CreateStaticFrictionAttr(STATIC_FRICTION)
    physics_material.CreateDynamicFrictionAttr(DYNAMIC_FRICTION)
    physics_material.CreateRestitutionAttr(RESTITUTION)
    applied += 1

    for path in analysis["usable"]:
        prim = stage.GetPrimAtPath(Sdf.Path(path))
        UsdPhysics.CollisionAPI.Apply(prim).CreateCollisionEnabledAttr(True)
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, UsdShade.Tokens.weakerThanDescendants, "physics")
        applied += 2
    return applied, analysis["rejected"], analysis


def apply_fixes(stage_path: Path | str, pod_path: Path | str, stage_out: Path | str, pod_out: Path | str) -> dict[str, Any]:
    """Write the two fixed outputs. Raises on any refusal; sources stay untouched."""

    from pxr import Sdf, Usd

    stage_path, pod_path, stage_out, pod_out = Path(stage_path), Path(pod_path), Path(stage_out), Path(pod_out)
    _prepare_outputs([stage_path, pod_path], [stage_out, pod_out])

    cube_size = memory_cube_size(Usd.Stage.Open(str(stage_path), Usd.Stage.LoadAll))
    written: list[Path] = []
    applied_total = 0
    rejected: list[dict[str, str]] = []
    try:
        for source, out in ((pod_path, pod_out), (stage_path, stage_out)):
            layer = Sdf.Layer.FindOrOpen(str(source))
            if layer is None:
                raise RuntimeError(f"cannot open {source}")
            if not layer.Export(str(out)):
                raise RuntimeError(f"cannot write {out}")
            written.append(out)
            stage = Usd.Stage.Open(str(out), Usd.Stage.LoadAll)
            pod = _find_pod(stage)
            if pod is None:
                raise ValueError(f"no containment pod in {out}")
            applied, rej, _ = _apply_pod_physics(stage, pod, cube_size)
            applied_total += applied
            rejected.extend(rej)
            stage.GetRootLayer().Save()
    except Exception:
        # A refused or failed fix must not leave half-written outputs behind.
        for out in written:
            out.unlink(missing_ok=True)
        raise
    return {
        "appliedCount": applied_total,
        "rejected": rejected,
        "outputs": [str(stage_out), str(pod_out)],
        "podPrimPath": str(_find_pod(Usd.Stage.Open(str(stage_out), Usd.Stage.LoadAll)).GetPath()),
    }
