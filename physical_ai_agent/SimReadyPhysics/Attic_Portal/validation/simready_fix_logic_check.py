#!/usr/bin/env python3
"""GPU-free logic check for the Mission 3 Part 2 fixer.

Works only on temp copies of the Mission 2 sources inside a scratch directory
and writes only temp outputs, never the real *_Mission_3_Fixed.usda paths or
R17_PhysicsOutlines.usda. Run with the portal Python (needs pxr).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "server"))

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics  # noqa: E402

import r17_physics_outlines as outlines  # noqa: E402
import r17_simready as sr  # noqa: E402
import r17_simready_fix as fix  # noqa: E402

SESSION = APP_ROOT.parent
SOURCES = [SESSION / "OldAttic_Mission_2.usda", SESSION / "C9_ContainmentPod.usda"]


def check(condition: bool, label: str, detail=None) -> None:
    print(("PASS " if condition else "FAIL ") + label + ("" if condition or detail is None else f" -> {detail}"))
    if not condition:
        raise SystemExit(1)


def fresh_copy(work: Path, name: str) -> tuple[Path, Path]:
    folder = work / name
    folder.mkdir(parents=True)
    stage, pod = (folder / s.name for s in SOURCES)
    shutil.copy(SOURCES[0], stage)
    shutil.copy(SOURCES[1], pod)
    return stage, pod


def main() -> None:
    hashes_before = [sr.sha256_file(p) for p in SOURCES]
    work = Path(tempfile.mkdtemp(prefix="simready_fix_check_"))
    try:
        stage, pod = fresh_copy(work, "base")
        result = sr.run_simready_validation(stage, pod)
        report = result["report"]
        check(sr.RULE_RB_MB_001 in report["ruleIds"] and report["repairable"], "report has repairable RB.MB.001", report["proxies"])
        check(report["proxies"]["rejected"] == [] and report["proxies"]["wallCount"] == 8, "existing proxies: floor + 8 walls, none rejected")
        check((report["proxies"]["openingSlack"] or 0) >= sr.MIN_OPENING_SLACK, "Memory Cube fits the opening", report["proxies"]["openingSlack"])

        # Guard: no report, stale hash, wrong paths, wrong rule, already applied.
        state = sr.initial_simready_state(stage, pod)
        check("run targets first" in (fix.check_fix_guard(state, stage, pod) or ""), "guard rejects without a report")
        state.update(report=report)
        check(fix.check_fix_guard(state, stage, pod) is None, "guard accepts a current repairable report")
        check("not the active" in (fix.check_fix_guard(state, stage, work / "other.usda") or ""), "guard rejects mismatched paths")
        state["report"] = {**report, "sha256": {"stage": "0" * 64, "pod": report["sha256"]["pod"]}}
        check("stale" in (fix.check_fix_guard(state, stage, pod) or ""), "guard rejects stale hashes")
        state["report"] = {**report, "ruleIds": []}
        check("no RB.MB.001" in (fix.check_fix_guard(state, stage, pod) or ""), "guard rejects a report without RB.MB.001")
        state["report"] = {**report, "repairable": False}
        check("not repairable" in (fix.check_fix_guard(state, stage, pod) or ""), "guard rejects a non-repairable report")
        state.update(report=report)
        state["fixes"]["status"] = sr.FIXES_IMPLEMENTED
        check("already applied" in (fix.check_fix_guard(state, stage, pod) or ""), "guard rejects a second fix")

        # Fix on temp copies, to temp outputs.
        stage_out, pod_out = work / "base" / "stage_fixed.usda", work / "base" / "pod_fixed.usda"
        done = fix.apply_fixes(stage, pod, stage_out, pod_out)
        check(done["appliedCount"] > 0 and done["rejected"] == [], "fix applied", done["appliedCount"])
        after = sr.run_simready_validation(stage_out, pod_out)
        check(after["missingCount"] == 0, "fixed outputs validate clean", after["missing"])
        inline = Usd.Stage.Open(str(stage_out), Usd.Stage.LoadAll)
        inline_pod = sr._find_pod(inline)
        check(inline_pod.HasAPI(UsdPhysics.RigidBodyAPI) and UsdPhysics.MassAPI(inline_pod).GetMassAttr().Get() > 0, "Mission 3 stage inline pod has rigid body and mass")
        top = [p for p in Usd.PrimRange(inline_pod, Usd.PrimAllPrimsPredicate) if p.IsA(UsdGeom.Gprim) and p.HasAPI(UsdPhysics.CollisionAPI)]
        check(len(top) == 9, "9 existing proxies carry CollisionAPI", len(top))
        try:
            fix.apply_fixes(stage, pod, stage_out, pod_out)
            check(False, "second write refuses to overwrite")
        except FileExistsError:
            check(True, "second write refuses to overwrite")
        try:
            fix.apply_fixes(stage, pod, stage, work / "x.usda")
            check(False, "refuses to write over a source")
        except ValueError:
            check(True, "refuses to write over a source")

        # Outlines: temp path with a different name, never artifacts/.
        geometry = outlines.collect_outline_geometry(pod_out)
        layer = outlines.write_outlines_layer(work / "outlines_check.usda", geometry)
        parsed = Usd.Stage.Open(str(layer))
        curves = [p for p in parsed.TraverseAll() if p.GetTypeName() == "BasisCurves"]
        check(len(curves) == 10 and layer.parent == work, "outlines: 9 CollisionAPI + 1 RigidBodyAPI curves", len(curves))

        # Lid / cover proxies are rejected, never collision geometry.
        stage_l, pod_l = fresh_copy(work, "lid")
        for name, z in (("LidProxy", 60.0), ("Cover_01", 59.0)):
            ps = Usd.Stage.Open(str(pod_l))
            cube = UsdGeom.Cube.Define(ps, f"/C9_ContainmentPod/CollisionProxies/{name}")
            cube.AddTranslateOp().Set(Gf.Vec3d(0, 0, z))
            cube.AddScaleOp().Set(Gf.Vec3d(30, 30, 1))
            ps.GetRootLayer().Save()
        rep = sr.run_simready_validation(stage_l, pod_l)["report"]
        rejected = {r["prim"].rsplit("/", 1)[-1] for r in rep["proxies"]["rejected"]}
        check({"LidProxy", "Cover_01"} <= rejected and rep["repairable"], "lid and cover proxies rejected, rest still repairable", rep["proxies"]["rejected"])
        out_s, out_p = work / "lid" / "s_fixed.usda", work / "lid" / "p_fixed.usda"
        fix.apply_fixes(stage_l, pod_l, out_s, out_p)
        fixed = Usd.Stage.Open(str(out_p))
        check(not fixed.GetPrimAtPath("/C9_ContainmentPod/CollisionProxies/LidProxy").HasAPI(UsdPhysics.CollisionAPI), "rejected lid gets no CollisionAPI")

        # Too-narrow opening: not repairable, refused, no half-written outputs.
        stage_n, pod_n = fresh_copy(work, "narrow")
        ps = Usd.Stage.Open(str(pod_n))
        for i in range(8):
            wall = ps.GetPrimAtPath(f"/C9_ContainmentPod/CollisionProxies/WallProxy_0{i}")
            wall.GetAttribute("xformOp:scale").Set(Gf.Vec3d(12, 11.6, 27))
        ps.GetRootLayer().Save()
        rep = sr.run_simready_validation(stage_n, pod_n)["report"]
        check(not rep["repairable"], "narrow opening is not repairable", rep["proxies"]["openingSlack"])
        n_out = work / "narrow" / "n.usda"
        try:
            fix.apply_fixes(stage_n, pod_n, n_out, work / "narrow" / "p.usda")
            check(False, "narrow opening refused")
        except ValueError:
            check(not n_out.exists() and not (work / "narrow" / "p.usda").exists(), "narrow opening refused, no outputs left")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    check([sr.sha256_file(p) for p in SOURCES] == hashes_before, "real sources unchanged")
    for forbidden in (SESSION / fix.STAGE_OUTPUT_NAME, SESSION / fix.POD_OUTPUT_NAME, APP_ROOT / "artifacts" / outlines.OUTLINE_LAYER_NAME):
        check(not forbidden.exists(), f"{forbidden.name} was not created")
    print("ALL PASS")


if __name__ == "__main__":
    main()
